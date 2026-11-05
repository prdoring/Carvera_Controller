"""Restricted system settings operations for the independent kiosk interface."""

import hashlib
import json
import math
import os
import re
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import time
import uuid
from pathlib import Path

import control

READ_ACTIONS = {"status", "scan", "files", "inspect", "diagnose", "logs", "backup", "display-modes", "open"}
CHANGE_ACTIONS = {
    "wifi",
    "wifi-confirm",
    "wifi-revert",
    "display",
    "display-confirm",
    "display-revert",
    "restart",
    "reboot",
    "shutdown",
    "update",
    "rollback",
    "restore",
    "leave",
}
FILE_LIMIT = 512 * 1024 * 1024


def validate(request):
    if not isinstance(request, dict) or set(request) - {"action", "value", "wifi", "confirmed_idle", "id"}:
        raise ValueError("Invalid system request")
    action = request.get("action")
    if not isinstance(action, str) or action not in READ_ACTIONS | CHANGE_ACTIONS:
        raise ValueError("Unknown system action")
    if action in CHANGE_ACTIONS and action != "leave" and request.get("confirmed_idle") is not True:
        raise ValueError("Confirm that the machine is idle before making changes")
    if not isinstance(request.get("id"), str) or not re.fullmatch(r"[a-f0-9]{32}", request["id"]):
        raise ValueError("Invalid operation identity")
    return action


def open_system():
    control.command("systemctl", "--no-block", "start", "carvera-recovery.service")
    return {"opened": True}


def remember(value):
    if value.get("phase") in {"queued", "running"}:
        value["process_start"] = process_start(value.get("pid"))
    control.write_json(control.RUN / "system-operation.json", value)


def process_start(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def operation_status():
    value = control.read_json(control.RUN / "system-operation.json")
    if value.get("phase") in {"queued", "running"}:
        try:
            pid = value.get("pid")
            if not isinstance(pid, int) or pid <= 0:
                raise ProcessLookupError()
            os.kill(pid, 0)
            if value.get("process_start") is not None and value["process_start"] != process_start(pid):
                raise ProcessLookupError()
        except (OSError, TypeError):
            value.update(
                phase="interrupted", message="The operation was interrupted. Refresh system details before retrying."
            )
    return value


def pending(name):
    value = control.read_json(control.RUN / (name + "-checkpoint.json"))
    if value:
        value = {key: value[key] for key in ("expires", "mode", "previous") if key in value}
        value["remaining"] = max(0, math.ceil(value.get("expires", 0) - time.monotonic()))
    return value


def status():
    controller = control.read_json(control.STATUS)
    fresh = bool(controller) and 0 <= time.monotonic() - controller.get("updated", 0) <= 3
    image = control.read_json(Path("/boot/firmware/carvera-image.json"))
    current = control.read_json(control.BASE / "current/bundle.json")
    previous = control.read_json(control.BASE / "previous/bundle.json")
    lease = control.read_json(control.RUN / "maintenance.json")
    details = {
        "system": control.read_json(control.BASE / "system-current/system-bundle.json"),
        "updater": control.read_json(control.BASE / "updater/updater-bundle.json"),
        "maintenance_protocol": 1,
        "controller": controller if fresh else {},
        "image_version": image.get("version"),
        "version": current.get("version"),
        "previous_version": previous.get("version"),
        "maintenance_owner": lease.get("owner"),
        "maintenance": bool(lease),
        "network": pending("network"),
        "display": pending("display"),
        "operation": operation_status(),
    }
    for name, path in (
        ("display_mode", "/etc/carvera/display-mode"),
        ("temperature", "/sys/class/thermal/thermal_zone0/temp"),
    ):
        try:
            details[name] = Path(path).read_text().strip()
        except OSError:
            details[name] = None
    try:
        details["temperature"] = f"{int(details['temperature']) / 1000:.1f} °C"
    except (ValueError, TypeError):
        details["temperature"] = "—"
    usage = shutil.disk_usage(control.DATA)
    details["storage"] = f"{usage.free / (1024**3):.1f} GiB free / {usage.total / (1024**3):.1f} GiB"
    try:
        memory = {
            line.split(":")[0]: int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if len(line.split()) >= 2
        }
        details["memory"] = f"{memory['MemAvailable'] // 1024} MiB available / {memory['MemTotal'] // 1024} MiB"
    except (OSError, ValueError, KeyError):
        details["memory"] = "—"
    details["login"] = "carvera-admin@" + socket.gethostname() + ".local"
    for name, arguments in (
        ("addresses", ("hostname", "-I")),
        ("identity", ("ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub")),
        ("connections", ("nmcli", "--terse", "--fields", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")),
    ):
        try:
            details[name] = subprocess.run(
                arguments, capture_output=True, text=True, check=False, timeout=3
            ).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            details[name] = ""
    details["interfaces"] = []
    for line in details.pop("connections", "").splitlines():
        fields = split_nmcli(line)
        if len(fields) == 4 and fields[1] in {"wifi", "ethernet"}:
            details["interfaces"].append(
                {"device": fields[0], "type": fields[1], "state": fields[2], "connection": fields[3]}
            )
    return details


def maintenance():
    lease = control.read_json(control.RUN / "maintenance.json")
    if lease and lease.get("owner") != "system":
        raise ValueError("Maintenance is controlled from the laptop. Finish it there before making changes here.")
    if lease and time.monotonic() - lease.get("entered", 0) > 1800:
        finish()
        lease = {}
    if not lease:
        control.enter(confirmed=True)
        lease = control.read_json(control.RUN / "maintenance.json")
        lease["owner"] = "system"
        control.write_json(control.RUN / "maintenance.json", lease)
    control.require_maintenance()


def finish():
    lease = control.read_json(control.RUN / "maintenance.json")
    if lease and lease.get("owner") != "system":
        raise ValueError("Maintenance is controlled from the laptop. Finish it there.")
    if pending("display").get("remaining", 0):
        raise ValueError("Keep or revert the display preview before returning to the controller")
    control.leave()


def controller_available():
    value = control.read_json(control.STATUS)
    if not value.get("pid") or not 0 <= time.monotonic() - value.get("updated", 0) <= 3:
        return False
    try:
        os.kill(value["pid"], 0)
    except OSError:
        return False
    return True


def display_command(mode):
    return control.command(
        "runuser",
        "-u",
        "carvera",
        "--",
        "env",
        "XDG_RUNTIME_DIR=/run/carvera",
        "WAYLAND_DISPLAY=wayland-0",
        "python3",
        str(control.BASE / "maintenance/display.py"),
        mode,
        timeout=10,
    )


def display_trial(mode):
    if mode not in ("1920x1200", "1920x1080"):
        raise ValueError("Choose 1920×1200 or 1920×1080")
    if pending("display"):
        raise ValueError("Finish the current display preview first")
    path = Path("/etc/carvera/display-mode")
    previous = path.read_text().strip()
    if previous not in ("1920x1200", "1920x1080"):
        raise ValueError("The saved display mode is invalid")
    token = uuid.uuid4().hex
    control.write_json(
        control.RUN / "display-checkpoint.json",
        {"mode": mode, "previous": previous, "token": token, "expires": time.monotonic() + 20},
    )
    try:
        control.command(
            "systemd-run",
            "--quiet",
            "--unit=carvera-display-" + token,
            "--on-active=20s",
            "--property=Restart=on-failure",
            "--property=RestartSec=1s",
            "--property=StartLimitIntervalSec=0",
            "/usr/bin/python3",
            str(control.BASE / "maintenance/recovery_control.py"),
            "--revert-display",
            token,
        )
        display_command(mode)
    except Exception:
        revert_display(token)
        raise
    return {"preview": mode}


def revert_display(token=None):
    path = control.RUN / "display-checkpoint.json"
    checkpoint = control.read_json(path)
    if checkpoint and (token is None or checkpoint.get("token") == token):
        display_command(checkpoint["previous"])
        path.unlink(missing_ok=True)
    return {"reverted": True}


def confirm_display():
    checkpoint = control.read_json(control.RUN / "display-checkpoint.json")
    if not checkpoint or checkpoint.get("expires", 0) <= time.monotonic():
        revert_display()
        raise ValueError("The display preview expired and was reverted")
    Path("/etc/carvera/display-mode").write_text(checkpoint["mode"] + "\n")
    (control.RUN / "display-checkpoint.json").unlink()
    return {"display": checkpoint["mode"]}


def revert_network():
    checkpoint = control.read_json(control.RUN / "network-checkpoint.json")
    if checkpoint and checkpoint.get("expires", 0) > time.monotonic():
        control.command(
            "gdbus",
            "call",
            "--system",
            "--dest",
            "org.freedesktop.NetworkManager",
            "--object-path",
            "/org/freedesktop/NetworkManager",
            "--method",
            "org.freedesktop.NetworkManager.CheckpointRollback",
            checkpoint["path"],
        )
        control.command(
            "gdbus",
            "call",
            "--system",
            "--dest",
            "org.freedesktop.NetworkManager",
            "--object-path",
            "/org/freedesktop/NetworkManager",
            "--method",
            "org.freedesktop.NetworkManager.CheckpointDestroy",
            checkpoint["path"],
            check=False,
        )
    (control.RUN / "network-checkpoint.json").unlink(missing_ok=True)
    return {"reverted": True}


def split_nmcli(line):
    parts, word, escaped = [], "", False
    for char in line:
        if escaped:
            word += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            parts.append(word)
            word = ""
        else:
            word += char
    return parts + [word]


def scan():
    result = control.command(
        "nmcli",
        "--terse",
        "--escape",
        "yes",
        "--fields",
        "SSID,SIGNAL,SECURITY,IN-USE",
        "device",
        "wifi",
        "list",
        "--rescan",
        "yes",
        timeout=20,
    )
    networks = {}
    for line in result.stdout.splitlines():
        parts = split_nmcli(line)
        if len(parts) != 4 or not parts[0]:
            continue
        ssid, signal, security, active = parts
        supported = any(token in {"WPA", "WPA1", "WPA2"} for token in security.split()) and not any(
            token in security for token in ("802.1X", "EAP")
        )
        entry = {
            "ssid": ssid,
            "signal": int(signal) if signal.isdecimal() else 0,
            "security": security or "Open",
            "active": active == "*",
            "supported": supported,
        }
        if ssid not in networks or networks[ssid]["signal"] < entry["signal"]:
            networks[ssid] = entry
    return {"networks": sorted(networks.values(), key=lambda value: (-value["signal"], value["ssid"]))}


def staged_path(name):
    return control.admin_path(name, "uploads")


def inspect_file(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_LIMIT:
            raise ValueError("Staged files must be regular files no larger than 512 MiB")
        digest, total = hashlib.sha256(), 0
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > FILE_LIMIT:
                raise ValueError("Staged file exceeds 512 MiB")
            digest.update(chunk)
        item = {"name": path.name, "bytes": total, "sha256": digest.hexdigest(), "kind": "preferences"}
        source.seek(0)
        expanded = 0
        with tarfile.open(fileobj=source, mode="r|*") as archive:
            for index, header in enumerate(archive):
                if header.name in {"system-bundle.json", "updater-bundle.json"}:
                    raise ValueError("Use kiosk-admin system-update for a system bundle")
                expanded += header.size
                if index >= 4096 or expanded > FILE_LIMIT:
                    raise ValueError("Staged archive exceeds supported limits")
                if header.name == "bundle.json":
                    if not header.isfile() or header.size > 65536:
                        raise ValueError("Invalid bundle metadata")
                    manifest = json.load(archive.extractfile(header))
                    if not isinstance(manifest, dict):
                        raise ValueError("Invalid bundle metadata")
                    item.update(
                        kind="application",
                        version=manifest.get("version"),
                        architecture=manifest.get("architecture"),
                        python=manifest.get("python"),
                    )
                    break
        final = os.fstat(source.fileno())
        if (info.st_mtime_ns, info.st_ctime_ns, info.st_size) != (final.st_mtime_ns, final.st_ctime_ns, final.st_size):
            raise ValueError("The staged file changed. Refresh and review it again.")
        return item


def files():
    items = []
    directory = control.ADMIN / "uploads"
    candidates = []
    for path in directory.iterdir() if directory.exists() else ():
        try:
            if path.is_symlink() or not path.name.endswith(".tar.gz"):
                continue
            candidates.append((path.stat().st_mtime_ns, path))
        except OSError:
            continue
    for _modified, path in sorted(candidates, reverse=True)[:20]:
        try:
            staged_path(path.name)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_LIMIT:
                    continue
                item = {"name": path.name, "bytes": info.st_size, "kind": "preferences"}
                with tarfile.open(fileobj=source, mode="r|*") as archive:
                    first = archive.next()
                    if first and first.name == "system-bundle.json":
                        continue
                    if first and first.name == "bundle.json" and first.isfile() and first.size <= 65536:
                        manifest = json.load(archive.extractfile(first))
                        if not isinstance(manifest, dict):
                            continue
                        item.update(
                            kind="application",
                            version=manifest.get("version"),
                            architecture=manifest.get("architecture"),
                            python=manifest.get("python"),
                        )
                items.append(item)
        except (OSError, ValueError, tarfile.TarError, KeyError):
            continue
    return {"files": items, "limited": len(candidates) > 20}


def private_copy(value):
    if not isinstance(value, dict) or set(value) != {"name", "sha256"}:
        raise ValueError("Select a staged file and review its details first")
    source = staged_path(value["name"])
    directory = tempfile.TemporaryDirectory(prefix="system-", dir=control.ADMIN)
    try:
        target = Path(directory.name) / "selected.tar.gz"
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as incoming, target.open("wb") as output:
            info = os.fstat(incoming.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > FILE_LIMIT:
                raise ValueError("Invalid staged file")
            total = 0
            while chunk := incoming.read(1024 * 1024):
                total += len(chunk)
                if total > FILE_LIMIT:
                    raise ValueError("Staged file exceeds 512 MiB")
                output.write(chunk)
        with target.open("rb") as incoming:
            digest = hashlib.file_digest(incoming, "sha256").hexdigest()
        if digest != value["sha256"]:
            raise ValueError("The staged file changed. Refresh and review it again.")
        return directory, target
    except Exception:
        directory.cleanup()
        raise


def export(action):
    name = "carvera-" + action + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    suffix = ".tar.gz" if action == "backup" else ".json" if action == "diagnose" else ".txt"
    destination = control.admin_path(name + suffix, "exports")
    if action == "backup":
        control.backup(destination, owner="carvera-admin")
    else:
        value = (
            control.diagnostics()
            if action == "diagnose"
            else control.command(
                "journalctl", "--no-pager", "-n", "500", "-u", control.SERVICE, "-u", "carvera-recovery.service"
            ).stdout
        )
        with tempfile.TemporaryDirectory(prefix="export-", dir=control.ADMIN) as directory:
            temporary = Path(directory) / "report"
            temporary.write_text(json.dumps(value, indent=2) if action == "diagnose" else value, encoding="utf-8")
            os.chmod(temporary, 0o600)
            shutil.chown(temporary, user="carvera-admin", group="carvera-admin")
            os.replace(temporary, destination)
    return {"file": destination.name, "message": "File saved for laptop retrieval."}


def dispatch(request):
    action = validate(request)
    if action == "open":
        return open_system()
    if action == "status":
        return status()
    if action == "scan":
        return scan()
    if action == "display-modes":
        return json.loads(display_command("--list").stdout)
    if action == "files":
        return files()
    if action == "inspect":
        return inspect_file(staged_path(request.get("value")))
    if action in {"backup", "diagnose", "logs"}:
        return export(action)
    if action == "leave":
        finish()
        return {"maintenance": False, "controller_available": controller_available()}
    maintenance()
    if pending("network").get("remaining", 0) and action not in {"wifi-confirm", "wifi-revert"}:
        raise ValueError("Keep or revert the pending Wi-Fi change first")
    if pending("display") and action not in {"display-confirm", "display-revert"}:
        raise ValueError("Keep or revert the display preview first")
    if action == "wifi":
        result = control.network_apply(request.get("wifi", {}))
    elif action == "wifi-confirm":
        result = control.network_confirm()
    elif action == "wifi-revert":
        result = revert_network()
    elif action == "display":
        result = display_trial(request.get("value"))
    elif action == "display-confirm":
        result = confirm_display()
    elif action == "display-revert":
        result = revert_display()
    elif action in {"update", "restore"}:
        directory, selected = private_copy(request.get("value"))
        try:
            if action == "update":
                result = control.deploy_file(selected)
            else:
                result = control.restore_preferences(selected)
        finally:
            directory.cleanup()
    elif action == "rollback":
        result = control.rollback()
    elif action == "restart":
        lease = control.require_maintenance()
        control.command("systemctl", "restart", control.SERVICE)
        control.wait_ready(lease["token"])
        result = {"restarted": True}
    elif action in {"reboot", "shutdown"}:
        control.command("systemctl", "--no-block", "reboot" if action == "reboot" else "poweroff")
        return {"requested": action}
    else:
        raise ValueError("Unknown system action")
    if not pending("network").get("remaining", 0) and not pending("display"):
        finish()
    return result


def run(request, queued=False):
    action = validate(request)
    previous = control.read_json(control.RUN / "system-operation.json")
    if previous.get("id") == request["id"]:
        if previous.get("phase") == "complete":
            return previous["result"]
        if not (queued and previous.get("phase") == "queued"):
            raise ValueError("This request has already been attempted. Refresh system details before retrying.")
    elif operation_status().get("phase") in {"queued", "running"}:
        raise ValueError("Another system operation is in progress")
    record = {
        "id": request["id"],
        "action": action,
        "phase": "running",
        "pid": os.getpid(),
        "started": time.monotonic(),
    }
    remember(record)
    try:
        result = dispatch(request)
    except Exception as error:
        record.update(phase="failed", message=str(error)[:1000])
        remember(record)
        raise
    record.update(phase="complete", result=result)
    remember(record)
    return result
