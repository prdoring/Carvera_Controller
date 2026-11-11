"""Originating-user access keys and versioned, secret-free kiosk profiles."""

from __future__ import annotations

import csv
import json
import os
import re
import stat
import subprocess
import uuid
from pathlib import Path

from kioskdesktop.runtime import shared

ROLES = {"maintenance": "carvera-admin", "administrator": "kiosk-admin"}


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=False)
    if os.name == "nt":
        from kioskdesktop.devices import windows_system_directory

        system = windows_system_directory()
        result = subprocess.run(
            [str(system / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        fields = next(csv.reader(result.stdout.splitlines()))
        sid = fields[-1]
        if not re.fullmatch(r"S-1-\d+(?:-\d+)+", sid):
            raise RuntimeError("Could not identify the interactive Windows user")
        subprocess.run(
            [str(system / "icacls.exe"), str(path), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
            check=True,
            capture_output=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        os.chmod(path, 0o700)


def write_new(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def public_keys(values):
    import asyncssh

    return shared("admin_accounts").public_keys(
        values, verify=lambda record: asyncssh.import_public_key(record.encode("utf-8")).get_fingerprint("sha256")
    )


def unlock(path: Path, passphrase: str):
    import asyncssh

    if not passphrase:
        raise ValueError("Enter the key passphrase")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Select a regular encrypted OpenSSH private key")
    data = path.read_bytes()
    try:
        asyncssh.import_private_key(data)
    except asyncssh.KeyImportError:
        pass
    else:
        raise ValueError("Select an encrypted key; the original key was left unchanged")
    return asyncssh.import_private_key(data, passphrase=passphrase)


def validate(value):
    if not isinstance(value, dict) or value.get("format") != 1:
        raise ValueError("Unsupported kiosk profile")
    if not isinstance(value.get("id"), str) or not re.fullmatch("[a-f0-9]{32}", value["id"]):
        raise ValueError("Invalid kiosk profile identity")
    if not isinstance(value.get("hostname"), str) or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value["hostname"]
    ):
        raise ValueError("Invalid profile hostname")
    keys = value.get("keys")
    if not isinstance(keys, dict) or set(keys) != set(ROLES):
        raise ValueError("Both access roles are required")
    for role, key in keys.items():
        if not isinstance(key, dict) or set(key) != {"path", "public", "fingerprint", "account"}:
            raise ValueError("Invalid access-key profile")
        if key["account"] != ROLES[role] or not isinstance(key["path"], str) or not Path(key["path"]).is_absolute():
            raise ValueError("Invalid access-key role or path")
        _keys, fingerprints = public_keys([key["public"]])
        if fingerprints != [key["fingerprint"]]:
            raise ValueError("The key fingerprint does not match the profile")
    if len({key["fingerprint"] for key in keys.values()}) != len(ROLES):
        raise ValueError("Use a different encrypted key for each access role")
    host = value.get("host")
    if host is not None:
        if not isinstance(host, dict) or set(host) != {"address", "public", "fingerprint"}:
            raise ValueError("Invalid host identity")
        validate_host(host["address"])
        _keys, fingerprints = public_keys([host["public"]])
        if fingerprints != [host["fingerprint"]]:
            raise ValueError("The host fingerprint does not match its public key")
    allowed = {"format", "id", "hostname", "keys", "host", "release", "components", "commit", "stage"}
    if set(value) - allowed:
        raise ValueError("Unexpected profile data; passwords and session tokens are never saved")
    if "components" in value:
        from kioskdesktop.releases import version

        if not isinstance(value["components"], dict) or set(value["components"]) != {
            "image",
            "controller",
            "system",
            "updater",
        }:
            raise ValueError("Invalid profile component versions")
        for component in value["components"].values():
            version(component)
    if "commit" in value and not re.fullmatch("[a-f0-9]{40}", str(value["commit"])):
        raise ValueError("Invalid profile source revision")
    if value.get("stage") not in {"keys", "prepared", "verified"}:
        raise ValueError("Invalid profile setup stage")
    return value


def validate_host(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.:-]{0,252}", value):
        raise ValueError("Enter the kiosk hostname or IP address without a username")
    return value


def load(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
        raise ValueError("Invalid profile file")
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError("The profile must belong to you and be private")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def saved(directory=None):
    """List this desktop user's valid local setup profiles."""
    folder = Path(directory or Path.home() / ".ssh/carvera")
    result = []
    for path in folder.glob("*/profile.json"):
        if path.parent.is_symlink() or path.is_symlink():
            continue
        try:
            result.append((path, load(path)))
        except (OSError, ValueError, KeyError):
            continue
    return sorted(result, key=lambda item: (item[1]["hostname"], str(item[0])))


def save(path: Path, value):
    validate(value)
    shared("setup_protocol").write_json(path, value)


def create(hostname: str, passphrase: str, confirmation: str, *, directory=None, existing=None):
    import asyncssh

    if directory is None:
        from kioskdesktop.elevation import elevated

        if elevated():
            raise PermissionError("Create access keys from your normal desktop account")

    generated = any(not existing or role not in existing for role in ROLES)
    if generated and (not passphrase or passphrase != confirmation):
        raise ValueError("Enter and confirm a nonempty passphrase")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise ValueError("Use a valid lowercase kiosk name")
    operation = uuid.uuid4().hex
    folder = Path(directory or Path.home() / ".ssh/carvera") / operation
    private_directory(folder)
    value = {"format": 1, "id": operation, "hostname": hostname, "keys": {}, "stage": "keys"}
    # Retain an incomplete local identity after failure rather than overwriting keys.
    write_new(folder / "identity.json", json.dumps({"id": operation, "hostname": hostname}).encode("utf-8"))
    for role in ROLES:
        record = existing.get(role) if existing else None
        selected_path = record.get("path") if isinstance(record, dict) else record
        selected = Path(selected_path).expanduser().resolve(strict=True) if selected_path else None
        if selected is not None:
            key = unlock(selected, record.get("passphrase", "") if isinstance(record, dict) else passphrase)
            target = selected
        else:
            key = asyncssh.generate_private_key("ssh-ed25519")
            target = folder / ("id_ed25519_" + role)
            write_new(target, key.export_private_key("openssh", passphrase=passphrase))
            write_new(target.with_suffix(".pub"), key.export_public_key("openssh"))
        value["keys"][role] = {
            "account": ROLES[role],
            "path": str(target),
            "public": key.export_public_key("openssh").decode("utf-8").strip(),
            "fingerprint": key.get_fingerprint("sha256"),
        }
    profile = folder / "profile.json"
    save(profile, value)
    return profile, value


def connection_details(value):
    validate(value)
    host = value.get("host", {})
    return {
        "hostname": value["hostname"],
        "address": host.get("address", value["hostname"] + ".local"),
        "host_fingerprint": host.get("fingerprint"),
        "accounts": {
            role: {"username": key["account"], "key_path": key["path"], "fingerprint": key["fingerprint"]}
            for role, key in value["keys"].items()
        },
    }
