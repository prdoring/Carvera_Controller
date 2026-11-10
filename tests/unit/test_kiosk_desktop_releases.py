"""Validate image content, resource bounds and complete release selection."""

import hashlib
import io
import lzma
import struct
from urllib.error import HTTPError

import pytest

from kioskdesktop import releases
from kioskdesktop.releases import Image, Release, partition_layout, verify_image


@pytest.fixture
def image_bytes():
    raw = bytearray(2 * 1024**2)
    raw[510:512] = b"\x55\xaa"
    struct.pack_into("<I", raw, 440, 0x12345678)
    for index, (kind, start, length) in enumerate(((0xC, 64, 512), (0x83, 576, 3520))):
        offset = 446 + index * 16
        raw[offset + 4] = kind
        struct.pack_into("<II", raw, offset + 8, start, length)
    data = lzma.compress(raw)
    image = Image(
        "https://example.invalid/image.xz",
        hashlib.sha256(data).hexdigest(),
        hashlib.sha256(raw).hexdigest(),
        len(data),
        len(raw),
        8 * 1024**3,
    )
    return raw, data, image


def test_raw_and_compressed_hashes_are_both_verified(image_bytes):
    _raw, data, image = image_bytes
    layout = verify_image(io.BytesIO(data), image)
    assert layout.boot_partuuid == "12345678-01"
    assert layout.root_offset == 576 * 512


@pytest.mark.parametrize("field", ["sha256", "raw_sha256", "size", "raw_size"])
def test_any_image_identity_mismatch_fails(image_bytes, field):
    from dataclasses import replace

    _raw, data, image = image_bytes
    changed = replace(image, **{field: "0" * 64 if "sha256" in field else getattr(image, field) - 1})
    with pytest.raises(ValueError):
        verify_image(io.BytesIO(data), changed)


def test_truncated_or_concatenated_images_fail(image_bytes):
    _raw, data, image = image_bytes
    for changed in (data[:-1], data + lzma.compress(b"other"), data + b"extra"):
        with pytest.raises(ValueError):
            verify_image(io.BytesIO(changed), image)


def test_cancellation_precedes_writing(image_bytes):
    _raw, data, image = image_bytes
    with pytest.raises(InterruptedError):
        verify_image(io.BytesIO(data), image, cancelled=lambda: True)


def test_overlapping_partitions_fail(image_bytes):
    raw, _data, _image = image_bytes
    struct.pack_into("<I", raw, 446 + 16 + 8, 64)
    with pytest.raises(ValueError, match="bounds"):
        partition_layout(bytes(raw[:512]), len(raw))


def test_app_only_metadata_is_not_installable():
    with pytest.raises(ValueError, match="full kiosk"):
        Release.parse({"kind": "kiosk-app", "version": "1.1.0.dev5"})


@pytest.mark.parametrize("availability", ["public", "draft", "404", "missing", "wrong-size"])
def test_viewer_link_requires_the_matching_public_asset(monkeypatch, image_bytes, availability):
    version, target = "1.1.0.dev6", "windows-x64"
    tag = f"kiosk-v{version}"
    url = f"{releases.RELEASES_PAGE}/download/{tag}/carvera-kiosk-viewer-{version}-{target}.exe"
    release = Release(version, "a" * 40, {}, image_bytes[2], {target: {"viewer": {"url": url, "size": 1024}}})

    def fetch(endpoint):
        assert endpoint == f"{releases.API}/tags/{tag}"
        if availability == "404":
            raise HTTPError(endpoint, 404, "Not Found", None, None)
        asset = {
            "browser_download_url": url,
            "state": "uploaded",
            "size": 512 if availability == "wrong-size" else 1024,
        }
        return {
            "tag_name": tag,
            "draft": availability == "draft",
            "assets": [] if availability == "missing" else [asset],
        }

    monkeypatch.setattr(releases, "fetch_json", fetch)
    assert releases.published_viewer_url(release, target) == (url if availability == "public" else None)
