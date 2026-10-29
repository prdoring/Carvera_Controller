"""Status exchange between the kiosk application and local maintenance tools."""

import json
import os
import tempfile
import time
from pathlib import Path


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def activity(app):
    controller = app.root.controller
    flags = {
        "playing": bool(app.playing),
        "jogging": bool(controller.continuous_jog_active),
        "connecting": bool(controller._connecting),
        "sending": bool(controller.sendNUM or controller.loadNUM),
        "probing": bool(getattr(app.root, "probe_in_progress", False)),
        "settings": bool(getattr(getattr(app.root, "_settings_sender", None), "active", False)),
    }
    state = str(app.state)
    connected = controller.stream is not None
    return {
        "pid": os.getpid(),
        "updated": time.monotonic(),
        "state": state,
        "connected": connected,
        "busy": any(flags.values()) or (connected and state not in ("Idle", "Sleep")),
        "flags": flags,
        "maintenance": False,
    }


def require_idle(status, *, confirmed=False, now=None):
    age = (time.monotonic() if now is None else now) - status.get("updated", 0)
    if not status or not 0 <= age <= 3:
        raise ValueError("Controller activity is unavailable or stale; confirm machine idle for recovery.")
    if status.get("busy", True):
        raise ValueError("The controller or machine is busy.")
    if not status.get("connected") and not confirmed:
        raise ValueError("The machine is disconnected; explicitly confirm that it is idle.")


def maintenance_ack(status, token):
    require_idle(status, confirmed=True)
    if not status.get("maintenance") or status.get("token") != token:
        raise ValueError("The controller has not acknowledged this maintenance session.")
