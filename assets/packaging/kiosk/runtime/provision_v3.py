"""Journal the complete initial setup and reconcile completion without replaying access."""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import admin_accounts as accounts
import setup_protocol as protocol
from network import profile as wifi_profile
from settings import import_settings

ROOT = Path("/")
BOOT = Path("/boot/firmware")
STATE = Path("/var/lib/carvera-system")
RUNTIME = Path("/run/carvera-maint")


class StorageIncomplete(RuntimeError):
    pass


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30)


def read(path):
    return protocol.read_json(path) if path.exists() else {}


def fingerprints(path):
    result = []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] not in {
            "ssh-ed25519",
            "ssh-rsa",
            "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384",
            "ecdsa-sha2-nistp521",
        }:
            continue
        try:
            wire = base64.b64decode(fields[1], validate=True)
        except ValueError:
            continue
        result.append("SHA256:" + base64.b64encode(hashlib.sha256(wire).digest()).decode("ascii").rstrip("="))
    return list(dict.fromkeys(result))[:16]


def status():
    def public_read(path):
        try:
            return read(path)
        except (OSError, ValueError):
            return {}

    image = {
        key: value
        for key, value in public_read(BOOT / "carvera-image.json").items()
        if key in {"format", "version", "commit", "setup_protocol", "provisioning_format"}
    }
    complete = public_read(STATE / "setup-complete.json")
    journal = public_read(STATE / "setup-pending.json")
    phase = (
        "complete" if complete and completion_ready() else "unknown" if complete else "applying" if journal else "fresh"
    )
    if any(
        path.exists() and not public_read(path)
        for path in (STATE / "setup-complete.json", STATE / "setup-pending.json")
    ):
        phase = "unknown"
    value = {
        "protocol": 1,
        "phase": phase,
        "id": (complete or journal).get("id"),
        "image": image,
        "components": {},
        "key_fingerprints": {},
        "cleanup_pending": any((BOOT / name).exists() for name in (protocol.REQUEST, protocol.SETTINGS)),
    }
    for name, path in {
        "controller": "opt/carvera/current/bundle.json",
        "system": "opt/carvera/system-current/system-bundle.json",
        "updater": "opt/carvera/updater/updater-bundle.json",
    }.items():
        metadata = public_read(ROOT / path)
        value["components"][name] = {"version": metadata.get("version"), "commit": metadata.get("commit")}
    for role, home in (("maintenance", "home/carvera-admin"), ("administrator", "home/kiosk-admin")):
        value["key_fingerprints"][role] = fingerprints(ROOT / home / ".ssh/authorized_keys")
    value["host_fingerprints"] = fingerprints(ROOT / "etc/ssh/ssh_host_ed25519_key.pub")
    if (ROOT / "var/lib/carvera").exists():
        space = shutil.disk_usage(ROOT / "var/lib/carvera")
        value["storage"] = {"total": space.total, "free": space.free}
    error = public_read(STATE / "setup-error.json").get("error")
    if error in {"configuration", "interrupted", "system", "storage"}:
        value["error"] = error
    return value


def publish_status():
    RUNTIME.mkdir(mode=0o755, parents=True, exist_ok=True)
    value = status()
    accounts.atomic_write(RUNTIME / "setup-status.json", json.dumps(value), 0o644)
    try:
        protocol.write_json(BOOT / "carvera-setup-diagnostic.json", value)
    except OSError:
        pass
    return value


def completion_ready():
    try:
        image = read(BOOT / "carvera-image.json")
        if image.get("format") == protocol.IMAGE_FORMAT:
            complete = read(STATE / "setup-complete.json")
            return bool(
                complete.get("protocol") == 1
                and re.fullmatch("[a-f0-9]{32}", str(complete.get("id", "")))
                and re.fullmatch("[a-f0-9]{64}", str(complete.get("digest", "")))
                and complete.get("image") == image
                and read(STATE / "root-grow.json").get("phase") == "complete"
            )
        if image.get("format") == "carvera-kiosk-pi4-v2":
            return bool(read(STATE / "access-complete.json"))
        return image.get("format") == "carvera-kiosk-pi4"
    except (OSError, ValueError):
        return False


def finalize(complete):
    """Root completion is authoritative; finalization must never reinstall keys."""
    operation = complete["id"]
    protocol.write_json(BOOT / protocol.RECEIPT, protocol.receipt("complete", operation))
    for name in (protocol.REQUEST, protocol.SETTINGS):
        path = BOOT / name
        if path.is_symlink():
            raise ValueError("Unexpected setup link")
        path.unlink(missing_ok=True)
    for name in ("setup-pending.json", "setup-settings.tar.gz", "setup-error.json"):
        (STATE / name).unlink(missing_ok=True)
    marker = ROOT / "var/lib/carvera/provisioned"
    marker.parent.mkdir(parents=True, exist_ok=True)
    accounts.atomic_write(marker, b"", 0o644)
    publish_status()


def hostname_step(value):
    accounts.atomic_write(ROOT / "etc/hostname", value["hostname"] + "\n", 0o644)
    hosts = ROOT / "etc/hosts"
    content = "\n".join(line for line in hosts.read_text().splitlines() if not line.startswith("127.0.1.1"))
    accounts.atomic_write(hosts, content + f"\n127.0.1.1 {value['hostname']}\n", 0o644)
    command("hostname", value["hostname"])


def maintenance_step(value):
    path = ROOT / "home/carvera-admin/.ssh"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("Unexpected maintenance SSH path")
    keys, _fingerprints = accounts.public_keys(value["authorized_keys"])
    accounts.atomic_write(path / "authorized_keys", "\n".join(keys) + "\n")
    os.chmod(path, 0o700)
    command("chown", "-R", "carvera-admin:carvera-admin", str(path))


def network_step(value):
    wifi = value.get("wifi")
    if wifi is None:
        return
    _, config = wifi_profile(wifi["ssid"], wifi["password"], autoconnect=True)
    import io

    output = io.StringIO()
    config.write(output, space_around_delimiters=False)
    accounts.atomic_write(ROOT / "etc/NetworkManager/system-connections/carvera-wifi.nmconnection", output.getvalue())
    accounts.atomic_write(
        ROOT / "etc/modprobe.d/cfg80211_regdomain.conf", f"options cfg80211 ieee80211_regdom={wifi['country']}\n", 0o644
    )
    command("iw", "reg", "set", wifi["country"])
    command("rfkill", "unblock", "wifi")


def settings_step(value):
    if value.get("settings_sha256") is not None:
        import_settings(STATE / "setup-settings.tar.gz", ROOT / "var/lib/carvera")
        command("chown", "-R", "carvera:carvera", str(ROOT / "var/lib/carvera"))


def run():
    if os.geteuid() != 0:
        raise ValueError("Initial setup requires the system provisioning service")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    image = read(BOOT / "carvera-image.json")
    if image.get("format") != protocol.IMAGE_FORMAT or image.get("setup_protocol") != 1:
        raise ValueError("Use a supported v3 image")
    complete = read(STATE / "setup-complete.json")
    if (STATE / "setup-complete.json").exists() and not complete:
        raise ValueError("The root setup completion record is invalid")
    if complete:
        if not completion_ready():
            raise ValueError("The root completion record does not match this image")
        finalize(complete)
        return
    journal_path = STATE / "setup-pending.json"
    journal = read(journal_path)
    try:
        if journal_path.exists() and not journal:
            raise ValueError("The authoritative setup journal is invalid")
        if read(STATE / "root-grow.json").get("phase") != "complete":
            raise StorageIncomplete("Kiosk storage setup must finish before provisioning")
        value = read(BOOT / protocol.REQUEST)
        protocol.validate_request(value, accounts.public_keys)
        operation, digest = protocol.identity(value)
        receipt = read(BOOT / protocol.RECEIPT)
        if (
            receipt.get("protocol") != 1
            or receipt.get("id") != operation
            or receipt.get("phase") not in {"prepared", "applying"}
        ):
            raise ValueError("The configuration was not committed by matching setup tools")
        if not journal and (receipt["phase"] == "applying" or (STATE / "access-complete.json").exists()):
            raise ValueError("The authoritative setup journal is missing; recover the matching transaction or reflash")
        if journal and (journal.get("id"), journal.get("digest")) != (operation, digest):
            raise ValueError("Only the original setup transaction can resume")
        expected = value.get("settings_sha256")
        if expected is not None:
            source = STATE / "setup-settings.tar.gz" if journal else BOOT / protocol.SETTINGS
            if source.is_symlink() or not source.is_file() or source.stat().st_size > protocol.MAX_SETTINGS:
                raise ValueError("The setup preferences are missing")
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("The setup preferences changed")
            if not journal:
                accounts.atomic_write(STATE / "setup-settings.tar.gz", data)
        elif (BOOT / protocol.SETTINGS).exists():
            raise ValueError("Unexpected setup preferences")
        if not journal:
            journal = {"id": operation, "digest": digest, "done": [], "request": value}
            accounts.write_json(journal_path, journal)
        protocol.write_json(BOOT / protocol.RECEIPT, protocol.receipt("applying", operation))
        (STATE / "setup-error.json").unlink(missing_ok=True)
        publish_status()
        for name, function in (
            ("hostkeys", lambda _value: command("ssh-keygen", "-A")),
            ("hostname", hostname_step),
            ("maintenance", maintenance_step),
            ("network", network_step),
            ("settings", settings_step),
            ("administrator", accounts.install),
        ):
            if name not in journal["done"]:
                function(value)
                journal["done"].append(name)
                accounts.write_json(journal_path, journal)
        result = {"protocol": 1, "id": operation, "digest": digest, "image": image}
        accounts.write_json(STATE / "setup-complete.json", result)
        finalize(result)
    except Exception as failure:
        error = "storage" if isinstance(failure, StorageIncomplete) else "interrupted" if journal else "configuration"
        accounts.write_json(STATE / "setup-error.json", {"error": error})
        try:
            current = read(BOOT / protocol.RECEIPT)
            phase = "applying" if journal else current.get("phase")
            operation = journal.get("id") if journal else current.get("id")
            if current.get("protocol") == 1 and phase in {"fresh", "prepared", "applying", "complete"}:
                protocol.write_json(BOOT / protocol.RECEIPT, protocol.receipt(phase, operation, error))
        finally:
            publish_status()
        raise


def main():
    try:
        run()
    except Exception:
        # Public diagnostics contain a fixed error code, never configuration values.
        raise SystemExit("Initial setup is incomplete; see the touchscreen setup status") from None


if __name__ == "__main__":
    main()
