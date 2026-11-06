"""Read the generated image itself, including boot identity and the installed growth path."""

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create(image, compressed, output, source):
    with image.open("rb") as stream:
        mbr = stream.read(512)
    if len(mbr) != 512 or mbr[510:] != b"\x55\xaa" or mbr[450] not in {0xB, 0xC} or mbr[466] != 0x83:
        raise ValueError("The produced image has an unsupported layout")
    offset = struct.unpack_from("<I", mbr, 454)[0] * 512
    identity = json.loads(subprocess.check_output(["mtype", "-i", f"{image}@@{offset}", "::/carvera-image.json"]))
    if identity.get("format") != "carvera-kiosk-pi4-v3" or identity.get("setup_protocol") != 1:
        raise ValueError("The produced image is not a GUI-managed image")
    root = image.parent / "root.ext4"
    if not root.is_file():
        raise ValueError("The generated ext4 artifact is needed to verify the installed first-boot mechanism")
    checks = {
        "/usr/local/lib/carvera/grow_root.py": source / "firstboot/grow_root.py",
        "/etc/systemd/system/carvera-root-grow.service": source
        / "overlay/etc/systemd/system/carvera-root-grow.service",
    }
    for name, expected in checks.items():
        actual = subprocess.check_output(["debugfs", "-R", "cat " + name, str(root)], stderr=subprocess.DEVNULL)
        if actual != expected.read_bytes():
            raise ValueError("The generated image is missing its tested first-boot storage implementation")
    metadata = {
        "format": 1,
        "identity": identity,
        "raw_size": image.stat().st_size,
        "size": compressed.stat().st_size,
        "raw_sha256": sha256(image),
        "sha256": sha256(compressed),
        "minimum_capacity": max(7 * 1024**3, image.stat().st_size + 256 * 1024**2),
        "root_growth": {"protocol": 1, "implementation": "growpart/resize2fs", "reserve_bytes": 256 * 1024**2},
    }
    output.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("compressed", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    create(args.image, args.compressed, args.output, args.source)
