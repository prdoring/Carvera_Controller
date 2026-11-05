import json
import subprocess
import time
from types import SimpleNamespace

import pytest

from carveracontroller.ui.kiosk_legacy import LegacySystem, validate_wifi


@pytest.fixture
def backend(tmp_path):
    runtime, maintenance = tmp_path / "runtime", tmp_path / "maintenance"
    runtime.mkdir()
    maintenance.mkdir()
    (runtime / "status.json").write_text(
        json.dumps({"updated": time.monotonic(), "busy": False, "connected": False, "maintenance": False})
    )
    return LegacySystem(runtime, maintenance)


def test_legacy_schema_is_exact_and_password_never_enters_arguments(backend, monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        request = json.loads(kwargs["input"])
        assert request == {
            "action": "wifi",
            "wifi": {"ssid": "Workshop", "password": "secret-pass"},
            "confirmed_idle": True,
        }
        (backend.maintenance / "maintenance.request").write_text('{"token":"own"}')
        return SimpleNamespace(returncode=0, stdout='{"confirm_within_seconds":120}', stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    backend.perform("wifi", confirmed_idle=True, ssid="Workshop", password="secret-pass")
    assert backend.token == "own"
    assert 118 <= backend.remaining() <= 120
    assert "secret-pass" not in str(calls[0][0])
    assert calls[0][1]["timeout"] == 60


@pytest.mark.parametrize("change", [{"busy": True}, {"updated": 0}, {"maintenance": True}])
def test_legacy_guard_rejects_busy_stale_and_existing_maintenance(backend, change, monkeypatch):
    path = backend.runtime / "status.json"
    status = json.loads(path.read_text())
    status.update(change)
    path.write_text(json.dumps(status))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("Do not call helper"))
    with pytest.raises(ValueError):
        backend.perform("restart", confirmed_idle=True)


def test_preexisting_request_is_never_taken_over(backend):
    (backend.maintenance / "maintenance.request").write_text('{"token":"laptop"}')
    with pytest.raises(ValueError, match="already active"):
        backend.guard("wifi")
    backend.token = "different"
    with pytest.raises(ValueError, match="already active"):
        backend.guard("restart")


def test_own_wifi_only_allows_keep_before_deadline_and_restart_afterwards(backend):
    path = backend.maintenance / "maintenance.request"
    path.write_text('{"token":"own"}')
    backend.token = "own"
    backend.wifi_started = time.monotonic()
    backend.wifi_attempted = True
    backend.guard("wifi-confirm")
    with pytest.raises(ValueError, match="wait"):
        backend.guard("restart")
    backend.wifi_started -= 121
    assert backend.remaining() == 0
    with pytest.raises(ValueError, match="expired"):
        backend.guard("wifi-confirm")
    backend.guard("restart")
    assert path.exists()


def test_failed_wifi_never_claims_a_possibly_concurrent_session(backend, monkeypatch):
    def run(*_args, **_kwargs):
        (backend.maintenance / "maintenance.request").write_text('{"token":"own"}')
        raise subprocess.TimeoutExpired("sudo", 60)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError, match="unknown"):
        backend.perform("wifi", confirmed_idle=True, ssid="Workshop", password="secret-pass")
    assert backend.token is None and backend.wifi_attempted and backend.uncertain
    with pytest.raises(ValueError):
        backend.guard("wifi")


def test_successful_keep_uses_old_raw_response_and_releases_local_ownership(backend, monkeypatch):
    backend.token, backend.wifi_attempted, backend.wifi_started = "own", True, time.monotonic()
    path = backend.maintenance / "maintenance.request"
    path.write_text('{"token":"own"}')

    def run(_args, **kwargs):
        assert json.loads(kwargs["input"]) == {"action": "wifi-confirm", "confirmed_idle": True}
        path.unlink()
        return SimpleNamespace(returncode=0, stdout='{"network_confirmed":true}', stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    assert backend.perform("wifi-confirm", confirmed_idle=True) == {"network_confirmed": True}
    assert backend.wifi_kept and backend.token is None and backend.remaining() == 0


@pytest.mark.parametrize("action", ["open", "shutdown", "display", "restore", "leave"])
def test_unsupported_actions_are_never_sent(backend, action):
    with pytest.raises(ValueError, match="does not support"):
        backend.perform(action, confirmed_idle=True)


@pytest.mark.parametrize(
    "ssid,password",
    [
        ("", "secret-pass"),
        ("network", "short"),
        ("x" * 33, "secret-pass"),
        ("network", "secret\npass"),
        ("network", "é" * 32),
    ],
)
def test_wifi_validation_uses_bytes_and_rejects_control_characters(ssid, password):
    with pytest.raises(ValueError):
        validate_wifi(ssid, password)


def test_mutations_always_need_operator_confirmation(backend):
    with pytest.raises(ValueError, match="Confirm"):
        backend.perform("restart")


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=1, stdout="", stderr="rejected"),
        SimpleNamespace(returncode=0, stdout="{}", stderr=""),
        SimpleNamespace(returncode=0, stdout="broken", stderr=""),
    ],
)
def test_failed_or_invalid_response_never_adopts_a_concurrent_request(backend, monkeypatch, result):
    def run(*_args, **_kwargs):
        (backend.maintenance / "maintenance.request").write_text('{"token":"laptop"}')
        return result

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError):
        backend.perform("wifi", confirmed_idle=True, ssid="Workshop", password="secret-pass")
    assert backend.token is None and backend.uncertain
    with pytest.raises(ValueError, match="unknown"):
        backend.guard("restart")
