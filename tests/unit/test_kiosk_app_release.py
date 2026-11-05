import hashlib
import io
import json
import tarfile
import zipfile

import pytest

from scripts.kiosk_release import checkout_commit, verify_bundle


def make_bundle(output, version="1.0.0.dev5", commit="a" * 40, metadata_version=None, manifest_changes=None):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as wheel:
        wheel.writestr(
            "carveracontroller/__version__.py",
            f'__version__ = "{version}"\n__release_version__ = "{metadata_version or version}"\n',
        )
    data = data.getvalue()
    wheel_name = f"wheels/carvera_controller_community-{version}-py3-none-any.whl"
    manifest = {
        "version": version,
        "commit": commit,
        "architecture": "aarch64",
        "python": "3.13",
        "sha256": {wheel_name: hashlib.sha256(data).hexdigest()},
    }
    manifest.update(manifest_changes or {})
    name = f"carvera-kiosk-app-{version}.tar.gz"
    archive_path = output / name
    with tarfile.open(archive_path, "w:gz") as archive:
        for entry, content in (("bundle.json", json.dumps(manifest).encode()), (wheel_name, data)):
            info = tarfile.TarInfo(entry)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    (output / (name + ".sha256")).write_text(f"{digest}  {name}\n")
    (output / f"bundle-{version}.json").write_text(json.dumps(manifest))
    return manifest


def test_verify_application_archive_manifest_wheels_and_release_identity(tmp_path):
    manifest = make_bundle(tmp_path)
    assert verify_bundle("kiosk-v1.0.0.dev5", "a" * 40, tmp_path) == manifest
    assert not (tmp_path / "SHA256SUMS").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"commit": "a" * 40 + "-dirty"},
        {"architecture": "x86_64"},
        {"python": "3.12"},
        {"version": "0.9.0"},
    ],
)
def test_release_identity_must_match_tag_and_runtime(tmp_path, changes):
    make_bundle(tmp_path, manifest_changes=changes)
    with pytest.raises(ValueError, match="identity"):
        verify_bundle("kiosk-v1.0.0.dev5", "a" * 40, tmp_path)


def test_wheel_requires_original_release_metadata(tmp_path):
    make_bundle(tmp_path, metadata_version="1.0.0.35")
    with pytest.raises(ValueError, match="version metadata"):
        verify_bundle("kiosk-v1.0.0.dev5", "a" * 40, tmp_path)


def test_bad_archive_checksum_is_rejected(tmp_path):
    make_bundle(tmp_path)
    (tmp_path / "carvera-kiosk-app-1.0.0.dev5.tar.gz").write_bytes(b"truncated")
    with pytest.raises(ValueError, match="checksum"):
        verify_bundle("kiosk-v1.0.0.dev5", "a" * 40, tmp_path)


def test_manifest_wheel_hash_is_verified(tmp_path):
    make_bundle(
        tmp_path,
        manifest_changes={
            "sha256": {
                "wheels/carvera_controller_community-1.0.0.dev5-py3-none-any.whl": "0" * 64,
            }
        },
    )
    with pytest.raises(ValueError, match="Wheel checksum"):
        verify_bundle("kiosk-v1.0.0.dev5", "a" * 40, tmp_path)


def test_dirty_or_wrong_checkout_is_rejected(monkeypatch):
    import scripts.kiosk_release as release

    for responses in (["a\n", "b\n"], ["a\n", "a\n", " M README.md\n"]):
        values = iter(responses)
        monkeypatch.setattr(release.subprocess, "check_output", lambda *args, values=values, **kwargs: next(values))
        with pytest.raises(ValueError, match="clean checkout"):
            checkout_commit("kiosk-v1.0.0.dev5")
