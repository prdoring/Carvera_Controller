#!/usr/bin/python3
"""Restricted entry point for touchscreen system settings."""

import json
import os
import subprocess
import sys
import tarfile
import time

import control
import system_operations as operations


def dispatch(request):
    return operations.dispatch(request)


def launch_operation(request):
    action = operations.validate(request)
    path = control.RUN / ("system-request-" + request["id"] + ".json")
    with control.locked():
        previous = operations.operation_status()
        if previous.get("id") == request["id"]:
            if previous.get("phase") == "complete":
                return previous["result"]
            raise ValueError("This request has already been attempted. Refresh system details before retrying.")
        if previous.get("phase") in {"queued", "running"}:
            raise ValueError("Another system operation is in progress")
        control.write_json(path, request)
        operations.remember(
            {"id": request["id"], "action": action, "phase": "queued", "pid": os.getpid(), "started": time.monotonic()}
        )
        try:
            process = subprocess.Popen(
                [
                    "systemd-run",
                    "--quiet",
                    "--wait",
                    "--pipe",
                    "--collect",
                    "--unit=carvera-system-" + request["id"],
                    "--property=RuntimeMaxSec=1800s",
                    "/usr/bin/python3",
                    "-E",
                    "-s",
                    str(control.BASE / "maintenance/recovery_control.py"),
                    "--operation",
                    request["id"],
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError:
            path.unlink(missing_ok=True)
            operations.remember(
                {
                    "id": request["id"],
                    "action": action,
                    "phase": "failed",
                    "message": "The system worker could not start.",
                }
            )
            raise
    try:
        stdout, _stderr = process.communicate(timeout=900)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError("The operation is still being checked. Refresh its status before attempting another action.")
    try:
        reply = json.loads(stdout)
    except ValueError as error:
        if operations.operation_status().get("phase") == "queued":
            path.unlink(missing_ok=True)
            operations.remember(
                {
                    "id": request["id"],
                    "action": action,
                    "phase": "failed",
                    "message": "The system worker could not start.",
                }
            )
        raise RuntimeError("The system worker did not return a result. Refresh details before retrying.") from error
    if process.returncode or not reply.get("ok"):
        raise RuntimeError(reply.get("error") or "The system operation failed")
    return reply["result"]


def execute_operation(identity):
    operations.validate({"action": "status", "id": identity})
    path = control.RUN / ("system-request-" + identity + ".json")
    try:
        for attempt in range(100):
            try:
                with control.locked():
                    request = control.read_json(path)
                    if request.get("id") != identity:
                        raise ValueError("Invalid system worker request")
                    return operations.run(request, queued=True)
            except ValueError as error:
                if str(error) != "Another maintenance operation is in progress" or attempt == 99:
                    raise
                time.sleep(0.05)
    finally:
        path.unlink(missing_ok=True)


def main():
    if os.geteuid() != 0:
        raise ValueError("Use the installed touchscreen recovery helper")
    if len(sys.argv) == 3 and sys.argv[1] == "--revert-display" and not os.environ.get("SUDO_USER"):
        with control.locked():
            return operations.revert_display(sys.argv[2])
    if len(sys.argv) == 3 and sys.argv[1] == "--operation" and not os.environ.get("SUDO_USER"):
        result = execute_operation(sys.argv[2])
        print(json.dumps({"ok": True, "result": result}))
        return None
    if len(sys.argv) != 1 or os.environ.get("SUDO_USER") != "carvera":
        raise ValueError("Use the installed touchscreen recovery helper")
    raw = sys.stdin.read(8193)
    if len(raw) > 8192:
        raise ValueError("System request is too large")
    request = json.loads(raw)
    if isinstance(request, dict) and request.get("action") in {"setup-status", "setup-retry", "setup-shutdown"}:
        import setup_gate

        result = setup_gate.dispatch(request)
        print(json.dumps({"ok": True, "result": result}))
        return None
    from provision_v3 import completion_ready

    if not completion_ready():
        raise ValueError("Complete kiosk setup before opening System settings")
    action = operations.validate(request)
    if action == "status":
        result = operations.status()
    elif action == "open":
        result = operations.open_system()
    else:
        result = launch_operation(request)
    print(json.dumps({"ok": True, "result": result}))


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        RuntimeError,
        KeyError,
        TypeError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        print(json.dumps({"ok": False, "error": str(error)[:1000]}))
        sys.exit(1)
