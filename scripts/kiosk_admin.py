"""Laptop preparation and transport for kiosk administrator operations."""

import base64
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import time
import uuid
from pathlib import Path

BOOTSTRAP = "kiosk-admin-bootstrap"
FILES = ("admin_accounts.py", "admin_bootstrap.py", "system_update.py", "kiosk_state.py", "bootstrap.sh")


def assets():
    bundled = Path(__file__).resolve().parent / "bootstrap"
    if bundled.is_dir():
        return bundled
    return Path(__file__).resolve().parents[1] / "assets/packaging/kiosk/runtime"


def account_module():
    spec = importlib.util.spec_from_file_location("kiosk_account_schema", assets() / "admin_accounts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def key_files(paths):
    if not paths:
        raise ValueError("Supply at least one --admin-public-key")
    values = [Path(path).expanduser().read_text(encoding="utf-8") for path in paths]
    return account_module().public_keys(values)


def sha256(path):
    with Path(path).open("rb") as incoming:
        return hashlib.file_digest(incoming, "sha256").hexdigest()


def remote_bytes(ssh, host, *arguments):
    return subprocess.run([*ssh(host), *arguments], capture_output=True, check=True, timeout=30).stdout


def target_report(ssh, host):
    image = json.loads(remote_bytes(ssh, host, "cat", "/boot/firmware/carvera-image.json"))
    if image.get("format") != "carvera-kiosk-pi4":
        raise ValueError("This migration is for an existing legacy kiosk image")
    original = remote_bytes(ssh, host, "cat", "/boot/firmware/cmdline.txt")
    if len(original) > 16384 or len(original.splitlines()) != 1:
        raise ValueError("Unexpected boot command line")
    fingerprint = (
        remote_bytes(ssh, host, "ssh-keygen", "-l", "-E", "sha256", "-f", "/etc/ssh/ssh_host_ed25519_key.pub")
        .decode()
        .split()[1]
    )
    blocks = json.loads(
        remote_bytes(
            ssh, host, "lsblk", "--json", "--bytes", "--output", "NAME,TYPE,SIZE,FSTYPE,UUID,PARTUUID,MOUNTPOINTS"
        )
    )
    for disk in blocks["blockdevices"]:
        children = disk.get("children", [])
        root = next((child for child in children if "/" in (child.get("mountpoints") or [])), None)
        boot = next((child for child in children if "/boot/firmware" in (child.get("mountpoints") or [])), None)
        if root and boot and boot.get("fstype") == "vfat":
            return {
                "image": image,
                "ssh_fingerprint": fingerprint,
                "capacity": int(disk["size"]),
                "boot_uuid": boot["uuid"],
                "boot_partuuid": boot["partuuid"],
                "root_partuuid": root["partuuid"],
                "cmdline_sha256": hashlib.sha256(original).hexdigest(),
                "controller": json.loads(remote_bytes(ssh, host, "cat", "/opt/carvera/current/bundle.json")),
            }, original
    raise ValueError("The kiosk does not use the supported single-card layout")


def prepare(ssh, host, public_key_paths, output):
    keys, fingerprints = key_files(public_key_paths)
    target, original = target_report(ssh, host)
    if any(token in original.decode().split() for token in ("single", "rescue")) or any(
        marker in original for marker in (b"systemd.run=", b"systemd.unit=", b"init=")
    ):
        raise ValueError("Review the existing special boot arguments before migration")
    directory = Path(output).expanduser().resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    source = assets()
    repository = Path(__file__).resolve().parents[1]
    for name in FILES:
        path = source / name
        if not path.exists() and name == "kiosk_state.py":
            path = repository / "carveracontroller/kiosk_state.py"
        if not path.exists() and name == "bootstrap.sh":
            path = source.parent / "admin-bootstrap.sh"
        shutil.copyfile(path, directory / name)
    line = original.rstrip(b"\r\n") + (
        b' systemd.run="/bin/bash /boot/firmware/kiosk-admin-bootstrap/bootstrap.sh"'
        b" systemd.run_success_action=reboot systemd.run_failure_action=poweroff\n"
    )
    request = {
        "format": 2,
        "id": uuid.uuid4().hex,
        "legacy_gate": True,
        "admin_public_keys": keys,
        "target": target,
        "original_cmdline": base64.b64encode(original).decode(),
        "staged_cmdline": base64.b64encode(line).decode(),
    }
    (directory / "request.json").write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
    (directory / "cmdline.before").write_bytes(original)
    names = [*FILES, "request.json", "cmdline.before"]
    (directory / "payload.sha256").write_text(
        "".join(f"{sha256(directory / name)}  {name}\n" for name in names), encoding="ascii"
    )
    return {
        "prepared": str(directory),
        "target": target,
        "admin_key_fingerprints": fingerprints,
        "next": "Shut down safely, make two independent full-card backups, then stage the package",
    }


def volume_identity(boot):
    """Read disk metadata only; never open a disk for writing."""
    boot = Path(boot)
    if os.name == "nt":
        if not re.fullmatch(r"[A-Za-z]:[\\/]", boot.anchor) or boot != Path(boot.anchor):
            raise ValueError("Select the local boot volume root, such as E:/")
        serial = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetVolumeInformationW(
            str(boot), None, 0, ctypes.byref(serial), None, None, None, 0
        ):
            raise OSError("Could not identify the boot volume")
        drive = boot.anchor[0]
        script = (
            f"Get-Partition -DriveLetter {drive} | Get-Disk | "
            "Select-Object Number,Size,BusType | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        disk = json.loads(result.stdout)
        value = f"{serial.value:08X}"
        return {"capacity": int(disk["Size"]), "boot_uuid": value[:4] + "-" + value[4:], "disk": disk["Number"]}
    result = subprocess.run(
        ["lsblk", "--json", "--bytes", "--output", "NAME,SIZE,UUID,MOUNTPOINTS"],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    for disk in json.loads(result.stdout)["blockdevices"]:
        for partition in disk.get("children", []):
            if str(boot) in (partition.get("mountpoints") or []):
                return {"capacity": int(disk["size"]), "boot_uuid": partition.get("uuid"), "disk": disk["name"]}
    raise ValueError("Select the actual mounted boot volume")


def verify_package(directory):
    directory = Path(directory)
    expected = {*FILES, "request.json", "cmdline.before"}
    if {path.name for path in directory.iterdir()} != expected | {"payload.sha256"}:
        raise ValueError("Unexpected files in the migration payload")
    found = set()
    for line in (directory / "payload.sha256").read_text(encoding="ascii").splitlines():
        checksum, separator, name = line.partition("  ")
        if not separator or name not in expected or name in found or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Invalid migration payload manifest")
        path = directory / name
        if path.is_symlink() or not path.is_file() or sha256(path) != checksum:
            raise ValueError("The migration payload changed")
        found.add(name)
    if found != expected:
        raise ValueError("Migration payload is incomplete")
    request = json.loads((directory / "request.json").read_text(encoding="utf-8"))
    account_module().request_identity(request)
    return request


def backup_identity(path):
    with Path(path).open("rb") as source:
        mbr = source.read(512)
        if len(mbr) != 512 or mbr[510:512] != b"\x55\xaa":
            raise ValueError("The backup does not contain the expected MBR card layout")
        disk_id = f"{struct.unpack_from('<I', mbr, 440)[0]:08x}"
        partitions = {}
        for index in range(4):
            offset = 446 + 16 * index
            kind = mbr[offset + 4]
            start, sectors = struct.unpack_from("<II", mbr, offset + 8)
            if sectors:
                partitions[f"{disk_id}-{index + 1:02x}"] = (kind, start * 512, sectors * 512)
        boot = next(
            ((identity, values) for identity, values in partitions.items() if values[0] in {0x0B, 0x0C, 0x06, 0x0E}),
            None,
        )
        if boot is None:
            raise ValueError("The backup has no expected FAT boot partition")
        source.seek(boot[1][1])
        sector = source.read(512)
        if len(sector) != 512:
            raise ValueError("The backup boot partition is truncated")
        serial_offset = 67 if sector[82:90].startswith(b"FAT32") else 39
        serial = struct.unpack_from("<I", sector, serial_offset)[0]
        text = f"{serial:08X}"
        return {"boot_uuid": text[:4] + "-" + text[4:], "boot_partuuid": boot[0], "partitions": partitions}


def verify_backups(first, second, target):
    first, second = Path(first), Path(second)
    capacity = target["capacity"]
    if first.is_symlink() or second.is_symlink() or os.path.samefile(first, second):
        raise ValueError("Select two separate, independent full-card reads")
    if first.stat().st_size != capacity or second.stat().st_size != capacity or sha256(first) != sha256(second):
        raise ValueError("Both backup sizes must match the card and both SHA-256 hashes must match")
    observed = backup_identity(first)
    if (
        str(observed["boot_uuid"]).upper() != str(target["boot_uuid"]).upper()
        or observed["boot_partuuid"] != target["boot_partuuid"]
        or target["root_partuuid"] not in observed["partitions"]
    ):
        raise ValueError("The backup partition identity does not match this kiosk card")
    return {"image": str(first.resolve()), "sha256": sha256(first), "bytes": capacity}


def stage(boot, package, first_backup, second_backup):
    boot, package = Path(boot).resolve(strict=True), Path(package).resolve(strict=True)
    request = verify_package(package)
    target = request["target"]
    actual = volume_identity(boot)
    if actual["capacity"] != target["capacity"] or str(actual["boot_uuid"]).upper() != str(target["boot_uuid"]).upper():
        raise ValueError("The selected physical card/boot volume does not match the target report")
    if json.loads((boot / "carvera-image.json").read_text()) != target["image"]:
        raise ValueError("The selected image does not match the target report")
    original = (boot / "cmdline.txt").read_bytes()
    if hashlib.sha256(original).hexdigest() != target["cmdline_sha256"]:
        raise ValueError("Boot arguments changed since the target was captured")
    destination = boot / BOOTSTRAP
    if destination.exists() or destination.is_symlink():
        raise ValueError("A migration is already staged; inspect or undo it first")
    if (boot / "carvera-provision.json").exists():
        raise ValueError("Finish or remove the pending initial provisioning request before migration")
    backup = verify_backups(first_backup, second_backup, target)
    if (
        shutil.disk_usage(boot).free
        < sum(path.stat().st_size for path in package.iterdir() if path.is_file()) + 1024 * 1024
    ):
        raise ValueError("Insufficient space on the boot volume")
    shutil.copytree(package, destination)
    try:
        verify_package(destination)
        account_module().atomic_write(
            boot / "cmdline.txt", base64.b64decode(request["staged_cmdline"], validate=True), 0o644
        )
    except Exception:
        account_module().atomic_write(boot / "cmdline.txt", original, 0o644)
        raise
    return {
        "staged": request["id"],
        "disk": actual,
        "backup": backup,
        "next": "Safely eject the card. Keep the mill disconnected. The dedicated boot reboots once on success.",
    }


def undo(boot, retained_package=None):
    boot = Path(boot).resolve(strict=True)
    package = Path(retained_package).resolve(strict=True) if retained_package else boot / BOOTSTRAP
    path = package / "request.json"
    if path.stat().st_size > 65536:
        raise ValueError("Invalid staged request")
    request = json.loads(path.read_text(encoding="utf-8"))
    account_module().request_identity(request)
    actual = volume_identity(boot)
    if (
        actual["capacity"] != request["target"]["capacity"]
        or str(actual["boot_uuid"]).upper() != str(request["target"]["boot_uuid"]).upper()
    ):
        raise ValueError("The selected card does not match the staged migration")
    original = (package / "cmdline.before").read_bytes()
    if hashlib.sha256(original).hexdigest() != request["target"]["cmdline_sha256"]:
        raise ValueError("The saved boot command line is corrupt; use the retained local package")
    current = (boot / "cmdline.txt").read_bytes()
    if current not in (original, base64.b64decode(request["staged_cmdline"], validate=True)):
        raise ValueError("Boot arguments changed; review before restoring the retained original")
    staged = boot / BOOTSTRAP
    retained = None
    if staged.exists():
        if staged.is_symlink():
            raise ValueError("The staged payload directory must not be a symbolic link")
        on_card = staged / "request.json"
        if on_card.exists():
            other = json.loads(on_card.read_text(encoding="utf-8"))
            if other.get("id") != request["id"]:
                raise ValueError("A different migration is staged; its files were left untouched")
    account_module().atomic_write(boot / "cmdline.txt", original, 0o644)
    if staged.exists():
        retained = boot / ("kiosk-admin-undone-" + request["id"] + "-" + uuid.uuid4().hex[:8])
        staged.rename(retained)
    return {
        "boot_restored": True,
        "account_unchanged": True,
        "retained_payload": str(retained) if retained else None,
        "message": "Normal boot restored. This does not revoke installed credentials or restore the whole card.",
    }


def system_request(run, ssh, host, action, value=None, payload=None):
    arguments = [*ssh(host), "sudo", "-n", "/usr/local/sbin/carvera-system-update", action]
    if value:
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise ValueError("Invalid system job identity")
        arguments.append(value)
    result = run(arguments, input=json.dumps(payload) if payload is not None else None, text=True, capture_output=True)
    return json.loads(result.stdout)


def system_operation(
    run,
    ssh,
    scp,
    host,
    action,
    bundle=None,
    *,
    inspect=False,
    recovery=False,
    confirmed=False,
    allow_screen_interruption=False,
):
    payload = {
        "action": action,
        "options": {
            "recovery": recovery,
            "confirmed": confirmed,
            "allow_screen_interruption": allow_screen_interruption,
        },
    }
    if bundle:
        bundle = Path(bundle).resolve(strict=True)
        name = "system-" + uuid.uuid4().hex + ".tar.gz"
        run([*scp(host), bundle, host + ":/home/kiosk-admin/transfers/uploads/" + name])
        payload.update(name=name, sha256=sha256(bundle))
    try:
        if inspect:
            return system_request(run, ssh, host, "inspect", payload=payload)
        job = system_request(run, ssh, host, "submit", payload=payload)
    finally:
        if bundle:
            run([*ssh(host), "rm", "--", "/home/kiosk-admin/transfers/uploads/" + name])
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        reply = system_request(run, ssh, host, "status", value=job["id"])
        result = reply.get("job", {})
        if result.get("phase") == "complete":
            return reply
        if result.get("phase") == "failed":
            raise RuntimeError(result.get("error", "System update failed"))
        time.sleep(2)
    raise RuntimeError("The system job is still running; inspect system-status before retrying")
