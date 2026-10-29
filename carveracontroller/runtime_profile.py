"""Runtime settings for the dedicated Linux touchscreen image."""

import os
from pathlib import Path

maintenance_active = False


def is_kiosk():
    return os.environ.get("CARVERA_PROFILE") == "kiosk"


def uses_touch(platform):
    return platform == "android" or is_kiosk()


def may_connect(*, automatic=False):
    directory = Path(os.environ.get("CARVERA_MAINT_DIR", "/run/carvera-maint"))
    return not is_kiosk() or not (
        maintenance_active
        or (directory / "maintenance.request").exists()
        or automatic
    )


def prepare():
    """Set paths and SDL options before importing Kivy."""
    if not is_kiosk():
        return
    data = Path(os.environ.get("CARVERA_DATA_DIR", "/var/lib/carvera"))
    data.mkdir(parents=True, exist_ok=True)
    (data / "gcodes").mkdir(exist_ok=True)
    os.environ.setdefault("KIVY_HOME", str(data / ".kivy"))
    os.environ.setdefault("KIVY_METRICS_DENSITY", "1.5")
    os.environ.setdefault("SDL_TOUCH_MOUSE_EVENTS", "0")
    os.environ.setdefault("SDL_MOUSE_TOUCH_EVENTS", "0")
    os.chdir(data)


def configure(config):
    if not is_kiosk():
        return
    config.set("graphics", "fullscreen", "auto")
    config.set("graphics", "maxfps", "60")
    config.set("graphics", "show_cursor", "0")
    config.set("kivy", "keyboard_mode", "dock")
    config.set("kivy", "exit_on_escape", "0")
    config.set("kivy", "log_level", "info")
    config.set("kivy", "log_maxfiles", "10")
    for key, _value in list(config.items("input")):
        config.remove_option("input", key)
    config.set("input", "mouse", "mouse,disable_multitouch")
