"""Root-owned startup gate and fixed actions for incomplete initial setup."""

import argparse
import re

import provision_v3


def dispatch(request):
    import control

    if (
        set(request) != {"action", "id"}
        or not isinstance(request["id"], str)
        or not re.fullmatch("[a-f0-9]{32}", request["id"])
    ):
        raise ValueError("Invalid initial-setup action")
    if request["action"] == "setup-status":
        return provision_v3.status()
    if request["action"] not in {"setup-retry", "setup-shutdown"}:
        raise ValueError("Unsupported initial-setup action")
    with control.locked():
        if provision_v3.completion_ready():
            raise ValueError("Initial setup is complete; use normal System controls")
        if any(control.active(name) for name in ("carvera-controller.service", "carvera-recovery.service")):
            raise ValueError("Initial-setup actions require the controller and full System app to be stopped")
        if request["action"] == "setup-shutdown":
            control.command("systemctl", "poweroff")
            return {"requested": "shutdown"}
        control.command(
            "systemd-run",
            "--quiet",
            "--no-block",
            "--collect",
            "--unit=carvera-setup-retry",
            "--property=RuntimeMaxSec=15min",
            "/usr/bin/python3",
            "-E",
            "-s",
            "/opt/carvera/maintenance/setup_gate.py",
            "--retry",
        )
        return {"phase": "queued"}


def retry():
    """Run outside the limited application's service, including a storage retry."""
    import os

    import control

    if os.geteuid() != 0:
        raise PermissionError("Initial setup retry requires its installed helper")
    with control.locked():
        if any(control.active(name) for name in ("carvera-controller.service", "carvera-recovery.service")):
            raise ValueError("Initial setup retry requires both applications to be stopped")
        for service, timeout in (("carvera-root-grow.service", 620), ("carvera-provision.service", 120)):
            control.command("systemctl", "reset-failed", service, check=False)
            control.command("systemctl", "restart", service, timeout=timeout)
        if not provision_v3.completion_ready():
            raise ValueError("Initial setup remains incomplete")
    control.command("/opt/carvera/maintenance/session-ready.sh")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()
    if args.check:
        raise SystemExit(0 if provision_v3.completion_ready() else 1)
    if args.retry:
        return retry()
    provision_v3.publish_status()


if __name__ == "__main__":
    main()
