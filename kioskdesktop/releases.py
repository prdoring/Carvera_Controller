"""Discover complete kiosk releases and validate image bytes before erasure."""

from __future__ import annotations

import hashlib
import json
import lzma
import re
import struct
import urllib.request
from dataclasses import dataclass
from typing import BinaryIO

REPOSITORY = "prdoring/Carvera_Controller"
API = f"https://api.github.com/repos/{REPOSITORY}/releases"
MAX_METADATA = 256 * 1024
MAX_IMAGE = 64 * 1024**3
IMAGE_FORMAT = "carvera-kiosk-pi4-v3"
COMPATIBILITY = {"provisioning_format": 2, "setup_protocol": 1, "screen_lease_protocol": 1, "minimum_updater": 2}


def version(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:\.dev\d+|rc\d+)?", value):
        raise ValueError("Invalid kiosk release version")
    return value


def digest(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise ValueError("Invalid release checksum")
    return value


def download_url(value: object, release_version: str) -> str:
    prefix = f"https://github.com/{REPOSITORY}/releases/download/kiosk-v{release_version}/"
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError("Release downloads must come from this fork and tag")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", value[len(prefix) :]):
        raise ValueError("Invalid release asset name")
    return value


def fetch_json(url: str, limit=MAX_METADATA):
    request = urllib.request.Request(url, headers={"User-Agent": "Carvera-Kiosk-Setup", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Release metadata exceeds its size limit")
    return json.loads(data)


@dataclass(frozen=True)
class Image:
    url: str
    sha256: str
    raw_sha256: str
    size: int
    raw_size: int
    minimum_capacity: int


@dataclass(frozen=True)
class Release:
    version: str
    commit: str
    components: dict[str, str]
    image: Image
    downloads: dict

    def document(self):
        from dataclasses import asdict

        return {"format": 1, "image_format": IMAGE_FORMAT, "compatibility": COMPATIBILITY, **asdict(self)}

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict) or value.get("format") != 1 or value.get("image_format") != IMAGE_FORMAT:
            raise ValueError("This is not a compatible full kiosk release")
        if value.get("compatibility") != COMPATIBILITY:
            raise ValueError("This release requires different setup, provisioning or viewer protocols")
        release_version = version(value.get("version"))
        commit = value.get("commit")
        if not isinstance(commit, str) or not re.fullmatch("[a-f0-9]{40}", commit):
            raise ValueError("A full source revision is required")
        components = value.get("components")
        if not isinstance(components, dict) or set(components) != {"image", "controller", "system", "updater"}:
            raise ValueError("Component versions are incomplete")
        for component in components.values():
            version(component)
        raw = value.get("image")
        if not isinstance(raw, dict):
            raise ValueError("The release has no flashable image")
        sizes = [raw.get(name) for name in ("size", "raw_size", "minimum_capacity")]
        if any(type(size) is not int or not 512 <= size <= MAX_IMAGE for size in sizes):
            raise ValueError("Invalid image sizes")
        if sizes[2] < sizes[1] or sizes[1] % 512:
            raise ValueError("Invalid minimum card capacity")
        image = Image(
            download_url(raw.get("url"), release_version),
            digest(raw.get("sha256")),
            digest(raw.get("raw_sha256")),
            *sizes,
        )
        downloads = value.get("downloads")
        targets = {"windows-x64", "linux-x64", "linux-arm64"}
        if not isinstance(downloads, dict) or set(downloads) != targets:
            raise ValueError("Desktop downloads are incomplete")
        for target in targets:
            if not isinstance(downloads[target], dict) or set(downloads[target]) != {"setup", "viewer"}:
                raise ValueError("Setup and viewer downloads are required")
            for asset in downloads[target].values():
                if not isinstance(asset, dict) or type(asset.get("size")) is not int or asset["size"] <= 0:
                    raise ValueError("Invalid desktop download")
                download_url(asset.get("url"), release_version)
                digest(asset.get("sha256"))
        return cls(release_version, commit, components, image, downloads)


def discover(previews=False) -> list[Release]:
    result = []
    for page in range(1, 11):
        releases = fetch_json(f"{API}?per_page=100&page={page}", limit=2 * 1024**2)
        if not isinstance(releases, list) or len(releases) > 100:
            raise ValueError("Unexpected release catalogue")
        for item in releases:
            if not isinstance(item, dict) or item.get("draft") is not False:
                continue
            if not previews and item.get("prerelease") is not False:
                continue
            tag = item.get("tag_name", "")
            if not isinstance(tag, str) or not tag.startswith("kiosk-v"):
                continue
            try:
                release_version = version(tag[7:])
            except ValueError:
                continue
            assets = item.get("assets", [])
            manifest = next(
                (
                    asset
                    for asset in assets
                    if isinstance(asset, dict)
                    and asset.get("name") == "setup-release.json"
                    and asset.get("state") == "uploaded"
                ),
                None,
            )
            if manifest is None:
                continue
            url = download_url(manifest.get("browser_download_url"), release_version)
            release = Release.parse(fetch_json(url))
            if release.version != release_version:
                raise ValueError("Release metadata does not match its tag")
            result.append(release)
        if len(releases) < 100:
            return result
    raise ValueError("Release catalogue pagination exceeds its limit")


@dataclass(frozen=True)
class Layout:
    boot_offset: int
    boot_size: int
    boot_partuuid: str
    root_offset: int
    root_size: int


def partition_layout(mbr: bytes, raw_size: int) -> Layout:
    if len(mbr) != 512 or mbr[510:] != b"\x55\xaa":
        raise ValueError("The image has no supported MBR partition table")
    entries = []
    for index in range(4):
        offset = 446 + 16 * index
        kind = mbr[offset + 4]
        start, length = struct.unpack_from("<II", mbr, offset + 8)
        if length:
            entries.append((kind, start * 512, length * 512))
    if len(entries) != 2 or entries[0][0] not in {0xB, 0xC} or entries[1][0] != 0x83:
        raise ValueError("Expected the kiosk FAT/ext4 partition layout")
    boot, root = entries
    if not 512 <= boot[1] <= 64 * 1024**2 or boot[1] + boot[2] > root[1] or root[1] + root[2] > raw_size:
        raise ValueError("Invalid kiosk partition bounds")
    disk = struct.unpack_from("<I", mbr, 440)[0]
    return Layout(boot[1], boot[2], f"{disk:08x}-01", root[1], root[2])


def verify_image(source: BinaryIO, image: Image, progress=lambda _count: None, cancelled=lambda: False) -> Layout:
    """Bound XZ memory and output; validate both hashes before any disk mutation."""
    compressed, raw = hashlib.sha256(), hashlib.sha256()
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=256 * 1024**2)
    input_count = output_count = 0
    prefix = bytearray()
    source.seek(0)
    while True:
        if cancelled():
            raise InterruptedError("Image verification cancelled")
        chunk = source.read(1024**2) if decoder.needs_input else b""
        if decoder.needs_input and not chunk:
            break
        input_count += len(chunk)
        if input_count > image.size:
            raise ValueError("Image download exceeds its declared length")
        compressed.update(chunk)
        block = decoder.decompress(chunk, max_length=1024**2)
        output_count += len(block)
        if output_count > image.raw_size:
            raise ValueError("Decompressed image exceeds its declared length")
        raw.update(block)
        if len(prefix) < 512:
            prefix.extend(block[: 512 - len(prefix)])
        progress(output_count)
        if decoder.eof:
            if decoder.unused_data or source.read(1):
                raise ValueError("Unexpected data after the compressed image")
            break
    if (
        not decoder.eof
        or input_count != image.size
        or output_count != image.raw_size
        or compressed.hexdigest() != image.sha256
        or raw.hexdigest() != image.raw_sha256
    ):
        raise ValueError("Image size or checksum verification failed")
    return partition_layout(bytes(prefix), output_count)
