"""Unprivileged access to the three operations supported by older kiosk images."""

import json
import math
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

from carveracontroller.kiosk_state import read_json, require_idle


def validate_wifi(ssid, password):
    if (
        not 1 <= len(ssid.encode("utf-8")) <= 32
        or not 8 <= len(password.encode("utf-8")) <= 63
        or any(char in ssid + password for char in "\r\n\0")
    ):
        raise ValueError("Use a network name of 1–32 bytes and a password of 8–63 bytes.")


class LegacySystem:
    def __init__(self, runtime=None, maintenance=None):
        self.runtime = Path(runtime or os.environ.get("CARVERA_RUNTIME_DIR", "/run/carvera"))
        self.maintenance = Path(maintenance or os.environ.get("CARVERA_MAINT_DIR", "/run/carvera-maint"))
        self.token = None
        self.wifi_started = None
        self.wifi_attempted = False
        self.wifi_kept = False
        self.uncertain = False

    def remaining(self):
        if self.wifi_started is None or self.wifi_kept:
            return 0
        return max(0, math.floor(120 - (time.monotonic() - self.wifi_started)))

    def owns_request(self):
        return bool(self.token and read_json(self.maintenance / "maintenance.request").get("token") == self.token)

    def guard(self, action):
        if action not in {"wifi", "wifi-confirm", "restart"}:
            raise ValueError("This image does not support that System action.")
        if self.uncertain:
            raise ValueError(
                "The previous request has an unknown outcome. Inspect and finish maintenance from the laptop."
            )
        status = read_json(self.runtime / "status.json")
        updated = status.get("updated", 0)
        if not isinstance(updated, (int, float)) or not math.isfinite(updated):
            raise ValueError("Controller activity is unavailable or stale.")
        require_idle(status, confirmed=True)
        existing = (self.maintenance / "maintenance.request").exists() or status.get("maintenance")
        if existing and not self.owns_request():
            raise ValueError("Maintenance is already active. Finish it from the laptop before making changes here.")
        if action == "wifi" and (existing or self.wifi_attempted and not self.wifi_kept):
            raise ValueError("Resolve the previous Wi-Fi attempt before connecting again.")
        if action == "wifi-confirm" and (not self.owns_request() or not self.remaining()):
            raise ValueError("The network confirmation is unavailable or expired. Refresh the controller status.")
        if action == "restart" and self.owns_request() and self.remaining():
            raise ValueError("Keep the Wi-Fi change or wait for its rollback before restarting.")

    def perform(self, action, *, confirmed_idle=False, ssid="", password=""):
        if confirmed_idle is not True:
            raise ValueError("Confirm that the machine is idle before making changes.")
        self.guard(action)
        request = {"action": action, "confirmed_idle": True}
        if action == "wifi":
            validate_wifi(ssid, password)
            request["wifi"] = {"ssid": ssid, "password": password}
            self.wifi_started = time.monotonic()
            self.wifi_attempted, self.wifi_kept = True, False
        try:
            result = subprocess.run(
                ["sudo", "-n", "/usr/local/sbin/carvera-recover"],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired as error:
            self.uncertain = True
            raise RuntimeError(
                "The request timed out. Its outcome is unknown; refresh status before another action."
            ) from error
        except OSError:
            self.uncertain = True
            raise
        if result.returncode:
            self.uncertain = True
            raise RuntimeError(
                result.stderr.strip()[:1500] or "The System action failed. Refresh status before retrying."
            )
        try:
            value = json.loads(result.stdout)
            expected = {"wifi": "confirm_within_seconds", "wifi-confirm": "network_confirmed", "restart": "restarted"}[
                action
            ]
            if not isinstance(value, dict) or value.get(expected) != (120 if action == "wifi" else True):
                raise ValueError()
        except ValueError as error:
            self.uncertain = True
            raise RuntimeError(
                "The helper returned an unknown result. Refresh status before another action."
            ) from error
        if action == "wifi":
            self.token = read_json(self.maintenance / "maintenance.request").get("token")
        if action == "wifi-confirm":
            self.wifi_kept = True
            self.token = None
        return value

    def overview(self):
        data = Path(os.environ.get("CARVERA_DATA_DIR", "/var/lib/carvera"))
        result = {
            "controller": read_json(self.runtime / "status.json"),
            "image": read_json(Path("/boot/firmware/carvera-image.json")).get("version"),
            "application": read_json(Path("/opt/carvera/current/bundle.json")).get("version"),
            "login": "carvera-admin@" + socket.gethostname() + ".local",
        }
        for key, command in (
            ("addresses", ["hostname", "-I"]),
            ("identity", ["ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub"]),
        ):
            try:
                reply = subprocess.run(command, capture_output=True, text=True, check=False, timeout=3)
                result[key] = reply.stdout.strip() if not reply.returncode else ""
            except (OSError, subprocess.TimeoutExpired):
                result[key] = ""
        try:
            result["temperature"] = f"{int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000:.1f} °C"
        except (OSError, ValueError):
            result["temperature"] = ""
        try:
            usage = shutil.disk_usage(data)
            result["storage"] = f"{usage.free / 1024**3:.1f} GiB / {usage.total / 1024**3:.1f} GiB"
        except OSError:
            result["storage"] = ""
        return result
