"""Forward native SDL finger events to Kivy on the Linux kiosk."""

import configparser
import io
import os
import sys
import tempfile
from pathlib import Path


class TouchInput:
    __slots__ = ("_storage", "_queue", "events")
    _carvera_touch_bridge = True

    def __init__(self, storage, queue):
        self._storage = storage
        self._queue = queue
        self.events = {"fingerdown": 0, "fingermotion": 0, "fingerup": 0}

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def __setattr__(self, name, value):
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._storage, name, value)

    def poll(self):
        while True:
            event = self._storage.poll()
            if not event or event[0] not in self.events:
                return event
            # Kivy's SDL window filters desktop finger events. Its motion
            # provider accepts the same tuples and retains each finger's ID.
            self.events[event[0]] += 1
            self._queue.appendleft(event)


def install(window):
    if sys.platform != "linux" or os.environ.get("CARVERA_PROFILE") != "kiosk":
        return None
    if getattr(window._win, "_carvera_touch_bridge", False):
        return window._win
    from kivy.core.window.window_sdl2 import SDL2MotionEventProvider
    from kivy.logger import Logger

    window._win = TouchInput(window._win, SDL2MotionEventProvider.q)
    Logger.info("Kiosk: Native SDL touch forwarding enabled on Linux")
    return window._win


def uninstall(window, bridge):
    if bridge is not None and window._win is bridge:
        window._win = bridge._storage


def start(window, context):
    context.bridge = install(window)


def stop(window, context):
    uninstall(window, context.bridge)


def _write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def prepare_recovery(home):
    """Install a self-contained Kivy input module for independent recovery."""
    home = Path(home)
    modules = home / "mods"
    modules.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).read_bytes()
    module = modules / "carvera_touch.py"
    if not module.exists() or module.read_bytes() != source:
        _write(module, source)
    path = home / "config.ini"
    config = configparser.ConfigParser(interpolation=None)
    config.read(path, encoding="utf-8")
    if not config.has_section("modules"):
        config.add_section("modules")
    config.set("modules", "carvera_touch", "")
    output = io.StringIO()
    config.write(output)
    _write(path, output.getvalue().encode("utf-8"))


if __name__ == "__main__":
    prepare_recovery(sys.argv[1])
