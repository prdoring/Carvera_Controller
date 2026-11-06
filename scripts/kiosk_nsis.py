"""Stage the checksummed portable NSIS compiler without installing system software."""

import argparse
import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

VERSION = "3.13"
SHA256 = "ba63dffc4410ee89193e1cb5a41989991bd77c61068da17e3156d136b7b0b3d8"
LENGTH = 2363925


def fetch(folder, archive_path=None):
    if archive_path is not None:
        data = archive_path.read_bytes()
    else:
        # This package mirrors the unchanged upstream portable ZIP and records its upstream checksum.
        url = "https://community.chocolatey.org/api/v2/package/nsis.portable/3.13.0"
        with urllib.request.urlopen(url, timeout=60) as response:
            package = response.read(8 * 1024**2 + 1)
        if len(package) > 8 * 1024**2:
            raise ValueError("The compiler package exceeds its download limit")
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            entry = archive.getinfo("tools/nsis-3.13.zip")
            if entry.file_size != LENGTH:
                raise ValueError("Unexpected portable compiler length")
            data = archive.read(entry)
    if len(data) != LENGTH or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("The portable compiler does not match its pinned checksum")
    folder = folder.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        if len(entries) > 4096 or sum(entry.file_size for entry in entries) > 64 * 1024**2:
            raise ValueError("Invalid portable compiler inventory")
        for entry in entries:
            target = folder / entry.filename
            if target.is_symlink() or not target.resolve().is_relative_to(folder):
                raise ValueError("Invalid compiler archive path")
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            content = archive.read(entry)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError("The cached compiler changed; select a new cache folder")
            else:
                with target.open("xb") as output:
                    output.write(content)
    compiler = folder / "nsis-3.13/makensis.exe"
    if not compiler.is_file():
        raise ValueError("The compiler package is incomplete")
    return compiler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    print(fetch(args.folder, args.archive))
