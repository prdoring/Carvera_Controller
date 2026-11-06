"""Create every CI writer target here; never accept a disk path from the caller."""

import argparse
import hashlib
import json
import lzma
import os
import shutil
import struct
import tempfile
import uuid
from pathlib import Path

from kiosk_boot import ASSETS, SOURCE, boot, run, write


def main(writer):
    with tempfile.TemporaryDirectory(prefix="carvera-writer-ci-") as temporary:
        work = Path(temporary)
        root = work / "root"
        shutil.copytree("/guest", root, symlinks=True)
        assets = root / "opt/ci-assets"
        assets.mkdir(parents=True)
        shutil.copytree(writer, assets / "writer")
        shutil.copytree(
            SOURCE / "kioskdesktop", root / "opt/ci-source/kioskdesktop", ignore=shutil.ignore_patterns("__pycache__")
        )
        shutil.copytree(ASSETS / "runtime", assets / "runtime", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(SOURCE / "tests/boot/kiosk_writer_guest.py", root / "usr/local/lib/writer-guest.py")
        for directory in ("dev", "proc", "sys", "run"):
            (root / directory).mkdir(exist_ok=True)
        boot_tree = work / "boot"
        boot_tree.mkdir()
        image_identity = {"format": "carvera-kiosk-pi4-v3", "version": "test", "commit": "a" * 40, "setup_protocol": 1}
        (boot_tree / "carvera-image.json").write_text(json.dumps(image_identity))
        (boot_tree / "carvera-setup.json").write_text(json.dumps({"protocol": 1, "phase": "fresh"}))
        fat, filesystem, raw = work / "boot.img", work / "data.ext4", work / "source.img"
        volume_size = 64 * 1024**2
        for path in (fat, filesystem):
            with path.open("xb") as output:
                output.truncate(volume_size)
        run("mkfs.vfat", "-F", "32", fat)
        run("mcopy", "-i", fat, "-s", *boot_tree.iterdir(), "::/")
        run("mkfs.ext4", "-q", "-F", filesystem)
        boot_start, root_start = 2048, 2048 + volume_size // 512
        with raw.open("xb") as output:
            mbr = bytearray(512)
            struct.pack_into("<I", mbr, 440, 0xC1A0C1A0)
            for index, (kind, start) in enumerate(((0xC, boot_start), (0x83, root_start))):
                offset = 446 + index * 16
                mbr[offset + 4] = kind
                struct.pack_into("<II", mbr, offset + 8, start, volume_size // 512)
            mbr[510:] = b"\x55\xaa"
            output.write(mbr)
            for path, start in ((fat, boot_start), (filesystem, root_start)):
                output.seek(start * 512)
                with path.open("rb") as incoming:
                    shutil.copyfileobj(incoming, output)
        compressed = assets / "source.img.xz"
        with raw.open("rb") as incoming, lzma.open(compressed, "wb", preset=1) as output:
            shutil.copyfileobj(incoming, output)
        keys = []
        for name in ("maintenance", "administrator"):
            key = work / name
            run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key)
            keys.append(key.with_suffix(".pub").read_text().strip())
        capacity = 256 * 1024**2
        prefix = "CARVERA-CI-"
        serial = prefix + uuid.uuid4().hex[: 20 - len(prefix)]
        assert len(serial) == 20

        def digest(path):
            with path.open("rb") as incoming:
                return hashlib.file_digest(incoming, "sha256").hexdigest()

        (assets / "test.json").write_text(
            json.dumps(
                {
                    "serial": serial,
                    "capacity": capacity,
                    "image": {
                        "url": "https://example.invalid/ci.img.xz",
                        "sha256": digest(compressed),
                        "raw_sha256": digest(raw),
                        "size": compressed.stat().st_size,
                        "raw_size": raw.stat().st_size,
                        "minimum_capacity": capacity,
                    },
                    "request": {
                        "format": 2,
                        "setup_protocol": 1,
                        "id": "a" * 32,
                        "hostname": "ci-kiosk",
                        "authorized_keys": keys[:1],
                        "admin_public_keys": keys[1:],
                    },
                }
            )
        )
        write(
            root,
            "/etc/systemd/system/writer-check.service",
            "[Unit]\nAfter=local-fs.target systemd-udev-settle.service\nWants=systemd-udev-settle.service\n"
            "FailureAction=poweroff\n[Service]\nType=oneshot\n"
            "ExecStart=/usr/bin/python3 /usr/local/lib/writer-guest.py\n"
            "StandardOutput=journal+console\nStandardError=journal+console\n[Install]\nWantedBy=multi-user.target\n",
        )
        run("chroot", root, "systemctl", "enable", "writer-check.service")
        system, target = work / "system.ext4", work / "exact-new-card.img"
        with system.open("xb") as output:
            output.truncate(1536 * 1024**2)
        run("mkfs.ext4", "-q", "-F", "-d", root, system)
        with target.open("xb") as output:
            output.truncate(capacity)
        assert target.resolve().parent == work.resolve() and target.is_file() and not target.is_symlink()
        reports = Path(os.environ.get("CARVERA_BOOT_REPORTS", "/tmp"))
        reports.mkdir(parents=True, exist_ok=True)
        report = reports / "carvera-writer-ci.log"
        boot(
            system,
            next((root / "boot").glob("vmlinuz-*")),
            next((root / "boot").glob("initrd.img-*")),
            "root=/dev/vda rw console=ttyS0 rootwait noresume",
            report,
            (
                "-drive",
                f"file={target},format=raw,if=none,id=ci-card",
                "-device",
                f"virtio-blk-pci,drive=ci-card,serial={serial}",
            ),
        )
        assert b"PASS: protected virtual selection" in report.read_bytes(), report
        print("PASS: isolated writer and real filesystem remount", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer", type=Path, required=True)
    main(parser.parse_args().writer.resolve(strict=True))
