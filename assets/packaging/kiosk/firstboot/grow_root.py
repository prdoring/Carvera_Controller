"""Expand only the running kiosk's final ext4 root partition; resume after interruption."""

import json
import os
import stat
import struct
import subprocess
import tempfile
from pathlib import Path

STATE = Path("/var/lib/carvera-system")
BOOT = Path("/boot/firmware")
RESERVE = 256 * 1024**2


def command(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=540)
    if check and result.returncode:
        raise RuntimeError("Root storage expansion did not finish")
    return result


def read(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        raise ValueError("Invalid root storage record")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid root storage record")
    return value


def save(value):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = STATE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError("Root storage state must be private and root-owned")
    descriptor, temporary = tempfile.mkstemp(prefix=".root-grow-", dir=STATE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, STATE / "root-grow.json")
        descriptor = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def mounted(path, filesystem):
    fields = command(
        "findmnt", "--noheadings", "--raw", "--output", "SOURCE,FSTYPE", "--target", str(path)
    ).stdout.split()
    if len(fields) != 2 or fields[1] != filesystem:
        raise ValueError("Unsupported kiosk filesystem")
    device = Path(fields[0]).resolve(strict=True)
    if not stat.S_ISBLK(device.stat().st_mode):
        raise ValueError("Kiosk filesystems must use physical block partitions")
    node = (Path("/sys/class/block") / device.name).resolve(strict=True)
    if not (node / "partition").is_file():
        raise ValueError("Kiosk root must be a partition")
    return device, node


def validate_layout(mbr, *, root_start, root_size, boot_start, boot_size, capacity):
    if len(mbr) != 512 or mbr[510:] != b"\x55\xaa":
        raise ValueError("Root expansion requires the kiosk MBR layout")
    entries = []
    for index in range(4):
        offset = 446 + index * 16
        kind = mbr[offset + 4]
        start, size = struct.unpack_from("<II", mbr, offset + 8)
        if size:
            entries.append((kind, start, size))
    if (
        len(entries) != 2
        or entries[0] not in {(0xB, boot_start, boot_size), (0xC, boot_start, boot_size)}
        or entries[1] != (0x83, root_start, root_size)
        or boot_start + boot_size > root_start
        or root_start + root_size > capacity
        or not 0 < capacity < 2**32
    ):
        raise ValueError("Root expansion supports only the identified final kiosk root partition")
    return f"{struct.unpack_from('<I', mbr, 440)[0]:08x}"


def discover():
    root, root_node = mounted(Path("/"), "ext4")
    boot, boot_node = mounted(BOOT, "vfat")
    if (
        root_node.parent != boot_node.parent
        or (root_node / "partition").read_text().strip() != "2"
        or (boot_node / "partition").read_text().strip() != "1"
    ):
        raise ValueError("Root and boot must be the two partitions on the same kiosk disk")
    disk = Path("/dev") / root_node.parent.name
    if not stat.S_ISBLK(disk.stat().st_mode):
        raise ValueError("The root disk is unavailable")
    values = {
        "root_start": int((root_node / "start").read_text()),
        "root_size": int((root_node / "size").read_text()),
        "boot_start": int((boot_node / "start").read_text()),
        "boot_size": int((boot_node / "size").read_text()),
        "capacity": int((root_node.parent / "size").read_text()),
    }
    with disk.open("rb", buffering=0) as source:
        signature = validate_layout(source.read(512), **values)
    filesystem = command("blkid", "-s", "UUID", "-o", "value", str(root)).stdout.strip()
    if not filesystem or len(filesystem) > 64:
        raise ValueError("The root filesystem identity is unavailable")
    return {"disk": str(disk), "root": str(root), "signature": signature, "filesystem": filesystem, **values}


def grow():
    image = read(BOOT / "carvera-image.json")
    if image.get("format") != "carvera-kiosk-pi4-v3":
        raise ValueError("Automatic root expansion is limited to new v3 kiosk images")
    target = discover()
    identity = {key: target[key] for key in ("signature", "filesystem", "root_start")}
    path = STATE / "root-grow.json"
    previous = read(path) if path.exists() else {}
    if previous and previous.get("identity") != identity:
        raise ValueError("The interrupted root expansion belongs to another filesystem")
    full_partition = target["capacity"] - target["root_start"] - target["root_size"] < 8192
    if previous.get("phase") == "complete" and full_partition:
        return
    save({"format": 1, "phase": "prepared", "identity": identity})
    result = command("growpart", target["disk"], "2", check=False)
    # Exit 1 is documented NOCHANGE; only accept it after checking the actual geometry.
    if result.returncode not in {0, 1}:
        raise RuntimeError("Root partition expansion failed")
    expanded = discover()
    if (
        {key: expanded[key] for key in identity} != identity
        or expanded["root_size"] < target["root_size"]
        or expanded["capacity"] - expanded["root_start"] - expanded["root_size"] >= 8192
    ):
        raise ValueError("The root partition did not safely expand to the available space")
    save({"format": 1, "phase": "partition", "identity": identity})
    command("resize2fs", expanded["root"])
    storage = os.statvfs("/")
    if storage.f_bavail * storage.f_frsize < RESERVE:
        raise OSError("The root filesystem has insufficient free space after expansion")
    command("sync", "-f", "/")
    save(
        {
            "format": 1,
            "phase": "complete",
            "identity": identity,
            "filesystem_bytes": storage.f_blocks * storage.f_frsize,
        }
    )


if __name__ == "__main__":
    try:
        if os.geteuid() != 0:
            raise PermissionError("Root storage setup requires its installed service")
        grow()
    except Exception:
        raise SystemExit("Kiosk storage setup is incomplete; the next boot can retry it") from None
