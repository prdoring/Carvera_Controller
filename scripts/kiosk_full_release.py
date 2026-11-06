"""Assemble and verify complete graphical-installation releases before publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kioskdesktop.releases import COMPATIBILITY, IMAGE_FORMAT, Release, verify_image, version

TARGETS = ("windows-x64", "linux-x64", "linux-arm64")


def required(version_value):
    names = {f"carvera-kiosk-{kind}-{version_value}.tar.gz" for kind in ("app", "system", "updater")}
    names |= {
        f"carvera-kiosk-pi4-{version_value}.img.xz",
        f"carvera-kiosk-laptop-{version_value}.zip",
        "setup-release.json",
        "image-metadata.json",
        "NOTICES.txt",
        "SHA256SUMS",
    }
    for target in TARGETS:
        for kind in ("setup", "viewer"):
            stem = f"carvera-kiosk-{kind}-{version_value}-{target}"
            names |= {
                stem + suffix for suffix in ((".exe", ".zip") if target.startswith("windows") else (".deb", ".tar.gz"))
            }
    return names


def checksum(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def asset(path, version_value):
    return {
        "url": f"https://github.com/prdoring/Carvera_Controller/releases/download/kiosk-v{version_value}/{path.name}",
        "sha256": checksum(path),
        "size": path.stat().st_size,
    }


def bundle(path, manifest_name, release_version, commit):
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        mapping = {item.name: item for item in members}
        if len(mapping) != len(members) or any(not item.isfile() for item in members):
            raise ValueError("Release bundles must contain unique regular files")
        manifest_member = mapping.get(manifest_name)
        if manifest_member is None or manifest_member.size > 256 * 1024:
            raise ValueError("Bundle manifest is missing or oversized")
        value = json.load(archive.extractfile(manifest_member))
        if value.get("version") != release_version or value.get("commit") != commit:
            raise ValueError("A bundle's actual embedded identity does not match the tag")
        if set(mapping) != {manifest_name, *value["sha256"]}:
            raise ValueError("A bundle contains unexpected payload files")
        if sum(item.size for item in members) > 1024**3:
            raise ValueError("Release bundle exceeds its expanded limit")
        for name, expected in value["sha256"].items():
            if hashlib.file_digest(archive.extractfile(name), "sha256").hexdigest() != expected:
                raise ValueError("A bundle payload checksum changed")
    return value


def desktop_identity(path):
    """Read the actual embedded metadata, including inside installed distributions."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            matches = [
                entry for entry in archive.infolist() if entry.filename.endswith("/_internal/desktop-build.json")
            ]
            if len(matches) != 1 or matches[0].file_size > 16384:
                raise ValueError("Desktop metadata is missing or ambiguous")
            return json.loads(archive.read(matches[0]))
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            matches = [entry for entry in archive if entry.name.endswith("/_internal/desktop-build.json")]
            if len(matches) != 1 or not matches[0].isfile() or matches[0].size > 16384:
                raise ValueError("Desktop metadata is missing or ambiguous")
            return json.load(archive.extractfile(matches[0]))
    if path.suffix == ".deb":
        # dpkg-deb checks its container and streams the data tar without installing anything.
        process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(path)], stdout=subprocess.PIPE)
        try:
            result = None
            with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
                for member in archive:
                    if member.name.endswith("/_internal/desktop-build.json"):
                        if result is not None or not member.isfile() or member.size > 16384:
                            raise ValueError("Invalid installed desktop identity")
                        result = json.load(archive.extractfile(member))
            if process.wait(timeout=30) or result is None:
                raise ValueError("The Debian package is incomplete")
            return result
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
    executable = shutil.which("7z") or shutil.which("7zz")
    if not executable:
        raise ValueError("7-Zip is required to verify Windows installer contents")
    listing = subprocess.check_output([executable, "l", "-slt", str(path)], text=True, timeout=60)
    matches = [
        line[7:]
        for line in listing.splitlines()
        if line.startswith("Path = ") and line.replace("\\", "/").endswith("/_internal/desktop-build.json")
    ]
    # NSIS archives can expose the payload without an $INSTDIR prefix.
    if not matches:
        matches = [
            line[7:]
            for line in listing.splitlines()
            if line.startswith("Path = ") and line[7:].replace("\\", "/") == "_internal/desktop-build.json"
        ]
    if len(matches) != 1:
        raise ValueError("The Windows installer identity is missing or ambiguous")
    process = subprocess.Popen(
        [executable, "x", "-so", str(path), matches[0]], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    try:
        data = process.stdout.read(16385)
        if len(data) > 16384 or process.wait(timeout=30):
            raise ValueError("Invalid Windows installer identity")
        return json.loads(data)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def laptop_identity(path, release_version, commit):
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 4096 or sum(member.file_size for member in members) > 64 * 1024**2:
            raise ValueError("The laptop tools exceed their release bounds")
        names = {member.filename for member in members}
        if len(names) != len(members) or any(member.is_dir() for member in members):
            raise ValueError("The laptop tools contain duplicate or unexpected entries")
        info = archive.getinfo("laptop/laptop-build.json")
        if info.file_size > 512 * 1024:
            raise ValueError("The laptop tools inventory is oversized")
        metadata = json.loads(archive.read(info))
        if (metadata.get("format"), metadata.get("version"), metadata.get("commit")) != (1, release_version, commit):
            raise ValueError("The laptop tools do not match this release")
        files = metadata.get("sha256", {})
        if names != {"laptop/laptop-build.json", *("laptop/" + name for name in files)}:
            raise ValueError("The laptop tools do not match their embedded inventory")
        required_files = {
            "kiosk.py",
            "kiosk_admin.py",
            "bootstrap/bootstrap.sh",
            "bootstrap/admin_accounts.py",
            "bootstrap/admin_bootstrap.py",
            "bootstrap/system_update.py",
            "bootstrap/setup_protocol.py",
            "bootstrap/settings.py",
            "kioskdesktop/viewer.py",
            "kioskdesktop/viewer_server.py",
            "novnc/vnc.html",
            "novnc/core/rfb.js",
            "laptop-requirements.txt",
        }
        if not required_files <= files.keys():
            raise ValueError("The laptop tools are missing a bootstrap, updater or viewer component")
        for name, expected in files.items():
            if hashlib.sha256(archive.read("laptop/" + name)).hexdigest() != expected:
                raise ValueError("The laptop tools changed after packaging")


def assemble(output, release_version, commit):
    version(release_version)
    if not re.fullmatch("[a-f0-9]{40}", commit):
        raise ValueError("Resolve a full source commit before building")
    if ".dev" not in release_version and "rc" not in release_version:
        raise ValueError("Desktop Windows signing is not configured; full releases must be prereleases")
    expected = required(release_version)
    present = {path.name for path in output.iterdir() if path.is_file()}
    missing = expected - {"setup-release.json", "SHA256SUMS", "NOTICES.txt"} - present
    if missing:
        raise ValueError("Missing full-release assets: " + ", ".join(sorted(missing)))
    metadata = json.loads((output / "image-metadata.json").read_text(encoding="utf-8"))
    identity = metadata["identity"]
    if (identity.get("format"), identity.get("version"), identity.get("commit")) != (
        IMAGE_FORMAT,
        release_version,
        commit,
    ):
        raise ValueError("Image identity does not match this release")
    image = asset(output / f"carvera-kiosk-pi4-{release_version}.img.xz", release_version)
    if image["sha256"] != metadata["sha256"] or image["size"] != metadata["size"]:
        raise ValueError("The produced image changed after verification")
    image.update({name: metadata[name] for name in ("raw_sha256", "raw_size", "minimum_capacity")})
    downloads = {
        target: {
            kind: asset(
                output
                / (
                    f"carvera-kiosk-{kind}-{release_version}-{target}"
                    + (".exe" if target.startswith("windows") else ".deb")
                ),
                release_version,
            )
            for kind in ("setup", "viewer")
        }
        for target in TARGETS
    }
    value = {
        "format": 1,
        "image_format": IMAGE_FORMAT,
        "compatibility": COMPATIBILITY,
        "version": release_version,
        "commit": commit,
        "components": dict.fromkeys(("image", "controller", "system", "updater"), release_version),
        "image": image,
        "downloads": downloads,
    }
    Release.parse(value)
    (output / "setup-release.json").write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    (output / "NOTICES.txt").write_text(
        "Carvera Kiosk Setup and Screen Share\nWindows packages are unsigned prereleases.\n"
        "Licenses and dependency versions are bundled in each application's _internal/notices and Slate fonts directories.\n"
        "The pinned Imager writer carries its own notices, source URLs and any recorded Windows CLI patch.\n"
        "Source and rebuild instructions: https://github.com/prdoring/Carvera_Controller\n",
        encoding="utf-8",
    )
    for name in expected - {"SHA256SUMS"}:
        if not (output / name).is_file():
            raise ValueError("A required release file is missing")
    (output / "SHA256SUMS").write_text(
        "".join(f"{checksum(output / name)}  {name}\n" for name in sorted(expected - {"SHA256SUMS"})), encoding="utf-8"
    )
    verify(output, release_version, commit)


def verify(output, release_version, commit):
    if {path.name for path in output.iterdir()} != required(release_version):
        raise ValueError("Publication requires the exact complete asset inventory")
    lines = (output / "SHA256SUMS").read_text().splitlines()
    hashes = {}
    for line in lines:
        if not re.fullmatch(r"[a-f0-9]{64}  [A-Za-z0-9][A-Za-z0-9._-]*", line):
            raise ValueError("Invalid release checksum entry")
        digest, name = line.split("  ")
        if name in hashes:
            raise ValueError("Duplicate release checksum")
        hashes[name] = digest
    if set(hashes) != required(release_version) - {"SHA256SUMS"}:
        raise ValueError("Checksum coverage is incomplete")
    for name, expected in hashes.items():
        if checksum(output / name) != expected:
            raise ValueError("A release asset checksum changed")
    release = Release.parse(json.loads((output / "setup-release.json").read_text()))
    if (release.version, release.commit) != (release_version, commit):
        raise ValueError("Release metadata does not match its resolved source")
    with (output / f"carvera-kiosk-pi4-{release_version}.img.xz").open("rb") as source:
        verify_image(source, release.image)
    for kind, manifest in (
        ("app", "bundle.json"),
        ("system", "system-bundle.json"),
        ("updater", "updater-bundle.json"),
    ):
        bundle(output / f"carvera-kiosk-{kind}-{release_version}.tar.gz", manifest, release_version, commit)
    laptop_identity(output / f"carvera-kiosk-laptop-{release_version}.zip", release_version, commit)
    for target in TARGETS:
        for kind in ("setup", "viewer"):
            stem = f"carvera-kiosk-{kind}-{release_version}-{target}"
            suffixes = (".exe", ".zip") if target.startswith("windows") else (".deb", ".tar.gz")
            identities = [desktop_identity(output / (stem + suffix)) for suffix in suffixes]
            if identities[0] != identities[1] or any(
                identities[0].get(key) != expected
                for key, expected in (
                    ("kind", kind),
                    ("version", release_version),
                    ("commit", commit),
                    ("platform", target),
                    ("dirty", False),
                    ("setup_protocol", 1),
                    ("screen_lease_protocol", 1),
                )
            ):
                raise ValueError("Installed and portable desktop identities differ from this release")
            if not identities[0].get("python", "").startswith("3.12."):
                raise ValueError("Desktop packages require the independent Python 3.12 runtime")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("assemble", "verify"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    (assemble if args.action == "assemble" else verify)(args.output, args.version, args.commit)
