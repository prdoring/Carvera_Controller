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

    def status(_host, action):
        assert action == "status"
        return {}

    monkeypatch.setattr(laptop, "remote", status)
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
    monkeypatch.setattr(laptop, "remote", lambda *_args: {})
    laptop.transfer_file("carvera-admin@example.invalid", "preferences.tar.gz", destination)
    assert destination.read_bytes() == b"exported"
    assert list(tmp_path.iterdir()) == [destination]


def test_stage_preserves_full_admin_identity_and_transfer_directory(laptop, monkeypatch, tmp_path):
    source = tmp_path / "preferences.tar.gz"
    source.write_bytes(b"archive")
    monkeypatch.setattr(laptop, "IDENTITY", tmp_path / "admin-key")
    monkeypatch.setattr(laptop, "HOST_KEY_ALIAS", "carvera-pi.local")
    monkeypatch.setattr(
        laptop,
        "remote",
        lambda *_args: {
            "transfers": {"uploads": "/home/kiosk-admin/transfers/uploads"},
        },
    )
    calls = []
    monkeypatch.setattr(laptop, "run", lambda args, **_kwargs: calls.append(args))
    laptop.transfer_file("kiosk-admin@192.0.2.1", source)
    assert str((tmp_path / "admin-key").resolve()) in calls[0]
    assert "IdentitiesOnly=yes" in calls[0] and "HostKeyAlias=carvera-pi.local" in calls[0]
    assert calls[0][-1] == "kiosk-admin@192.0.2.1:/home/kiosk-admin/transfers/uploads/preferences.tar.gz"


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


def test_viewer_rejects_administrator_role_before_starting_a_session(laptop, monkeypatch, tmp_path):
    (tmp_path / "vnc.html").touch()
    (tmp_path / "core").mkdir()
    (tmp_path / "core/rfb.js").touch()
    monkeypatch.setattr(laptop, "IDENTITY", "selected-key")
    monkeypatch.setattr(laptop, "remote", lambda *_args: pytest.fail("No session may start"))
    with pytest.raises(ValueError, match="carvera-admin"):
        laptop.screen("kiosk-admin@example.invalid", tmp_path)
