"""Root-only, journaled updates of the kiosk system application and helpers."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath

from admin_accounts import atomic_write, read_json, write_json
from kiosk_state import maintenance_ack

BASE = Path("/opt/carvera")
STATE = Path("/var/lib/carvera-system")
RUN = Path("/run/carvera-maint")
STATUS = Path("/run/carvera/status.json")
UNITS = Path("/etc/systemd/system")
RUNTIME_UNITS = Path("/run/systemd/system")
SCREEN_CONFIG = Path("/etc/carvera/wayvnc.conf")
UPLOADS = Path("/home/kiosk-admin/transfers/uploads")
MANIFEST = "system-bundle.json"
UPDATER_VERSION = 1
LIMIT = 512 * 1024 * 1024
SERVICES = ("carvera-screen.service", "carvera-recovery.service", "carvera-controller.service", "carvera-kiosk.service")
UNIT_NAMES = {*SERVICES, "carvera-cpu.service"}
RUNTIME_NAMES = {
    "control.py",
    "controller.sh",
    "cpu.sh",
    "display.py",
    "network.py",
    "provision.py",
    "recovery.py",
    "recovery_control.py",
    "session-ready.sh",
    "settings.py",
    "system_operations.py",
    "system_ui.py",
    "admin_accounts.py",
    "kiosk_state.py",
    "runtime_profile.py",
    "kiosk_touch.py",
}
ALIASES = {"maintenance": "runtime", "recovery-venv": "venv", "system-ui": "system-ui"}


def command(*args, check=True, timeout=60, **kwargs):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout, **kwargs)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or f"{args[0]} failed")
    return result


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def version_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,79}", value):
        raise ValueError("Invalid system version")
    return value


def allowed_member(name):
    path = PurePosixPath(name)
    if path.as_posix() != name or path.is_absolute() or ".." in path.parts or "\\" in name or len(path.parts) < 2:
        return False
    area, tail = path.parts[0], path.parts[1:]
    if area == "runtime":
        return len(tail) == 1 and tail[0] in RUNTIME_NAMES
    if area == "units":
        return len(tail) == 1 and tail[0] in UNIT_NAMES
    if area == "config":
        return tail == ("wayvnc.conf",)
    if area == "wheels":
        return len(tail) == 1 and tail[0].endswith(".whl")
    if area == "system-ui":
        return tail[0] == "carveracontroller" and path.suffix in {
            ".py",
            ".kv",
            ".ttf",
            ".png",
            ".svg",
            ".mo",
            ".po",
            ".txt",
            ".md",
            ".json",
        }
    return False


def bounded_members(archive, size_limit, count_limit):
    entries, total = [], 0
    for entry in archive:
        entries.append(entry)
        total += entry.size
        if entry.size < 0 or len(entries) > count_limit or total > size_limit:
            raise ValueError("Archive exceeds supported limits")
    return entries


def unpack(bundle, destination=None):
    """Validate the complete archive before extracting any file."""
    with tarfile.open(bundle, "r:*") as archive:
        entries = bounded_members(archive, LIMIT, 4096)
        names = [entry.name for entry in entries]
        if len(names) != len(set(names)) or MANIFEST not in names:
            raise ValueError("Expected a system bundle with unique members")
        for entry in entries:
            if not entry.isfile() or entry.mode & 0o7022 or (entry.name != MANIFEST and not allowed_member(entry.name)):
                raise ValueError(f"Invalid system bundle member: {entry.name}")
        header = archive.getmember(MANIFEST)
        if header.size > 65536:
            raise ValueError("System manifest is too large")
        manifest = json.load(archive.extractfile(header))
        if not isinstance(manifest, dict) or manifest.get("kind") != "kiosk-system" or manifest.get("format") != 1:
            raise ValueError("Unsupported system bundle format")
        version_name(manifest.get("version"))
        if (
            manifest.get("architecture") != "aarch64"
            or manifest.get("os") != "debian-13"
            or manifest.get("python") != "3.13"
            or manifest.get("minimum_updater", 999) > UPDATER_VERSION
            or manifest.get("maintenance_protocols") != [1]
        ):
            raise ValueError("System bundle is incompatible with this updater")
        checksums = manifest.get("sha256")
        if not isinstance(checksums, dict) or set(checksums) != set(names) - {MANIFEST}:
            raise ValueError("System manifest does not match its files")
        required = {"runtime/control.py", "runtime/recovery.py", "runtime/recovery_control.py", "config/wayvnc.conf"}
        if not required <= set(names):
            raise ValueError("System bundle is incomplete")
        for entry in entries:
            checksum = hashlib.file_digest(archive.extractfile(entry), "sha256").hexdigest()
            if entry.name != MANIFEST and checksum != checksums[entry.name]:
                raise ValueError(f"Checksum mismatch: {entry.name}")
        if archive.getmember("config/wayvnc.conf").size > 4096:
            raise ValueError("Screen configuration is too large")
        config = archive.extractfile("config/wayvnc.conf").read().decode("utf-8")
        settings = dict(line.split("=", 1) for line in config.splitlines() if line and not line.startswith("#"))
        if settings != {"address": "127.0.0.1", "port": "5901", "enable_auth": "false"}:
            raise ValueError("Screen sharing must use the explicit localhost configuration")
        if destination is not None:
            destination = Path(destination)
            destination.mkdir(mode=0o700, parents=True, exist_ok=False)
            for entry in entries:
                target = destination / entry.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as output:
                    shutil.copyfileobj(archive.extractfile(entry), output, length=1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                target.chmod(0o755 if entry.name.endswith(".sh") else 0o644)
        return manifest, sum(entry.size for entry in entries)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def point(name, target):
    link = BASE / name
    temporary = BASE / ("." + name + ".next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    temporary.replace(link)
    sync_directory(BASE)


@contextlib.contextmanager
def locked(*, wait=False):
    RUN.mkdir(mode=0o755, parents=True, exist_ok=True)
    path = RUN / "control.lock"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError as error:
            raise ValueError("Another maintenance operation is in progress") from error
        yield


def process_alive(pid):
    try:
        return isinstance(pid, int) and pid > 0 and Path(f"/proc/{pid}").exists()
    except OSError:
        return False


def preflight(*, recovery=False, confirmed=False, allow_screen_interruption=False):
    transaction = read_json(STATE / "transaction.json")
    if transaction and transaction.get("phase") not in {"committed", "rolled-back"}:
        raise ValueError("Recover the interrupted system transaction before starting another update")
    for name in ("network-checkpoint.json", "display-checkpoint.json"):
        if read_json(RUN / name):
            raise ValueError("Finish the network/display trial before updating the system")
    operation = read_json(RUN / "system-operation.json")
    if operation.get("phase") in {"queued", "running"}:
        raise ValueError("Finish the pending System operation before updating")
    if (
        command("systemctl", "is-active", "carvera-screen.service", check=False).returncode == 0
        and not allow_screen_interruption
    ):
        raise ValueError("An active screen session requires explicit interruption approval")
    status = read_json(STATUS)
    if recovery:
        if not confirmed:
            raise ValueError("Recovery requires operator confirmation that the mill is physically disconnected")
        if (
            status
            and 0 <= time.monotonic() - status.get("updated", 0) <= 3
            and (status.get("connected") or status.get("busy"))
        ):
            raise ValueError("A fresh connected or busy controller cannot be overridden by recovery confirmation")
        return {"mode": "recovery", "controller_active": False}
    lease = read_json(RUN / "maintenance.json")
    request = read_json(RUN / "maintenance.request")
    if (
        not lease
        or lease.get("token") != request.get("token")
        or not 0 <= time.monotonic() - lease.get("entered", 0) <= 1800
    ):
        raise ValueError("Enter a valid maintenance session before updating")
    maintenance_ack(status, lease["token"])
    if status.get("maintenance_protocol", 1) != 1:
        raise ValueError("Unsupported controller maintenance protocol")
    return {"mode": "normal", "token": lease["token"], "controller_active": True}


def inventory(directory):
    result = {}
    for path in sorted(Path(directory).rglob("*")):
        if path.is_symlink():
            # Python virtual environments contain interpreter/library links.
            result[str(path.relative_to(directory))] = {"link": os.readlink(path)}
        elif path.is_file():
            result[str(path.relative_to(directory))] = {"sha256": digest(path), "mode": path.stat().st_mode & 0o777}
    return result


def snapshot_units(transaction):
    saved = STATE / "transactions" / transaction["id"] / "units"
    saved.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = {}
    for name in sorted(UNIT_NAMES):
        path = UNITS / name
        if path.is_symlink():
            raise ValueError(f"Review the custom service link before updating: {name}")
        exists = path.exists()
        if exists:
            atomic_write(saved / name, path.read_bytes(), 0o644)
        result[name] = {
            "exists": exists,
            "enabled": command("systemctl", "is-enabled", name, check=False).stdout.strip(),
        }
    config = SCREEN_CONFIG
    result["screen_config"] = {"exists": config.exists()}
    if config.exists():
        if config.is_symlink():
            raise ValueError("Review the custom screen configuration link")
        atomic_write(saved / "wayvnc.conf", config.read_bytes(), 0o644)
    transaction["unit_snapshot"] = result


def save_transaction(transaction):
    write_json(STATE / "transaction.json", transaction)


def import_legacy(transaction):
    if (BASE / "system-current").is_symlink():
        release = (BASE / "system-current").resolve()
        if release.parent != BASE / "system-releases":
            raise ValueError("Unexpected current system release")
        transaction["previous"] = str(release)
        save_transaction(transaction)
        return release
    release = BASE / "system-releases" / ("legacy-" + transaction["id"])
    release.mkdir(mode=0o755, parents=True, exist_ok=False)
    transaction["legacy"] = str(release)
    transaction["conversions"] = []
    save_transaction(transaction)
    saved_units = STATE / "transactions" / transaction["id"] / "units"
    shutil.copytree(saved_units, release / "units")
    if (saved_units / "wayvnc.conf").exists():
        (release / "config").mkdir()
        shutil.copyfile(saved_units / "wayvnc.conf", release / "config/wayvnc.conf")
    for alias, destination in ALIASES.items():
        source = BASE / alias
        if source.is_symlink() or (source.exists() and not source.is_dir()):
            raise ValueError(f"Unsupported legacy system layout: {source}")
        if not source.exists():
            if alias != "system-ui":
                raise ValueError(f"Missing legacy system component: {source}")
            transaction["conversions"].append({"alias": alias, "destination": destination, "existed": False})
            save_transaction(transaction)
            (release / destination).mkdir()
            source.symlink_to(Path("system-current") / destination, target_is_directory=True)
            sync_directory(BASE)
            continue
        entry = {"alias": alias, "destination": destination, "existed": True, "inventory": inventory(source)}
        transaction["conversions"].append(entry)
        save_transaction(transaction)
        source.rename(release / destination)
        sync_directory(release)
        sync_directory(BASE)
        source.symlink_to(Path("system-current") / destination, target_is_directory=True)
        sync_directory(BASE)
    write_json(
        release / MANIFEST,
        {
            "kind": "legacy-system",
            "version": release.name,
            "format": 1,
            "unit_snapshot": transaction["unit_snapshot"],
            "components": transaction["conversions"],
        },
    )
    point("system-current", release)
    transaction["previous"] = str(release)
    save_transaction(transaction)
    return release


def session_hook_override(enabled):
    path = RUNTIME_UNITS / "carvera-kiosk.service.d/90-system-update.conf"
    if enabled:
        atomic_write(path, "[Service]\nExecStartPost=\n", 0o644)
    else:
        path.unlink(missing_ok=True)
    command("systemctl", "daemon-reload")


def stop_services():
    for name in SERVICES:
        command("systemctl", "stop", name)


def install_units(release):
    manifest = read_json(release / MANIFEST)
    if manifest.get("kind") == "legacy-system":
        for name, value in manifest["unit_snapshot"].items():
            path = SCREEN_CONFIG if name == "screen_config" else UNITS / name
            source = release / "units" / ("wayvnc.conf" if name == "screen_config" else name)
            if value["exists"]:
                atomic_write(path, source.read_bytes(), 0o644)
            else:
                path.unlink(missing_ok=True)
        command("systemctl", "daemon-reload")
        return
    for path in (release / "units").glob("*.service"):
        if path.name not in UNIT_NAMES:
            raise ValueError("Unexpected system service")
        atomic_write(UNITS / path.name, path.read_bytes(), 0o644)
    config = release / "config/wayvnc.conf"
    if config.exists():
        atomic_write(SCREEN_CONFIG, config.read_bytes(), 0o644)
    command("systemctl", "daemon-reload")


def wait_for(predicate, message, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    raise RuntimeError(message)


def start_and_check(transaction, release):
    command("systemctl", "start", "carvera-kiosk.service")
    wait_for(lambda: Path("/run/carvera/wayland-0").is_socket(), "The kiosk compositor did not become ready")
    ready = Path("/run/carvera/system-ready.json")
    ready.unlink(missing_ok=True)
    command("systemctl", "start", "carvera-recovery.service")
    if read_json(release / MANIFEST).get("kind") == "legacy-system":
        # The captured legacy UI predates the readiness protocol.
        wait_for(
            lambda: command("systemctl", "is-active", "carvera-recovery.service", check=False).returncode == 0,
            "The legacy recovery service did not start",
        )
    else:
        expected = read_json(release / MANIFEST)["version"]

        def ui_ready():
            value = read_json(ready)
            main_pid = command(
                "systemctl", "show", "--property=MainPID", "--value", "carvera-recovery.service"
            ).stdout.strip()
            return (
                value.get("system_version") == expected
                and str(value.get("pid")) == main_pid
                and process_alive(value.get("pid"))
                and 0 <= time.monotonic() - value.get("updated", 0) <= 5
            )

        wait_for(ui_ready, "The independent System application did not render and contact its helper")
        reply = command(
            "/usr/bin/python3", "-E", "-s", str(release / "runtime/control.py"), input='{"action":"health"}'
        ).stdout
        if json.loads(reply).get("system_version") != expected:
            raise RuntimeError("The system helper did not report the activated release")
    if transaction["mode"] == "normal":
        command("systemctl", "stop", "carvera-recovery.service")
        STATUS.unlink(missing_ok=True)
        command("systemctl", "start", "carvera-controller.service")

        def acknowledged():
            try:
                current = read_json(STATUS)
                maintenance_ack(current, transaction["token"])
                return not current.get("connected", True)
            except ValueError:
                return False

        wait_for(acknowledged, "The controller did not reach disconnected maintenance")


def restore_units(transaction):
    saved = STATE / "transactions" / transaction["id"] / "units"
    for name, value in transaction.get("unit_snapshot", {}).items():
        path = SCREEN_CONFIG if name == "screen_config" else UNITS / name
        source = saved / ("wayvnc.conf" if name == "screen_config" else name)
        if value["exists"]:
            atomic_write(path, source.read_bytes(), 0o644)
        else:
            path.unlink(missing_ok=True)
    command("systemctl", "daemon-reload")


def undo(transaction, *, boot=False):
    if not boot:
        stop_services()
    previous = transaction.get("previous")
    if previous:
        point("system-current", Path(previous))
    else:
        legacy = Path(transaction["legacy"]) if transaction.get("legacy") else None
        for entry in reversed(transaction.get("conversions", [])):
            alias = BASE / entry["alias"]
            moved = legacy / entry["destination"]
            if alias.is_symlink():
                alias.unlink()
            if entry.get("existed", True) and moved.exists() and not alias.exists():
                moved.rename(alias)
                sync_directory(legacy)
                sync_directory(BASE)
        (BASE / "system-current").unlink(missing_ok=True)
    if "previous_pointer" in transaction:
        if transaction["previous_pointer"]:
            point("system-previous", Path(transaction["previous_pointer"]))
        else:
            (BASE / "system-previous").unlink(missing_ok=True)
    restore_units(transaction)
    transaction["phase"] = "restored"
    save_transaction(transaction)
    if not boot:
        try:
            session_hook_override(True)
            if previous:
                start_and_check(transaction, Path(previous))
            else:
                command("systemctl", "start", "carvera-kiosk.service")
                command("systemctl", "start", "carvera-recovery.service")
                if transaction["mode"] == "normal":
                    command("systemctl", "start", "carvera-controller.service")
        finally:
            session_hook_override(False)
    transaction["phase"] = "rolled-back"
    save_transaction(transaction)


def apply_release(release, options):
    with locked():
        conditions = preflight(**options)
        transaction = {"id": uuid.uuid4().hex, "phase": "preparing", **conditions}
        for name, field in (("system-current", "previous"), ("system-previous", "previous_pointer")):
            path = BASE / name
            if path.is_symlink():
                target = path.resolve(strict=True)
                if target.parent != BASE / "system-releases":
                    raise ValueError("Unexpected system release link")
                transaction[field] = str(target)
            elif path.exists():
                raise ValueError("Review the custom system release path")
            elif field == "previous_pointer":
                transaction[field] = None
        snapshot_units(transaction)
        save_transaction(transaction)
        try:
            session_hook_override(True)
            stop_services()
            previous = import_legacy(transaction)
            transaction["phase"] = "activating"
            save_transaction(transaction)
            point("system-current", release)
            install_units(release)
            start_and_check(transaction, release)
            point("system-previous", previous)
            session_hook_override(False)
            transaction["phase"] = "committed"
            save_transaction(transaction)
        except Exception:
            undo(transaction)
            raise
    return {"current": str(release), "previous": str(previous), "mode": conditions["mode"]}


def prepare_release(bundle, job=None):
    manifest, expanded = unpack(bundle)
    if platform.machine() not in {"aarch64", "arm64"} or sys.version_info[:2] != (3, 13):
        raise ValueError("System activation requires this image's aarch64 Python 3.13 platform")
    if 'VERSION_ID="13"' not in Path("/etc/os-release").read_text():
        raise ValueError("System activation requires Debian 13")
    release = BASE / "system-releases" / manifest["version"]
    if release.exists():
        raise ValueError("This system version already exists; build a new version")
    # Allow room for extraction, the new environment and private transfer copies.
    required = expanded * 4 + 256 * 1024 * 1024
    if shutil.disk_usage(BASE).free < required:
        raise ValueError(f"Insufficient storage: need {required} bytes without removing rollback releases")
    release.parent.mkdir(parents=True, exist_ok=True)
    stage = BASE / "system-releases" / ("staging-" + uuid.uuid4().hex)
    if job:
        write_json(job / "preparation.json", {"stage": str(stage), "release": str(release)})
    try:
        unpack(bundle, stage)
        stage.chmod(0o755)
        command("python3", "-m", "compileall", "-q", str(stage / "runtime"))
        command("systemd-analyze", "verify", *[str(path) for path in (stage / "units").glob("*.service")])
        (stage / "venv").mkdir(mode=0o755)
        command("chown", "carvera:carvera", str(stage / "venv"))
        command("runuser", "-u", "carvera", "--", "python3", "-m", "venv", str(stage / "venv"))
        command(
            "runuser",
            "-u",
            "carvera",
            "--",
            str(stage / "venv/bin/python"),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-cache-dir",
            "--find-links",
            str(stage / "wheels"),
            "Kivy==2.3.1",
            timeout=600,
        )
        command("chown", "-hR", "root:root", str(stage / "venv"))
        command("chmod", "-R", "go-w", str(stage))
        command("sync", "-f", str(stage))
        stage.rename(release)
        sync_directory(release.parent)
    except Exception:
        if stage.parent == BASE / "system-releases" and stage.name.startswith("staging-"):
            shutil.rmtree(stage, ignore_errors=True)
        raise
    return release


def updater_contents(bundle):
    with tarfile.open(bundle, "r:*") as archive:
        members = bounded_members(archive, 1024 * 1024, 4)
        names = [member.name for member in members]
        expected = {"updater-bundle.json", "system_update.py", "admin_accounts.py", "kiosk_state.py"}
        if (
            set(names) != expected
            or len(names) != len(expected)
            or sum(member.size for member in members) > 1024 * 1024
            or any(not member.isfile() or member.mode & 0o7022 for member in members)
        ):
            raise ValueError("Invalid updater bundle")
        manifest = json.load(archive.extractfile("updater-bundle.json"))
        if manifest.get("kind") != "kiosk-updater" or manifest.get("format") != 1:
            raise ValueError("Unsupported updater format")
        version = version_name(manifest.get("version"))
        if set(manifest.get("sha256", {})) != expected - {"updater-bundle.json"}:
            raise ValueError("Incomplete updater checksums")
        contents = {}
        for member in members:
            content = archive.extractfile(member).read()
            if (
                member.name != "updater-bundle.json"
                and hashlib.sha256(content).hexdigest() != manifest["sha256"][member.name]
            ):
                raise ValueError("Updater checksum mismatch")
            contents[member.name] = content
    return manifest, contents


def install_updater(bundle, job=None, options=None):
    manifest, contents = updater_contents(bundle)
    version = manifest["version"]
    release = BASE / "updater-releases" / version
    if release.exists():
        raise ValueError("This updater version already exists")
    stage = release.parent / ("staging-" + uuid.uuid4().hex)
    if job:
        write_json(job / "preparation.json", {"stage": str(stage), "release": str(release)})
    try:
        stage.mkdir(mode=0o755, parents=True)
        for name, content in contents.items():
            atomic_write(stage / name, content, 0o644)
        command("/usr/bin/python3", "-m", "compileall", "-q", str(stage))
        checked = json.loads(
            command("/usr/bin/python3", "-E", "-s", str(stage / "system_update.py"), "self-test").stdout
        )
        if checked.get("updater_version") != manifest.get("updater_version"):
            raise ValueError("Updater self-test did not match its manifest")
        with locked():
            preflight(**(options or {}))
            previous = (BASE / "updater").resolve(strict=True)
            if previous.parent != BASE / "updater-releases":
                raise ValueError("Unexpected active updater path")
            stage.rename(release)
            sync_directory(release.parent)
            point("updater-previous", previous)
            point("updater", release)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"updater": version, "previous": str(previous)}


def clean_preparation(directory):
    transaction = read_json(STATE / "transaction.json")
    if transaction and transaction.get("phase") not in {"committed", "rolled-back"}:
        return
    value = read_json(directory / "preparation.json")
    # These paths were recorded by the root worker, never supplied by the caller.
    for field in ("stage", "release"):
        path = Path(value[field]) if value.get(field) else None
        if (
            path is None
            or path.parent not in {BASE / "system-releases", BASE / "updater-releases"}
            or path.is_symlink()
        ):
            continue
        keep = {
            (BASE / name).resolve() for name in ("system-current", "system-previous", "updater", "updater-previous")
        }
        if path.exists() and path.resolve() not in keep:
            shutil.rmtree(path)
    (directory / "preparation.json").unlink(missing_ok=True)


def prune_releases():
    keep = {(BASE / name).resolve() for name in ("system-current", "system-previous")}
    for path in (BASE / "system-releases").iterdir():
        if path.is_symlink() or not path.is_dir() or path.resolve() in keep:
            continue
        manifest = read_json(path / MANIFEST)
        if manifest.get("version") == path.name and manifest.get("kind") in {"kiosk-system", "legacy-system"}:
            shutil.rmtree(path)


def private_upload(name, expected, directory):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", name):
        raise ValueError("Use a plain upload filename")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Supply the reviewed SHA-256 digest")
    if UPLOADS.is_symlink() or UPLOADS.parent.is_symlink():
        raise ValueError("The upload directory must not be a symbolic link")
    descriptor = os.open(UPLOADS / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    target = Path(directory) / "bundle.tar.gz"
    with os.fdopen(descriptor, "rb") as source, target.open("xb") as output:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise ValueError("Upload a regular system bundle no larger than 512 MiB")
        total = 0
        while chunk := source.read(1024 * 1024):
            total += len(chunk)
            if total > LIMIT:
                raise ValueError("Upload exceeds the supported limit")
            output.write(chunk)
    if digest(target) != expected:
        raise ValueError("The uploaded file differs from the reviewed digest")
    return target


def worker(identity):
    if not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid system job")
    directory = STATE / "jobs" / identity
    request = read_json(directory / "request.json")
    result = {"id": identity, "phase": "running", "pid": os.getpid(), "boot_id": boot_id()}
    write_json(directory / "result.json", result)
    try:
        options = request.get("options", {})
        if request["action"] == "apply":
            release = prepare_release(directory / "bundle.tar.gz", directory)
            answer = apply_release(release, options)
        elif request["action"] == "rollback":
            previous = BASE / "system-previous"
            if not previous.is_symlink():
                raise ValueError("There is no previous system release")
            release = previous.resolve()
            if release.parent != BASE / "system-releases":
                raise ValueError("Invalid previous system release")
            answer = apply_release(release, options)
        elif request["action"] == "updater-install":
            answer = install_updater(directory / "bundle.tar.gz", directory, options)
        else:
            raise ValueError("Unknown system operation")
        result.update(phase="complete", result=answer)
    except Exception as error:
        result.update(phase="failed", error=str(error))
    with locked(wait=True):
        try:
            (directory / "bundle.tar.gz").unlink(missing_ok=True)
            clean_preparation(directory)
            if result["phase"] == "complete" and request["action"] != "updater-install":
                prune_releases()
        except OSError as error:
            result["cleanup_error"] = str(error)
        write_json(directory / "result.json", result)


def submit(request):
    if set(request) - {"action", "name", "sha256", "options"} or request.get("action") not in {
        "apply",
        "rollback",
        "updater-install",
    }:
        raise ValueError("Invalid system operation")
    options = request.get("options", {})
    if not isinstance(options, dict) or set(options) - {"recovery", "confirmed", "allow_screen_interruption"}:
        raise ValueError("Invalid system operation options")
    if any(not isinstance(value, bool) for value in options.values()):
        raise ValueError("System confirmations must be booleans")
    with locked():
        preflight(**options)
        jobs = STATE / "jobs"
        jobs.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path in jobs.glob("*/result.json"):
            if read_json(path).get("phase") in {"preparing", "queued", "running"}:
                raise ValueError("A system job is already pending; inspect it before retrying")
        identity = uuid.uuid4().hex
        directory = jobs / identity
        directory.mkdir(mode=0o700)
        try:
            write_json(directory / "result.json", {"id": identity, "phase": "preparing", "boot_id": boot_id()})
            if request["action"] in {"apply", "updater-install"}:
                private_upload(request.get("name"), request.get("sha256"), directory)
                if request["action"] == "apply":
                    unpack(directory / "bundle.tar.gz")
                else:
                    updater_contents(directory / "bundle.tar.gz")
            write_json(directory / "request.json", request)
            source = Path(__file__).resolve().parent
            snapshot = directory / "worker"
            snapshot.mkdir()
            for name in ("system_update.py", "admin_accounts.py", "kiosk_state.py"):
                atomic_write(snapshot / name, (source / name).read_bytes(), 0o600)
            write_json(directory / "result.json", {"id": identity, "phase": "queued", "boot_id": boot_id()})
        except Exception:
            shutil.rmtree(directory)
            raise
        try:
            command(
                "systemd-run",
                "--quiet",
                "--collect",
                "--unit=carvera-update-" + identity,
                "/usr/bin/python3",
                "-E",
                "-s",
                str(snapshot / "system_update.py"),
                "worker",
                identity,
            )
        except Exception as error:
            write_json(directory / "result.json", {"id": identity, "phase": "failed", "error": str(error)})
            raise
    return {"id": identity, "phase": "queued"}


def status(identity=None):
    value = {
        "updater_version": UPDATER_VERSION,
        "updater": read_json(BASE / "updater/updater-bundle.json"),
        "system": read_json(BASE / "system-current" / MANIFEST),
        "previous": read_json(BASE / "system-previous" / MANIFEST),
        "controller": read_json(BASE / "current/bundle.json"),
        "image": read_json(Path("/boot/firmware/carvera-image.json")),
    }
    paths = sorted((STATE / "jobs").glob("*/result.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    value["recent_jobs"] = [read_json(path) for path in paths[:10]]
    if identity:
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Invalid system job")
        value["job"] = read_json(STATE / "jobs" / identity / "result.json")
    return value


def boot_id():
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def recover(*, boot=False):
    if not boot or command("systemctl", "is-system-running", check=False).stdout.strip() not in {
        "initializing",
        "starting",
    }:
        raise ValueError("Boot recovery runs only during startup; arrange an operator-approved safe reboot")
    with locked():
        jobs = list((STATE / "jobs").glob("*/result.json"))
        for path in jobs:
            result = read_json(path)
            if result.get("phase") in {"preparing", "queued", "running"} and result.get("boot_id") == boot_id():
                raise ValueError("A system worker belongs to this boot; inspect its service before recovery")
        transaction = read_json(STATE / "transaction.json")
        if transaction and transaction.get("phase") not in {"committed", "rolled-back"}:
            undo(transaction, boot=True)
        session_hook_override(False)
        for path in jobs:
            result = read_json(path)
            if result.get("phase") in {"preparing", "queued", "running"}:
                result.update(
                    phase="failed", error="The system job was interrupted by a reboot; inspect status before retrying"
                )
                write_json(path, result)
            clean_preparation(path.parent)
            (path.parent / "bundle.tar.gz").unlink(missing_ok=True)


def main():
    if os.geteuid() != 0 or os.environ.get("SUDO_USER", "root") not in {"root", "kiosk-admin"}:
        raise ValueError("Use kiosk-admin with sudo for system administration")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "inspect", "submit", "worker", "recover", "self-test", "repair"))
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    if args.action == "status":
        result = status(args.value)
    elif args.action == "self-test":
        result = {"updater_version": UPDATER_VERSION}
    elif args.action == "repair":
        release = Path(__file__).resolve().parent
        if release.parent != BASE / "updater-releases":
            raise ValueError("Run repair from a retained updater release")
        with locked():
            point("updater", release)
            atomic_write(
                Path("/usr/local/sbin/carvera-system-update"),
                '#!/bin/sh\nset -eu\nexec /usr/bin/python3 -E -s /opt/carvera/updater/system_update.py "$@"\n',
                0o755,
            )
        result = {"updater_restored": str(release)}
    elif args.action == "recover":
        recover(boot=args.value == "boot")
        result = {"recovered": True}
    elif args.action == "worker":
        worker(args.value)
        return
    else:
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError("System request is too large")
        request = json.loads(raw)
        if args.action == "inspect":
            with tempfile.TemporaryDirectory(dir=STATE) as temporary:
                source = private_upload(request.get("name"), request.get("sha256"), temporary)
                if request.get("action") == "updater-install":
                    manifest, contents = updater_contents(source)
                    expanded = sum(map(len, contents.values()))
                else:
                    manifest, expanded = unpack(source)
                result = {
                    "manifest": manifest,
                    "required_bytes": expanded * 4 + 256 * 1024 * 1024,
                    "free_bytes": shutil.disk_usage(BASE).free,
                    "current": status(),
                    "interruption": "Kiosk services stop; SSH remains available",
                }
        else:
            result = submit(request)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        sys.exit(1)
