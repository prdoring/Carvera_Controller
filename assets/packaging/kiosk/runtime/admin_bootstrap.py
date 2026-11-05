"""One-time owner-approved administrator migration from the boot partition."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from admin_accounts import LEGACY_FORMAT, STATE, atomic_write, install, read_json, request_identity, write_json

BOOT = Path("/boot/firmware")
BASE = Path("/opt/carvera")


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout


def block_identity():
    devices = json.loads(
        command("lsblk", "--json", "--bytes", "--output", "NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS")
    )
    for disk in devices["blockdevices"]:
        children = disk.get("children", [])
        root = next((child for child in children if "/" in (child.get("mountpoints") or [])), None)
        boot = next((child for child in children if "/boot/firmware" in (child.get("mountpoints") or [])), None)
        if root and boot:
            return {
                "capacity": int(disk["size"]),
                "boot_uuid": boot.get("uuid"),
                "boot_partuuid": boot.get("partuuid"),
                "root_partuuid": root.get("partuuid"),
            }
    raise ValueError("The boot and root partitions are not on the expected single card")


def validate_target(request):
    request_identity(request)
    expected = request.get("target", {})
    actual = block_identity()
    if any(
        actual.get(name) != expected.get(name) for name in ("capacity", "boot_uuid", "boot_partuuid", "root_partuuid")
    ):
        raise ValueError("The migration package is for a different card")
    fingerprint = command("ssh-keygen", "-l", "-E", "sha256", "-f", "/etc/ssh/ssh_host_ed25519_key.pub").split()[1]
    if fingerprint != expected.get("ssh_fingerprint"):
        raise ValueError("The migration package is for a different SSH identity")
    image = read_json(BOOT / "carvera-image.json")
    if image.get("format") != LEGACY_FORMAT or image != expected.get("image"):
        raise ValueError("The migration package does not match the installed legacy image")
    original = base64.b64decode(request.get("original_cmdline", ""), validate=True)
    if hashlib.sha256(original).hexdigest() != expected.get("cmdline_sha256"):
        raise ValueError("The saved boot command line is invalid")
    if len(original) > 16384 or len(original.splitlines()) != 1:
        raise ValueError("The saved boot command line must be one line")
    return original


def infrastructure(source, request):
    identity, request_digest = request_identity(request)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = STATE / "infrastructure.json"
    checksums = {
        name: hashlib.sha256((source / name).read_bytes()).hexdigest()
        for name in ("system_update.py", "admin_accounts.py", "kiosk_state.py")
    }
    expected = {"id": identity, "request_digest": request_digest, "sha256": checksums}
    recorded = read_json(marker)
    if recorded and recorded != expected:
        raise ValueError("A different infrastructure migration already exists")
    link = BASE / "updater"
    relative = Path("updater-releases") / ("bootstrap-" + identity)
    updater = BASE / relative
    if link.exists() or link.is_symlink():
        if not recorded or not link.is_symlink() or link.readlink() != relative:
            raise ValueError("Review the existing updater installation before migration")
    if not recorded:
        write_json(marker, expected)
    updater.mkdir(mode=0o755, parents=True, exist_ok=True)
    for name in ("system_update.py", "admin_accounts.py", "kiosk_state.py"):
        atomic_write(updater / name, (source / name).read_bytes(), 0o644)
    write_json(
        updater / "updater-bundle.json",
        {
            "kind": "kiosk-updater",
            "format": 1,
            "version": "bootstrap-" + identity,
            "updater_version": 1,
            "sha256": checksums,
        },
    )
    if not link.is_symlink():
        link.symlink_to(relative, target_is_directory=True)
    atomic_write(
        Path("/usr/local/sbin/carvera-system-update"),
        '#!/bin/sh\nset -eu\nexec /usr/bin/python3 -E -s /opt/carvera/updater/system_update.py "$@"\n',
        0o755,
    )
    atomic_write(
        Path("/etc/systemd/system/carvera-system-recover.service"),
        "[Unit]\nDescription=Recover an interrupted Carvera system update\nAfter=local-fs.target\n"
        "Before=carvera-kiosk.service carvera-cpu.service carvera-provision.service\n[Service]\nType=oneshot\n"
        "ExecStart=/usr/local/sbin/carvera-system-update recover boot\nRemainAfterExit=yes\n"
        "[Install]\nWantedBy=multi-user.target\n",
        0o644,
    )
    atomic_write(
        Path("/etc/systemd/system/carvera-kiosk.service.d/10-system-recovery.conf"),
        "[Unit]\nRequires=carvera-system-recover.service\nAfter=carvera-system-recover.service\n",
        0o644,
    )
    command("systemctl", "daemon-reload")
    command("systemctl", "enable", "carvera-system-recover.service")


def migrate(path):
    if os.geteuid() != 0:
        raise ValueError("Run this migration only during the dedicated root boot")
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError("Migration request is too large")
    request = read_json(path)
    original = validate_target(request)
    identity, digest = request_identity(request)
    current = (BOOT / "cmdline.txt").read_bytes()
    if current != base64.b64decode(request["staged_cmdline"], validate=True):
        raise ValueError("The staged boot command line changed")
    # A failed boot-volume write must be detected before granting access.
    probe = BOOT / ".kiosk-migration-write-check"
    atomic_write(probe, b"ok\n")
    probe.unlink()
    completed = read_json(STATE / "access-complete.json")
    result = {"id": identity, "ssh_fingerprint": request["target"]["ssh_fingerprint"]}
    try:
        if completed and (completed.get("id"), completed.get("digest")) != (identity, digest):
            raise ValueError("Administrator setup already completed; this request cannot replace its keys")
        if not completed:
            infrastructure(path.parent, request)
        answer = install(request)
        result.update(phase="complete", account=answer["account"], key_fingerprints=answer["key_fingerprints"])
    except Exception as error:
        result.update(phase="failed", error=str(error))
        raise
    finally:
        atomic_write(BOOT / "cmdline.txt", original, 0o644)
        write_json(BOOT / "kiosk-admin-migration-result.json", result)
    path.unlink(missing_ok=True)
    return result


if __name__ == "__main__":
    try:
        print(json.dumps(migrate(sys.argv[1])))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("Administrator migration failed: " + str(error), file=sys.stderr)
        sys.exit(1)
