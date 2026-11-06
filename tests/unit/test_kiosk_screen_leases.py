"""Owned screen sessions expire without blocking on long application updates."""

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

fcntl = pytest.importorskip("fcntl")
RUNTIME = Path(__file__).resolve().parents[2] / "assets/packaging/kiosk/runtime"


@pytest.fixture
def sessions(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(RUNTIME))
    value = importlib.import_module("screen_sessions")
    monkeypatch.setattr(value, "RUN", tmp_path)
    clock = {"now": 100.0}
    monkeypatch.setattr(value.time, "monotonic", lambda: clock["now"])
    current = {"pid": 123, "invocation": "a" * 32}
    monkeypatch.setattr(value, "service_identity", lambda: dict(current))
    calls = []
    monkeypatch.setattr(value, "command", lambda *args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0))
    owner = {**current, "generation": "b" * 32, "token": "c" * 64, "expires": 190.0, "lease_protocol": 1}
    value.write_json(tmp_path / "screen.json", owner)
    return value, clock, current, owner, calls


def token(owner):
    return {key: owner[key] for key in ("token", "generation")}


def test_renewal_does_not_take_global_lock_for_more_than_90_seconds(sessions):
    module, clock, _current, owner, _calls = sessions
    with (module.RUN / "control.lock").open("w") as global_lock:
        fcntl.flock(global_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for tick in range(120, 301, 20):
            clock["now"] = tick
            assert module.renew(token(owner))["renewed"]
    assert module.read_json(module.RUN / "screen.json")["expires"] == 390


def test_expired_lease_cannot_be_revived(sessions):
    module, clock, _current, owner, calls = sessions
    clock["now"] = 191
    with pytest.raises(ValueError, match="expired"):
        module.renew(token(owner))
    assert ("systemctl", "stop", module.SERVICE) in calls
    assert not (module.RUN / "screen.json").exists()


def test_lease_expiring_during_service_validation_cannot_be_revived(sessions, monkeypatch):
    module, clock, current, owner, calls = sessions

    def delayed_identity():
        clock["now"] = 200
        return dict(current)

    monkeypatch.setattr(module, "service_identity", delayed_identity)
    with pytest.raises(ValueError, match="expired"):
        module.renew(token(owner))
    assert not (module.RUN / "screen.json").exists()
    assert ("systemctl", "stop", module.SERVICE) in calls


def test_stale_expiry_never_stops_replacement(sessions):
    module, clock, current, _owner, calls = sessions
    current.update(pid=456, invocation="d" * 32)
    clock["now"] = 200
    assert not module.expire()
    assert not any(call[:2] == ("systemctl", "stop") for call in calls)


def test_wrong_token_or_generation_preserves_live_session(sessions):
    module, _clock, _current, owner, calls = sessions
    for wrong in ({**token(owner), "token": "wrong"}, {**token(owner), "generation": "d" * 32}):
        with pytest.raises(ValueError):
            module.stop(wrong)
    assert (module.RUN / "screen.json").exists()
    assert calls == []


def test_clients_must_negotiate_before_starting_remote_service(sessions):
    module, _clock, _current, _owner, calls = sessions
    with pytest.raises(ValueError, match="protocol 1"):
        module.start(None)
    assert calls == []
