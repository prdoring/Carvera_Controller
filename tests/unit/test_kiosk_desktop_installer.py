"""Persist exact retries and bind the final consent to the worker-held medium."""

import hashlib
import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("asyncssh")

from kioskdesktop import devices, installer, profiles
from kioskdesktop.releases import Image, Release


@pytest.fixture
def prepared(tmp_path):
    version, commit = "1.1.0.dev5", "c" * 40
    prefix = f"https://github.com/prdoring/Carvera_Controller/releases/download/kiosk-v{version}/"
    image = Image(prefix + "card.img.xz", "a" * 64, "b" * 64, 1024, 2048, 8 * 1024**3)
    downloads = {
        target: {
            kind: {"url": prefix + kind + "-" + target + ".zip", "size": 512, "sha256": "e" * 64}
            for kind in ("setup", "viewer")
        }
        for target in ("windows-x64", "linux-x64", "linux-arm64")
    }
    release = Release(
        version, commit, dict.fromkeys(("image", "controller", "system", "updater"), version), image, downloads
    )
    path, profile = profiles.create("kiosk-test", "test-key-passphrase", "test-key-passphrase", directory=tmp_path)
    wifi = {"ssid": "Workshop", "password": "private-wifi-value", "country": "US"}
    installer.prepare(path, profile, release, wifi)
    return path, profile, release, wifi


def test_retry_retains_same_request_keys_and_wifi_and_rejects_changed_inputs(prepared):
    path, profile, release, wifi = prepared
    original = (path.parent / "transaction.json").read_bytes()
    installer.prepare(path, profile, release, wifi)
    assert (path.parent / "transaction.json").read_bytes() == original
    with pytest.raises(ValueError, match="different installation"):
        installer.prepare(path, profile, release, {**wifi, "ssid": "Another network"})
    assert (path.parent / "transaction.json").read_bytes() == original
    assert wifi["password"] not in path.read_text()
    assert wifi["password"] not in (path.parent / "release.json").read_text()


def test_verified_handoff_removes_private_setup_inputs_but_retains_release(prepared):
    path, profile, release, wifi = prepared
    profile["stage"] = "verified"
    installer.finish_verification(path, profile)
    assert not (path.parent / "transaction.json").exists()
    assert installer.load_release(path, profile) == release
    assert all(wifi["password"] not in item.read_text() for item in path.parent.glob("*.json"))


def test_failed_new_attempt_does_not_resume_from_an_old_completed_card_record(prepared, tmp_path):
    path, profile, _release, wifi = prepared
    status_path = path.parent / "card-status.json"
    status_path.write_text(json.dumps({"id": profile["id"], "phase": "complete"}))
    operation = installer.CardOperation()
    with pytest.raises(OSError):
        operation.run(None, path, profile, action="flash", image=tmp_path / "missing.img.xz")
    assert json.loads(status_path.read_text())["phase"] == "preparing"
    assert wifi["password"] not in status_path.read_text()


def test_worker_client_waits_for_physical_confirmation_and_cancels_without_consent(prepared, monkeypatch, tmp_path):
    path, profile, release, _wifi = prepared
    selected = devices.Device("fixture-card", "d" * 64, 8 * 1024**3, "Disposable fixture", "usb", False, False, False)
    image = tmp_path / "image.img.xz"
    image.write_bytes(b"x" * release.image.size)
    jobs, payloads = [], []
    token = "f" * 64
    operation = installer.CardOperation()

    class Channel:
        def send(self, value):
            jobs.append(value)

        def write(self, data):
            payloads.append(data)

        def receive(self):
            return {
                "phase": "awaiting_confirmation",
                "device": selected.public(),
                "confirmation": token,
                "erases": True,
            }

        def alive(self):
            return True

    class Endpoint:
        def __init__(self):
            self.channel = Channel()

        def accept(self, *_args):
            return self.channel

        def close(self):
            pass

    monkeypatch.setattr(installer.ipc, "Endpoint", Endpoint)
    monkeypatch.setattr(installer.elevation, "launch", lambda _endpoint: SimpleNamespace(pid=123, poll=lambda: 0))

    def cancel_after_review(value):
        if value["phase"] == "awaiting_confirmation":
            operation.cancel()

    with pytest.raises(InterruptedError, match="cancelled"):
        operation.run(selected, path, profile, action="flash", image=image, progress=cancel_after_review)
    assert b"".join(payloads) == image.read_bytes()
    assert len(jobs) == 1 and jobs[0]["configuration"]["id"] == profile["id"]
    assert all("confirm" not in request for request in jobs)


def test_preferences_bytes_are_bound_into_the_private_transaction(prepared, tmp_path):
    path, profile, release, _wifi = prepared
    # A separate new profile permits a preferences choice before the first card write.
    new_path, new_profile = profiles.create("kiosk-test", "passphrase", "passphrase", directory=tmp_path)
    source = tmp_path / "preferences.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        member = tarfile.TarInfo(".kivy/config.ini")
        content = b"[carvera]\nexample = retained\n"
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    value = installer.prepare(new_path, new_profile, release, preferences=source)
    payload = (new_path.parent / "preferences.tar.gz").read_bytes()
    assert value["configuration"]["settings_sha256"] == hashlib.sha256(payload).hexdigest()
    assert json.loads(new_path.read_text())["stage"] == "prepared"
