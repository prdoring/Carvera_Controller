"""Public downloads contain complete tools without local preferences or keys."""

import hashlib
import importlib.util
import zipfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "assets/packaging/kiosk/package_release.py"
spec = importlib.util.spec_from_file_location("kiosk_package_release", SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def tools(tmp_path):
    helper = tmp_path / "kiosk.py"
    helper.write_text("print('setup helper')\n")
    novnc = tmp_path / "novnc"
    for relative in ("vnc.html", "app/ui.js", "core/rfb.js", "vendor/example.js", "LICENSE.txt"):
        target = novnc / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(relative)
    return helper, novnc


def test_laptop_zip_has_one_folder_complete_viewer_and_setup(tmp_path, tools):
    helper, novnc = tools
    output = tmp_path / "output"
    old = output / "laptop/makera.ini"
    old.parent.mkdir(parents=True)
    old.write_text("personal preferences")
    archive = release.package_laptop("1.0.0", output, helper, novnc)
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        assert all(name.startswith("laptop/") for name in names)
        assert "laptop/makera.ini" not in names
        for path in novnc.rglob("*"):
            if path.is_file():
                assert bundle.read("laptop/novnc/" + path.relative_to(novnc).as_posix()) == path.read_bytes()
        assert bundle.read("laptop/kiosk.py") == helper.read_bytes()
        assert "laptop/laptop-requirements.txt" in names
        instructions = bundle.read("laptop/README.md").decode()
        assert "carvera-kiosk-pi4-1.0.0.img.xz" in instructions
        assert "carvera-kiosk-app-1.0.0.tar.gz" in instructions
        assert "python kiosk.py prepare-card" in instructions
        assert "@VERSION@" not in instructions
    assert old.read_text() == "personal preferences"


def test_private_key_in_viewer_prevents_export(tmp_path, tools):
    helper, novnc = tools
    (novnc / "secret.pem").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nexample\n")
    with pytest.raises(ValueError, match="Private data"):
        release.package_laptop("1.0.0", tmp_path / "output", helper, novnc)
    assert not list((tmp_path / "output").glob("*.zip"))


def test_incomplete_viewer_is_rejected(tmp_path, tools):
    helper, novnc = tools
    (novnc / "core/rfb.js").unlink()
    with pytest.raises(ValueError, match="Incomplete noVNC"):
        release.package_laptop("1.0.0", tmp_path / "output", helper, novnc)


def test_checksums_cover_only_the_three_current_downloads(tmp_path):
    expected = {}
    for name in release.release_names("1.0.0"):
        data = name.encode()
        (tmp_path / name).write_bytes(data)
        expected[name] = hashlib.sha256(data).hexdigest()
    (tmp_path / "older-dev1.img.xz").write_bytes(b"old image")
    release.write_checksums("1.0.0", tmp_path)
    actual = {line.split()[1]: line.split()[0] for line in (tmp_path / "SHA256SUMS").read_text().splitlines()}
    assert actual == expected


def test_missing_download_prevents_checksums(tmp_path):
    with pytest.raises(ValueError, match="Missing or empty"):
        release.write_checksums("1.0.0", tmp_path)
    assert not (tmp_path / "SHA256SUMS").exists()
