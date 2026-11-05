"""Laptop operations must stay local until a host is explicitly selected."""

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def laptop():
    path = Path(__file__).resolve().parents[2] / "scripts/kiosk.py"
    spec = importlib.util.spec_from_file_location("kiosk_laptop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_device_commands_require_an_explicit_host(laptop, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["kiosk.py", "status"])
    monkeypatch.setattr(laptop, "run", lambda *_a, **_k: pytest.fail("Must not invoke SSH"))
    with pytest.raises(SystemExit) as result:
        laptop.main()
    assert result.value.code == 2


def test_stage_only_uploads_without_deploying(laptop, monkeypatch, tmp_path):
    source = tmp_path / "preferences.tar.gz"
    source.write_bytes(b"archive")
    calls = []
    monkeypatch.setattr(laptop, "run", lambda args, **_kwargs: calls.append(args))
    monkeypatch.setattr(laptop, "remote", lambda *_args, **_kwargs: pytest.fail("Staging must not deploy"))
    result = laptop.transfer_file("carvera-admin@example.invalid", source)
    assert result == {"staged": source.name}
    assert len(calls) == 1 and calls[0][0] == "scp"
    assert "StrictHostKeyChecking=yes" in calls[0]
    assert calls[0][-1].endswith("/uploads/preferences.tar.gz")


def test_fetch_does_not_overwrite_an_existing_file(laptop, monkeypatch, tmp_path):
    destination = tmp_path / "preferences.tar.gz"
    destination.write_bytes(b"original")
    monkeypatch.setattr(laptop, "run", lambda *_a, **_k: pytest.fail("Do not fetch over existing files"))
    with pytest.raises(FileExistsError):
        laptop.transfer_file("carvera-admin@example.invalid", "preferences.tar.gz", destination)
    assert destination.read_bytes() == b"original"


def test_fetch_downloads_to_a_private_temporary_file(laptop, monkeypatch, tmp_path):
    destination = tmp_path / "preferences.tar.gz"

    def download(args, **_kwargs):
        assert args[0] == "scp" and "/exports/" in args[-2]
        assert args[-1] != destination
        Path(args[-1]).write_bytes(b"exported")

    monkeypatch.setattr(laptop, "run", download)
    laptop.transfer_file("carvera-admin@example.invalid", "preferences.tar.gz", destination)
    assert destination.read_bytes() == b"exported"
    assert list(tmp_path.iterdir()) == [destination]


def test_remote_password_is_sent_on_stdin_not_in_arguments(laptop, monkeypatch):
    seen = []

    def run(args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(stdout="{}")

    monkeypatch.setattr(laptop, "run", run)
    laptop.remote("carvera-admin@example.invalid", "network", {"ssid": "Workshop", "password": "secret-test-value"})
    arguments, options = seen[0]
    assert "secret-test-value" not in str(arguments)
    assert json.loads(options["input"])["value"]["password"] == "secret-test-value"
    assert "StrictHostKeyChecking=yes" in arguments


def test_card_requires_kiosk_image_identity(laptop, tmp_path):
    with pytest.raises(ValueError, match="identified"):
        laptop.prepare_card(tmp_path, "unused.pub", "carvera-pi", None, None)
    (tmp_path / "carvera-image.json").write_text('{"format":"other-image"}')
    with pytest.raises(ValueError, match="unexpected"):
        laptop.prepare_card(tmp_path, "unused.pub", "carvera-pi", None, None)


def test_card_archive_contains_only_valid_preferences(laptop, tmp_path):
    source = tmp_path / "backup.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        for name, content in {
            "files/.kivy/config.ini": b"[carvera]\nandroid_ui_scale=1.1\n",
            "files/.carveracontroller/gcodes/job.nc": b"G0 X100",
            "files/.kivy/plugin.py": b"raise Exception()",
            "../escape.json": b"{}",
        }.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    output = tmp_path / "preferences.tar.gz"
    laptop.pack_settings(source, output)
    with tarfile.open(output) as archive:
        assert archive.getnames() == [".kivy/config.ini"]
        assert b"android_ui_scale=1.1" in archive.extractfile(".kivy/config.ini").read()


def test_failed_viewer_stops_only_the_screen_session_it_started(laptop, monkeypatch, tmp_path):
    (tmp_path / "vnc.html").touch()
    monkeypatch.setitem(sys.modules, "websockify", SimpleNamespace())
    requests, stopped = [], []

    def remote(_host, action, value=None):
        requests.append((action, value))
        return {"owned": True, "token": "owned-session"}

    process = object()
    monkeypatch.setattr(laptop, "remote", remote)
    monkeypatch.setattr(laptop.subprocess, "Popen", lambda *_a, **_k: process)
    monkeypatch.setattr(laptop, "unused_port", lambda: 49999)
    monkeypatch.setattr(laptop, "wait_port", lambda *_a: (_ for _ in ()).throw(RuntimeError("failed viewer")))
    monkeypatch.setattr(laptop, "stop_owned", stopped.append)
    with pytest.raises(RuntimeError, match="failed viewer"):
        laptop.screen("carvera-admin@example.invalid", tmp_path)
    assert stopped == [process]
    assert requests == [("screen-start", None), ("screen-stop", "owned-session")]
