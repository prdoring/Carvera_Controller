#!/usr/bin/python3
"""Privileged touchscreen operations: Wi-Fi recovery and controller restart."""

import json
import os
import sys

import control


def dispatch(request):
    if request["action"] == "wifi-confirm":
        result = control.network_confirm()
        control.leave()
        return result
    if not (control.RUN / "maintenance.request").exists():
        control.enter(confirmed=True)
    elif control.time.monotonic() - control.read_json(control.RUN / "maintenance.json").get("entered", 0) > 1800:
        control.leave()
        control.enter(confirmed=True)
    control.require_maintenance()
    if request["action"] == "wifi":
        return control.network_apply(request.get("wifi", {}))
    control.leave()
    control.command("systemctl", "--no-block", "restart", control.SERVICE)
    return {"restarted": True}


def main():
    if len(sys.argv) != 1 or os.geteuid() != 0 or os.environ.get("SUDO_USER") != "carvera":
        raise ValueError("Use the installed touchscreen recovery helper")
    request = json.loads(sys.stdin.read(8193))
    if not isinstance(request, dict) or set(request) - {"action", "wifi", "confirmed_idle"}:
        raise ValueError("Invalid recovery request")
    if request.get("action") not in ("wifi", "wifi-confirm", "restart"):
        raise ValueError("Only Wi-Fi recovery and controller restart are available")
    if request.get("confirmed_idle") is not True:
        raise ValueError("Confirm that the machine is idle before making changes")
    with control.locked():
        result = dispatch(request)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
