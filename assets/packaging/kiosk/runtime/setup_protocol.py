"""Bounded, dependency-free card preparation shared by desktop and Pi tools."""

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

IMAGE_FORMAT = "carvera-kiosk-pi4-v3"
PROTOCOL = 1
REQUEST = "carvera-provision.json"
RECEIPT = "carvera-setup.json"
SETTINGS = "carvera-settings.tar.gz"
MAX_REQUEST = 65536
MAX_SETTINGS = 32 * 1024 * 1024


def read_json(path):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_REQUEST:
        raise ValueError("Invalid setup document")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a setup object")
    return value


def atomic_write(path, data, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Setup paths must not be links")
    descriptor, temporary = tempfile.mkstemp(prefix=".carvera-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            if os.name != "nt":
                os.fchmod(stream.fileno(), mode)
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=True).encode("utf-8")
    if len(data) > MAX_REQUEST:
        raise ValueError("Setup document is too large")
    atomic_write(path, data)


def identity(value):
    data = json.dumps(value, sort_keys=True).encode("utf-8")
    operation = value.get("id")
    if len(data) > MAX_REQUEST or not isinstance(operation, str) or not re.fullmatch("[a-f0-9]{32}", operation):
        raise ValueError("Invalid setup identity")
    return operation, hashlib.sha256(data).hexdigest()


def validate_request(value, key_validator):
    identity(value)
    allowed = {
        "format",
        "setup_protocol",
        "id",
        "hostname",
        "authorized_keys",
        "admin_public_keys",
        "wifi",
        "settings_sha256",
    }
    if set(value) - allowed or value.get("format") != 2 or value.get("setup_protocol") != PROTOCOL:
        raise ValueError("Use matching v3 setup tools")
    hostname = value.get("hostname")
    if not isinstance(hostname, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise ValueError("Use a valid lowercase kiosk hostname")
    key_validator(value.get("authorized_keys"))
    key_validator(value.get("admin_public_keys"))
    wifi = value.get("wifi")
    if wifi is not None:
        if not isinstance(wifi, dict) or set(wifi) != {"ssid", "password", "country"}:
            raise ValueError("Invalid Wi-Fi configuration")
        if any(not isinstance(wifi[key], str) or any(c in wifi[key] for c in "\r\n\0") for key in wifi):
            raise ValueError("Invalid Wi-Fi configuration")
        if (
            not 1 <= len(wifi["ssid"].encode("utf-8")) <= 32
            or not 8 <= len(wifi["password"].encode("utf-8")) <= 63
            or not re.fullmatch("[A-Z]{2}", wifi["country"])
        ):
            raise ValueError("Use a WPA-personal network and a two-letter country code")
    digest = value.get("settings_sha256")
    if digest is not None and (not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest)):
        raise ValueError("Invalid preferences identity")
    return value


def receipt(phase, operation=None, error=None):
    if phase not in {"fresh", "prepared", "applying", "complete"}:
        raise ValueError("Unknown setup phase")
    value = {"protocol": PROTOCOL, "phase": phase}
    if operation is not None:
        if not re.fullmatch("[a-f0-9]{32}", operation):
            raise ValueError("Invalid setup identity")
        value["id"] = operation
    if error is not None:
        if error not in {"configuration", "interrupted", "system", "storage"}:
            raise ValueError("Invalid public setup error")
        value["error"] = error
    return value


def prepare(boot, value, key_validator, settings=None):
    """Commit only fresh or identical prepared transactions; never reset access."""
    boot = Path(boot)
    image = read_json(boot / "carvera-image.json")
    if image.get("format") != IMAGE_FORMAT or image.get("setup_protocol") != PROTOCOL:
        raise ValueError("Select a matching v3 kiosk image")
    validate_request(value, key_validator)
    operation, digest = identity(value)
    current = read_json(boot / RECEIPT)
    if current.get("protocol") != PROTOCOL or current.get("phase") not in {"fresh", "prepared"}:
        raise ValueError("This card cannot accept a new configuration; resume setup or explicitly reflash")
    if current.get("phase") == "prepared" and current.get("id") != operation:
        raise ValueError("Resume the original setup profile; do not replace its keys")
    existing = boot / REQUEST
    if existing.exists() and identity(read_json(existing)) != (operation, digest):
        raise ValueError("A different setup request is already present")
    expected = value.get("settings_sha256")
    if settings is not None:
        if len(settings) > MAX_SETTINGS or hashlib.sha256(settings).hexdigest() != expected:
            raise ValueError("Preferences do not match the setup request")
        atomic_write(boot / SETTINGS, settings)
    elif expected is not None:
        path = boot / SETTINGS
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_SETTINGS:
            raise ValueError("The original preferences payload is missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("The preferences payload changed")
    elif (boot / SETTINGS).exists():
        raise ValueError("Unexpected preferences on the selected card")
    write_json(existing, value)
    write_json(boot / RECEIPT, receipt("prepared", operation))
    if read_json(existing) != value or read_json(boot / RECEIPT) != receipt("prepared", operation):
        raise OSError("Configuration read-back failed")
    return {"id": operation, "phase": "prepared"}
