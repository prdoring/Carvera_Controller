#!/usr/bin/python3
"""Local kiosk administration. This program never opens a machine connection."""

import configparser
import contextlib
import fcntl
import hashlib
import json
import os
import pwd
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

from kiosk_state import maintenance_ack, read_json, write_json
from network import profile as wifi_profile

BASE = Path("/opt/carvera")
DATA = Path("/var/lib/carvera")
RUN = Path("/run/carvera-maint")
STATUS = Path("/run/carvera/status.json")
SERVICE = "carvera-controller.service"
ADMIN = Path("/var/lib/carvera-maint")


@contextlib.contextmanager
def locked():
    RUN.mkdir(mode=0o755, parents=True, exist_ok=True)
    with (RUN / "control.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Another maintenance operation is in progress") from error
        yield


def admin_path(name, directory):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name):
        raise ValueError("Specify a plain file name")
    target = ADMIN / directory / name
    if ADMIN.is_symlink() or target.parent.is_symlink() or target.is_symlink():
        raise ValueError("Symbolic links are not accepted")
    return target


def command(*args, check=True):
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=300)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed")
    return result


def active(service=SERVICE):
    result = command("systemctl", "is-active", service, check=False)
    if result.returncode not in (0, 3):
        raise RuntimeError("Could not determine controller service state")
    return result.returncode == 0


def enter(confirmed=False):
    RUN.mkdir(parents=True, exist_ok=True)
    status = read_json(STATUS)
    if status and time.monotonic() - status.get("updated", 0) <= 3 and status.get("busy"):
        raise ValueError("The machine or controller is busy; maintenance is blocked")
    if (RUN / "maintenance.request").exists():
        raise ValueError("A maintenance session already exists; leave it before starting another")
    request = {"token": secrets.token_hex(16), "confirmed_idle": confirmed}
    if not active():
        if not confirmed:
            raise ValueError("Confirm the machine is idle before maintenance with the controller stopped")
        request["recovery"] = True
    write_json(RUN / "maintenance.request", request)
    os.chmod(RUN / "maintenance.request", 0o644)
    if not request.get("recovery"):
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                status = read_json(STATUS)
                try:
                    maintenance_ack(status, request["token"])
                    break
                except ValueError:
                    time.sleep(0.2)
            else:
                raise ValueError(status.get("error", "The controller did not acknowledge maintenance"))
        except Exception:
            status = read_json(STATUS)
            if not confirmed or (status and time.monotonic() - status.get("updated", 0) <= 3):
                (RUN / "maintenance.request").unlink(missing_ok=True)
                raise
            command("systemctl", "stop", SERVICE)
            request["recovery"] = True
            write_json(RUN / "maintenance.request", request)
            os.chmod(RUN / "maintenance.request", 0o644)
    write_json(RUN / "maintenance.json", {"token": request["token"], "entered": time.monotonic()})
    return {"maintenance": True}


def require_maintenance():
    lease = read_json(RUN / "maintenance.json")
    request = read_json(RUN / "maintenance.request")
    if not lease or lease.get("token") != request.get("token"):
        raise ValueError("Enter maintenance before making changes")
    if time.monotonic() - lease.get("entered", 0) > 1800:
        raise ValueError("Maintenance expired; leave and enter again")
    if active():
        maintenance_ack(read_json(STATUS), lease["token"])
    return lease


def leave():
    checkpoint = read_json(RUN / "network-checkpoint.json")
    if checkpoint and time.monotonic() < checkpoint.get("expires", 0):
        raise ValueError("Confirm the new Wi-Fi network or wait for its 120-second rollback before leaving maintenance")
    (RUN / "network-checkpoint.json").unlink(missing_ok=True)
    (RUN / "maintenance.request").unlink(missing_ok=True)
    (RUN / "maintenance.json").unlink(missing_ok=True)
    return {"maintenance": False}


def export_snapshot(destination):
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        result = subprocess.run([
            "runuser", "-u", "carvera", "--", "python3", str(BASE / "maintenance/settings.py"), "backup", str(DATA),
        ], stdout=output, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "Settings backup failed")


def backup(destination, owner=None):
    destination = Path(destination)
    temporary = RUN / ("settings-" + secrets.token_hex(8) + ".tar.gz")
    try:
        export_snapshot(temporary)
        os.chmod(temporary, 0o600)
        if owner is not None:
            account = pwd.getpwnam(owner)
            os.chown(temporary, account.pw_uid, account.pw_gid)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)


def unpack_bundle(bundle, destination):
    destination = Path(destination)
    archive = tarfile.open(fileobj=bundle, mode="r:*") if hasattr(bundle, "read") else tarfile.open(bundle, "r:*")
    with archive:
        members = archive.getmembers()
        names = set()
        total = 0
        for member in members:
            path = Path(member.name)
            allowed = member.name == "bundle.json" or (
                path.parent.as_posix() == "wheels" and path.suffix == ".whl"
            )
            if not member.isfile() or not allowed or member.name in names:
                raise ValueError(f"Invalid bundle member: {member.name}")
            names.add(member.name)
            total += member.size
            if total > 512 * 1024 * 1024:
                raise ValueError("Bundle exceeds 512 MiB")
        manifest = json.load(archive.extractfile("bundle.json"))
        if manifest.get("architecture") != "aarch64" or manifest.get("python") != "3.13":
            raise ValueError("This image requires an aarch64 Python 3.13 application bundle")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", manifest["version"]):
            raise ValueError("Invalid application version")
        if set(manifest["sha256"]) != names - {"bundle.json"}:
            raise ValueError("Bundle manifest does not match its files")
        destination.mkdir(parents=True, exist_ok=False)
        try:
            for member in members:
                content = archive.extractfile(member).read()
                expected = manifest["sha256"].get(member.name)
                if expected and hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError(f"Checksum mismatch: {member.name}")
                target = destination / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        except Exception:
            shutil.rmtree(destination)
            raise
    return manifest


def point_current(release):
    temporary = BASE / "current.next"
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release, target_is_directory=True)
    temporary.replace(BASE / "current")


def wait_ready(token):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        status = read_json(STATUS)
        try:
            maintenance_ack(status, token)
            return
        except ValueError:
            if not active():
                break
            time.sleep(0.5)
    raise RuntimeError("Controller startup did not reach a healthy maintenance state")


def restore_snapshot(snapshot):
    result = subprocess.run([
        "runuser", "-u", "carvera", "--", "python3", str(BASE / "maintenance/settings.py"), "restore", str(DATA),
    ], input=Path(snapshot).read_bytes(), capture_output=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "Settings restore failed")


def activate(release, restore=None):
    lease = require_maintenance()
    previous = (BASE / "current").resolve()
    snapshot = RUN / "before-activation.tar.gz"
    backup(snapshot)
    command("systemctl", "stop", SERVICE)
    try:
        if restore is not None:
            restore_snapshot(restore)
        request = read_json(RUN / "maintenance.request")
        request["confirmed_idle"] = True
        write_json(RUN / "maintenance.request", request)
        os.chmod(RUN / "maintenance.request", 0o644)
        STATUS.unlink(missing_ok=True)
        point_current(release)
        command("systemctl", "stop", "carvera-recovery.service")
        command("systemctl", "start", SERVICE)
        wait_ready(lease["token"])
    except Exception:
        command("systemctl", "stop", SERVICE, check=False)
        point_current(previous)
        restore_snapshot(snapshot)
        command("systemctl", "stop", "carvera-recovery.service", check=False)
        command("systemctl", "start", SERVICE, check=False)
        raise
    previous_link = BASE / "previous"
    previous_link.unlink(missing_ok=True)
    previous_link.symlink_to(previous, target_is_directory=True)
    shutil.copy2(snapshot, BASE / "previous-settings.tar.gz")
    prune_releases()
    return {"current": str(release), "previous": str(previous)}


def prune_releases():
    directory = BASE / "releases"
    keep = {(BASE / name).resolve() for name in ("current", "previous")}
    for path in directory.iterdir() if directory.exists() else ():
        if path.is_symlink() or not path.is_dir() or path.resolve() in keep:
            continue
        manifest = read_json(path / "bundle.json")
        if manifest.get("version") == path.name or re.fullmatch(r"staging-[0-9a-f]{12}", path.name):
            shutil.rmtree(path)


def deploy(bundle):
    require_maintenance()
    prune_releases()
    bundle = admin_path(bundle, "uploads")
    staging = BASE / "releases" / ("staging-" + secrets.token_hex(6))
    descriptor = os.open(bundle, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as incoming:
        if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
            raise ValueError("Upload a regular application bundle file")
        manifest = unpack_bundle(incoming, staging)
    release = BASE / "releases" / manifest["version"]
    if release.exists():
        shutil.rmtree(staging)
        raise ValueError("This version already exists; build a new version")
    try:
        command("chown", "-R", "carvera:carvera", str(staging))
        command("runuser", "-u", "carvera", "--", "python3", "-m", "venv", str(staging / "venv"))
        command("runuser", "-u", "carvera", "--", str(staging / "venv/bin/python"), "-m", "pip",
                "install", "--no-index", "--find-links",
                str(staging / "wheels"), "carvera-controller-community==" + manifest["version"])
        command("chown", "-R", "root:root", str(staging))
        command("chmod", "-R", "go-w", str(staging))
        staging.rename(release)
        # venv scripts contain absolute paths; activation uses its Python executable.
        return activate(release)
    except Exception:
        if release.exists() and (BASE / "current").resolve() != release.resolve():
            shutil.rmtree(release)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def rollback():
    require_maintenance()
    previous = BASE / "previous"
    if not previous.exists():
        raise ValueError("No previous application is available")
    snapshot = BASE / "previous-settings.tar.gz"
    return activate(previous.resolve(), restore=snapshot if snapshot.exists() else None)


def diagnostics():
    result = {"controller": read_json(STATUS), "maintenance": read_json(RUN / "maintenance.json")}
    for label, path in {
        "os": "/etc/os-release",
        "model": "/proc/device-tree/model",
        "temperature_millidegrees": "/sys/class/thermal/thermal_zone0/temp",
        "governor": "/sys/devices/system/cpu/cpufreq/policy0/scaling_governor",
        "clock_khz": "/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq",
        "cpu_pressure": "/proc/pressure/cpu", "memory_pressure": "/proc/pressure/memory",
        "io_pressure": "/proc/pressure/io",
        "memory": "/proc/meminfo",
        "boot_config": "/boot/firmware/config.txt",
        "display_mode": "/etc/carvera/display-mode",
    }.items():
        try:
            result[label] = Path(path).read_text().strip()
        except OSError:
            result[label] = None
    for label, args in {
        "addresses": ("hostname", "-I"), "storage": ("df", "-h", str(DATA)),
        "services": ("systemctl", "--no-pager", "--plain", "list-units", "--state=running", "--type=service"),
        "processes": ("ps", "-eo", "pid,comm,pcpu,pmem,rss", "--sort=-pcpu"),
    }.items():
        result[label] = command(*args, check=False).stdout.strip()
    if shutil.which("vcgencmd"):
        result["throttling"] = command("vcgencmd", "get_throttled", check=False).stdout.strip()
    return result


def network_apply(value):
    require_maintenance()
    if not isinstance(value, dict):
        raise ValueError("Provide a Wi-Fi network name and password")
    identity, profile = wifi_profile(value.get("ssid"), value.get("password"), autoconnect=False)
    checkpoint = command("gdbus", "call", "--system", "--dest", "org.freedesktop.NetworkManager",
                         "--object-path", "/org/freedesktop/NetworkManager", "--method",
                         "org.freedesktop.NetworkManager.CheckpointCreate", "[]", "120", "0").stdout
    match = re.search(r"(/org/freedesktop/NetworkManager/Checkpoint/\d+)", checkpoint)
    if not match:
        raise RuntimeError("NetworkManager did not create a recovery checkpoint")
    path = Path("/etc/NetworkManager/system-connections") / f"carvera-{identity}.nmconnection"
    path.touch(mode=0o600, exist_ok=False)
    with path.open("w") as output:
        profile.write(output, space_around_delimiters=False)
    write_json(RUN / "network-checkpoint.json", {"path": match[1], "uuid": identity, "expires": time.monotonic() + 120})
    command("nmcli", "connection", "load", str(path))
    command("nmcli", "--wait", "30", "connection", "up", "uuid", identity)
    return {"confirm_within_seconds": 120, "addresses": command("hostname", "-I").stdout.strip()}


def network_confirm():
    require_maintenance()
    checkpoint = read_json(RUN / "network-checkpoint.json")
    if not checkpoint:
        raise ValueError("No pending network change")
    command("gdbus", "call", "--system", "--dest", "org.freedesktop.NetworkManager",
            "--object-path", "/org/freedesktop/NetworkManager", "--method",
            "org.freedesktop.NetworkManager.CheckpointDestroy", checkpoint["path"])
    command("nmcli", "connection", "modify", checkpoint["uuid"], "connection.autoconnect", "yes")
    (RUN / "network-checkpoint.json").unlink()
    return {"network_confirmed": True}


def screen_start():
    service = "carvera-screen.service"
    if active(service):
        return {"owned": False}
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", 5900))
        except OSError as error:
            raise ValueError("Screen-sharing port 5900 is occupied by another process; it will be left alone") from error
    command("systemctl", "start", service)
    pid = command("systemctl", "show", "--property=MainPID", "--value", service).stdout.strip()
    if not pid.isdigit() or int(pid) == 0:
        raise RuntimeError("Screen sharing did not start")
    value = {"token": secrets.token_hex(16), "pid": pid}
    write_json(RUN / "screen.json", value)
    return {"owned": True, "token": value["token"]}


def screen_stop(token):
    owner = read_json(RUN / "screen.json")
    service = "carvera-screen.service"
    if not owner or not secrets.compare_digest(str(token), owner["token"]):
        raise ValueError("This screen session belongs to another viewer")
    pid = command("systemctl", "show", "--property=MainPID", "--value", service).stdout.strip()
    if pid != owner["pid"]:
        raise ValueError("The screen service was replaced; it will be left running")
    command("systemctl", "stop", service)
    (RUN / "screen.json").unlink()
    return {"screen_stopped": True}


def dispatch(args):
    if args.action in ("status", "diagnose"):
        return diagnostics()
    if args.action == "enter":
        return enter(args.confirm_machine_idle)
    if args.action == "leave":
        return leave()
    if args.action == "deploy":
        return deploy(args.value)
    if args.action == "rollback":
        return rollback()
    if args.action == "backup":
        destination = admin_path(args.value or "carvera-settings.tar.gz", "exports")
        backup(destination, owner="carvera-admin")
        return str(destination)
    if args.action == "logs":
        return command("journalctl", "--no-pager", "-n", "500", "-u", SERVICE,
                       "-u", "carvera-kiosk.service", "-u", "carvera-recovery.service").stdout
    if args.action == "screen-start":
        return screen_start()
    if args.action == "screen-stop":
        return screen_stop(args.value)
    if args.action == "network":
        return network_apply(args.value)
    if args.action == "network-confirm":
        return network_confirm()
    require_maintenance()
    if args.action == "governor":
        if args.value not in ("performance", "schedutil"):
            raise ValueError("Choose performance or schedutil")
        for path in Path("/sys/devices/system/cpu/cpufreq").glob("policy*/scaling_governor"):
            path.write_text(args.value)
        Path("/etc/carvera/cpu-governor").write_text(args.value + "\n")
        return {"governor": args.value}
    if args.action == "display":
        if args.value not in ("1920x1200", "1920x1080"):
            raise ValueError("Choose native 1920x1200 or comparison mode 1920x1080")
        command("runuser", "-u", "carvera", "--", "env", "XDG_RUNTIME_DIR=/run/carvera",
                "WAYLAND_DISPLAY=wayland-0", "python3", str(BASE / "maintenance/display.py"), args.value)
        Path("/etc/carvera/display-mode").write_text(args.value + "\n")
        return {"display": args.value}
    if args.action == "restart":
        request = read_json(RUN / "maintenance.request")
        request["confirmed_idle"] = True
        write_json(RUN / "maintenance.request", request)
        os.chmod(RUN / "maintenance.request", 0o644)
        command("systemctl", "restart", SERVICE)
        wait_ready(request["token"])
    else:
        command("systemctl", "reboot")
    return {"requested": args.action}


def main():
    if len(sys.argv) != 1:
        raise ValueError("This helper accepts a JSON request on standard input, without command arguments")
    if os.geteuid() != 0:
        raise ValueError("Run through the installed maintenance helper")
    request = json.loads(sys.stdin.read(65537))
    if not isinstance(request, dict) or set(request) - {"action", "value", "confirm_machine_idle"}:
        raise ValueError("Invalid maintenance request")
    args = SimpleNamespace(action=request.get("action"), value=request.get("value"),
                           confirm_machine_idle=request.get("confirm_machine_idle") is True)
    actions = {"status", "diagnose", "enter", "leave", "deploy", "rollback", "backup", "screen-start",
               "screen-stop", "restart", "reboot", "network", "network-confirm", "governor", "display", "logs"}
    if args.action not in actions:
        raise ValueError("Unknown maintenance action")
    if os.environ.get("SUDO_USER") != "carvera-admin":
        raise ValueError("This helper is restricted to the laptop maintenance account")
    with locked():
        result = dispatch(args)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
