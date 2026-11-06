"""Owned screen leases; renewals and cleanup never take the global update lock."""

import argparse
import contextlib
import fcntl
import json
import os
import re
import secrets
import socket
import subprocess
import time
from pathlib import Path

from admin_accounts import read_json, write_json

RUN = Path("/run/carvera-maint")
SERVICE = "carvera-screen.service"
WATCHDOG = "carvera-screen-watchdog.service"
LEASE_SECONDS = 90
HEARTBEAT_SECONDS = 20


def command(*args, check=True):
    result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=20)
    if check and result.returncode:
        raise RuntimeError("The owned screen service could not be managed")
    return result


@contextlib.contextmanager
def locked():
    RUN.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor = os.open(RUN / "screen.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        os.close(descriptor)
        raise ValueError("Unsafe screen-session lock")
    with os.fdopen(descriptor, "w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def service_identity():
    pid = command("systemctl", "show", "--property=MainPID", "--value", SERVICE).stdout.strip()
    invocation = command("systemctl", "show", "--property=InvocationID", "--value", SERVICE).stdout.strip()
    return {"pid": int(pid) if pid.isdigit() else 0, "invocation": invocation}


def listener_owned(pid):
    inodes = set()
    try:
        for path in Path(f"/proc/{pid}/fd").iterdir():
            try:
                link = os.readlink(path)
            except OSError:
                continue
            match = re.fullmatch(r"socket:\[(\d+)\]", link)
            if match:
                inodes.add(match[1])
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            if fields[1] == "0100007F:170D" and fields[3] == "0A" and fields[9] in inodes:
                return True
    except OSError:
        return False
    return False


def matches(owner, current):
    return bool(
        owner
        and str(owner.get("pid", "")).isdigit()
        and int(owner["pid"]) > 0
        and str(owner["pid"]) == str(current["pid"])
        and re.fullmatch("[a-f0-9]{32}", str(owner.get("invocation", "")))
        and owner["invocation"] == current["invocation"]
    )


def remove_owned(owner, reason):
    """Caller holds the screen lock. A replaced service is never stopped."""
    owned = matches(owner, service_identity())
    if owned:
        command("systemctl", "stop", SERVICE)
    write_json(RUN / "screen-ended.json", {"generation": owner.get("generation"), "reason": reason})
    (RUN / "screen.json").unlink(missing_ok=True)
    return owned


def start(value):
    if value != {"lease_protocol": 1}:
        raise ValueError("Update the laptop viewer: this server requires screen lease protocol 1")
    with locked():
        if command("systemctl", "is-active", "--quiet", SERVICE, check=False).returncode == 0:
            raise ValueError("A screen session is already active; close its original viewer")
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", 5901))
            except OSError as error:
                raise ValueError("Screen port 5901 is occupied; the existing listener was left alone") from error
        command("systemctl", "start", SERVICE)
        owner = service_identity()
        try:
            if not owner["pid"] or not re.fullmatch("[a-f0-9]{32}", owner["invocation"]):
                raise RuntimeError("Screen sharing did not report its process identity")
            deadline = time.monotonic() + 10
            while not listener_owned(owner["pid"]):
                if time.monotonic() >= deadline or not matches(owner, service_identity()):
                    raise RuntimeError("The owned localhost screen listener did not become ready")
                time.sleep(0.1)
            owner.update(
                {
                    "token": secrets.token_hex(32),
                    "generation": secrets.token_hex(16),
                    "expires": time.monotonic() + LEASE_SECONDS,
                    "lease_protocol": 1,
                }
            )
            write_json(RUN / "screen.json", owner)
            command("systemctl", "restart", WATCHDOG)
        except Exception:
            if owner.get("pid") and matches(owner, service_identity()):
                command("systemctl", "stop", SERVICE, check=False)
            (RUN / "screen.json").unlink(missing_ok=True)
            raise
        return {
            "owned": True,
            "token": owner["token"],
            "generation": owner["generation"],
            "lease_protocol": 1,
            "heartbeat_seconds": HEARTBEAT_SECONDS,
            "lease_seconds": LEASE_SECONDS,
        }


def authenticated(value, owner):
    return (
        isinstance(value, dict)
        and set(value) == {"token", "generation"}
        and owner
        and isinstance(value.get("token"), str)
        and secrets.compare_digest(value["token"], str(owner.get("token", "")))
        and value.get("generation") == owner.get("generation")
    )


def renew(value):
    with locked():
        owner = read_json(RUN / "screen.json")
        if not authenticated(value, owner):
            raise ValueError("This screen session has ended or belongs to another viewer")
        if owner.get("expires", 0) <= time.monotonic():
            remove_owned(owner, "expired")
            raise ValueError("The screen session expired; connect again explicitly")
        current = service_identity()
        if owner.get("expires", 0) <= time.monotonic():
            remove_owned(owner, "expired")
            raise ValueError("The screen session expired; connect again explicitly")
        if not matches(owner, current):
            remove_owned(owner, "replaced")
            raise ValueError("The screen service changed; its replacement was left alone")
        owner["expires"] = time.monotonic() + LEASE_SECONDS
        write_json(RUN / "screen.json", owner)
        return {"renewed": True, "lease_seconds": LEASE_SECONDS}


def stop(value):
    with locked():
        owner = read_json(RUN / "screen.json")
        if not authenticated(value, owner):
            raise ValueError("This screen session belongs to another viewer")
        stopped = remove_owned(owner, "closed")
        return {"screen_stopped": stopped, "replacement_preserved": not stopped}


def expire():
    with locked():
        owner = read_json(RUN / "screen.json")
        if not owner:
            return False
        if owner.get("expires", 0) <= time.monotonic() or not matches(owner, service_identity()):
            remove_owned(owner, "expired")
            return False
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", required=True)
    parser.parse_args()
    if os.geteuid() != 0 or os.environ.get("SUDO_USER"):
        raise ValueError("Use the managed root screen watchdog")
    while expire():
        time.sleep(5)


if __name__ == "__main__":
    main()
