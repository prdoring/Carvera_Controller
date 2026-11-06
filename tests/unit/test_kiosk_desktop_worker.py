"""The elevated boundary rejects invalid jobs before selecting any physical disk."""

import bz2
import gzip
import hashlib
import io
import json
import lzma
import os
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("asyncssh")

from kioskdesktop import disk_worker
from kioskdesktop.runtime import shared


def test_original_desktop_home_is_derived_independently_of_worker_environment(monkeypatch, tmp_path):
    from kioskdesktop.elevation import origin_home

    expected = Path.home().resolve()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    if os.name != "nt":
        import pwd

        expected = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        monkeypatch.setenv("PKEXEC_UID", str(os.getuid()))
    assert origin_home(os.getpid()) == expected


def test_worker_protects_authenticated_owner_home_when_client_omits_it(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_worker, "validate_job", lambda _job: object())
    paths = []

    def select(_path, _identity, protected):
        paths.extend(protected)
        raise ValueError("isolated selection stop")

    monkeypatch.setattr(disk_worker.devices, "select", select)
    with pytest.raises(ValueError, match="isolated selection stop"):
        disk_worker.execute(
            None, {"device": {"path": "fixture", "identity": "fixture"}, "protected_paths": []}, owner_home=tmp_path
        )
    assert paths == [tmp_path]


def test_actual_pinned_imager_progress_format():
    assert disk_worker.writer_progress(b"  Writing: [---->                ] 20 %\r") == {
        "phase": "writing",
        "percent": 20,
    }
    assert disk_worker.writer_progress(b"  Verifying: [-------------------->] 100 %\r") == {
        "phase": "verifying_write",
        "percent": 100,
    }
    assert disk_worker.writer_progress(b"a malformed progress message") is None


@pytest.mark.parametrize("compress", [gzip.compress, bz2.compress, lzma.compress])
def test_settings_bound_decompression_even_for_skipped_members(compress):
    module = shared("settings")
    archive = compress(b"\0" * (module.MAX_ARCHIVE + 1))
    with pytest.raises(ValueError, match="32 MiB"):
        module.prepare_archive(io.BytesIO(archive))


def test_arbitrary_worker_destinations_never_reach_disk_selection(monkeypatch):
    monkeypatch.setattr(
        disk_worker.devices, "select", lambda *_args: pytest.fail("Invalid input reached disk selection")
    )
    with pytest.raises(ValueError, match="request"):
        disk_worker.execute(None, {"destination": "/etc", "command": "arbitrary"})


@pytest.mark.parametrize("corruption", [None, "checksum", "traversal", "extra"])
def test_opaque_writer_archive_is_validated_before_executing_any_payload(tmp_path, monkeypatch, corruption):
    executable = "rpi-imager.exe" if os.name == "nt" else "rpi-imager"
    data = b"non-executable fixture: this test must never start a writer"
    name = "../escape" if corruption == "traversal" else executable
    files = {name: "0" * 64 if corruption == "checksum" else hashlib.sha256(data).hexdigest()}
    if corruption == "traversal":
        files[executable] = hashlib.sha256(data).hexdigest()
    value = {
        "format": 1,
        "version": disk_worker.IMAGER_VERSION,
        "commit": disk_worker.IMAGER_COMMIT,
        "dependencies": disk_worker.IMAGER_DEPENDENCIES,
        "telemetry": False,
        "cli_only": True,
        "patches": {"imager-cli-windows.patch": disk_worker.IMAGER_WINDOWS_PATCH} if os.name == "nt" else {},
        "sha256": files,
    }
    with zipfile.ZipFile(tmp_path / "writer.zip", "w") as archive:
        archive.writestr("writer-manifest.json", json.dumps(value))
        for filename in files:
            archive.writestr(filename, data)
        if corruption == "extra":
            archive.writestr("unlisted-payload", b"not allowed")
    monkeypatch.setattr(disk_worker.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(
        disk_worker.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("No executable may start")
    )
    if corruption:
        with pytest.raises(ValueError):
            disk_worker.stage_writer(tmp_path / "stage")
    else:
        path = disk_worker.stage_writer(tmp_path / "stage")
        assert path.read_bytes() == data
    assert not (tmp_path / "escape").exists()
