"""The independent recovery form must remain usable with its docked keyboard."""

import importlib.util
import os
from pathlib import Path

import pytest

from .conftest import capture_screenshot, pump_frames

pytestmark = pytest.mark.skipif(os.environ.get("CARVERA_PROFILE") != "kiosk", reason="Dedicated recovery run")


def test_recovery_network_fields_stay_above_keyboard(monkeypatch, tmp_path):
    from kivy.base import EventLoop
    from kivy.core.window import Window
    from kivy.uix.vkeyboard import VKeyboard

    root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(root)
    monkeypatch.setenv("CARVERA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CARVERA_RUNTIME_DIR", str(tmp_path / "run"))
    monkeypatch.syspath_prepend(str(root / "carveracontroller"))
    monkeypatch.syspath_prepend(str(root / "assets/packaging/kiosk/runtime"))
    source = root / "assets/packaging/kiosk/runtime/recovery.py"
    spec = importlib.util.spec_from_file_location("kiosk_recovery_ui", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.Recovery, "refresh", lambda self: None)
    app = module.Recovery()
    try:
        app._run_prepare()
        app.choose("Network")
        pump_frames(8)
        app.ssid.focus = True
        pump_frames(20, sleep=0.04)
        height = max(child.height for child in Window.children if isinstance(child, VKeyboard))
        keyboard = next(child for child in Window.children if isinstance(child, VKeyboard))
        assert max(pos[0] + size[0] for pos, size in keyboard.layout_geometry["LINE_1"]) >= Window.width * 0.9
        assert app.ssid.to_window(*app.ssid.pos)[1] >= height
        assert app.password.to_window(*app.password.pos)[1] >= height
        capture_screenshot(app, "kiosk_system_network_keyboard")
    finally:
        app.ssid.focus = False
        app.stop()
        EventLoop.close()
