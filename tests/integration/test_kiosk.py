"""Linux kiosk checks with simulated machine hardware."""

import ctypes
import os
import subprocess
import sys
from collections import deque
from types import SimpleNamespace

import pytest

from .conftest import pump_frames

pytestmark = pytest.mark.skipif(os.environ.get("CARVERA_PROFILE") != "kiosk", reason="Dedicated kiosk run")


def test_touch_bridge_preserves_mouse_keyboard_and_storage_access():
    from carveracontroller.kiosk_touch import TouchInput

    events = iter([("fingerdown", 5, 0.2, 0.4, 1), ("mousemotion", 10, 20),
                   ("fingerup", 5, 0.2, 0.4, 1), ("keydown", 65), False])
    storage = SimpleNamespace(poll=lambda: next(events), title="original")
    queue = deque()
    bridge = TouchInput(storage, queue)
    assert bridge.poll() == ("mousemotion", 10, 20)
    assert bridge.poll() == ("keydown", 65)
    assert bridge.poll() is False
    assert [queue.pop()[0], queue.pop()[0]] == ["fingerdown", "fingerup"]
    bridge.title = "changed"
    assert storage.title == bridge.title == "changed"
    assert bridge.events == {"fingerdown": 1, "fingermotion": 0, "fingerup": 1}


def test_recovery_loads_touch_module_without_the_application(tmp_path):
    from carveracontroller.kiosk_touch import prepare_recovery

    home = tmp_path / "recovery"
    home.mkdir()
    (home / "config.ini").write_text("[graphics]\nmaxfps=30\n")
    prepare_recovery(home)
    assert "maxfps = 30" in (home / "config.ini").read_text()
    environment = dict(os.environ, KIVY_HOME=str(home), CARVERA_PROFILE="kiosk")
    environment.pop("PYTHONPATH", None)
    code = (
        "import sys; from kivy.core.window import Window; "
        "assert Window._win._carvera_touch_bridge; "
        "assert 'carveracontroller' not in sys.modules; Window.close()"
    )
    subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=environment,
                   capture_output=True, text=True, check=True, timeout=30)


def test_native_sdl_fingers_reach_linux_touch_widgets(kivy_app):
    from kivy.core.window import Window
    from kivy.uix.widget import Widget

    class Finger(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("timestamp", ctypes.c_uint32),
                    ("touch_id", ctypes.c_int64), ("finger_id", ctypes.c_int64),
                    ("x", ctypes.c_float), ("y", ctypes.c_float),
                    ("dx", ctypes.c_float), ("dy", ctypes.c_float),
                    ("pressure", ctypes.c_float), ("window_id", ctypes.c_uint32)]

    class Event(ctypes.Union):
        _fields_ = [("finger", Finger), ("padding", ctypes.c_uint8 * 56)]

    sdl = ctypes.CDLL("libSDL2-2.0.so.0")
    sdl.SDL_PushEvent.argtypes = [ctypes.POINTER(Event)]
    sdl.SDL_PushEvent.restype = ctypes.c_int
    received = []

    class Sink(Widget):
        def on_touch_down(self, touch):
            received.append(("down", touch.id, touch.sx, touch.sy))
            return True

        def on_touch_move(self, touch):
            received.append(("move", touch.id, touch.sx, touch.sy))
            return True

        def on_touch_up(self, touch):
            received.append(("up", touch.id, touch.sx, touch.sy))
            return True

    sink = Sink(size_hint=(None, None), size=Window.size)
    Window.add_widget(sink)
    try:
        for kind, finger_id, x in [(0x700, 501, 0.2), (0x700, 502, 0.6),
                                    (0x702, 501, 0.3), (0x701, 501, 0.3), (0x701, 502, 0.6)]:
            event = Event()
            event.finger = Finger(kind, 0, 1, finger_id, x, 0.4, 0, 0, 1, 0)
            assert sdl.SDL_PushEvent(ctypes.byref(event)) == 1
            Window.mainloop()
            pump_frames(2)
        assert [(kind, fid) for kind, fid, *_ in received] == [
            ("down", 501), ("down", 502), ("move", 501), ("up", 501), ("up", 502),
        ]
        assert received[0][2:] == pytest.approx((0.2, 0.6))
    finally:
        Window.remove_widget(sink)


def test_kiosk_shares_touch_layout_without_android_services(kivy_app):
    from kivy.config import Config
    from kivy.core.window import Window
    from kivy.utils import platform

    assert platform == "linux"
    assert kivy_app.touch_mode and kivy_app.android_touch
    assert kivy_app._touch_layout is not None
    assert kivy_app._android_input is None
    assert "jnius" not in sys.modules
    assert Config.get("kivy", "keyboard_mode") == "dock"
    assert tuple(Window.size) == (1920, 1200)
    assert kivy_app._kiosk.renderer


@pytest.mark.parametrize("state", ["Idle", "Run", "Pause", "Hold"])
def test_kiosk_footer_keeps_desktop_icons_and_touch_targets(kivy_app, connected_idle_state, state):
    from carveracontroller.CNC import CNC

    app = kivy_app
    original = app.state, app.playing, app.selected_remote_filename
    app.root.config_loaded = True
    CNC.vars["state"] = app.state = state
    app.playing = state in ("Run", "Pause")
    app.selected_remote_filename = "fixture.cnc"
    expected = {
        "Files": "data/file.png",
        "Resume" if state == "Pause" else "Job": "data/start.png" if state == "Pause" else "data/config_start.png",
        "Pause": "data/suspend.png",
        "Abort": "data/abort.png",
        "Hold": "data/feedhold2.png" if state == "Hold" else "data/feedhold1.png",
    }
    try:
        app._touch_layout.update()
        pump_frames(12)
        footer = app.root.ids.main_file_button.parent
        actions = {widget.android_label: widget for widget in footer.children if getattr(widget, "android_label", "")}
        for caption, icon in expected.items():
            button = actions[caption]
            assert button.icon == icon
            assert not button.text
            assert button.opacity == 1
            assert button.width >= app.touch_target and button.height >= app.touch_target
            assert button.x >= footer.x and button.right <= footer.right
            assert button.y >= footer.y and button.top <= footer.top
        assert actions["Stop"].text == "Stop"
        assert actions["Stop"].width >= app.touch_target
        assert actions["Stop"].right <= footer.right
    finally:
        app.state, app.playing, app.selected_remote_filename = original
        app._touch_layout.update()


def test_virtual_keyboard_uses_shared_touch_layout(kivy_app):
    from kivy.core.window import Window
    from kivy.uix.vkeyboard import VKeyboard

    from carveracontroller.ui.editing import EditingTextInput

    field = EditingTextInput(size_hint=(None, None), size=(500, 80), pos=(100, 100), multiline=False)
    kivy_app.root.add_widget(field)
    try:
        field.focus = True
        pump_frames(20)
        assert any(isinstance(child, VKeyboard) for child in Window.children)
        assert kivy_app.android_keyboard_height > 0
    finally:
        field.focus = False
        kivy_app.root.remove_widget(field)
        pump_frames(10)
    assert kivy_app.android_keyboard_height == 0


@pytest.mark.parametrize("source", ["local", "remote"])
def test_file_selection_does_not_open_keyboard(kivy_app, connected_idle_state, source):
    from kivy.core.window import Window
    from kivy.uix.vkeyboard import VKeyboard

    from tests.unit.test_touch import dispatch, finger

    app = kivy_app
    app.state = "Idle"
    app.root.config_loaded = True
    popup = app.root.file_popup
    rv = getattr(popup, source + "_rv")
    original = list(rv.data), rv.browser_state
    popup.popup_manager.current = source + "_page"
    popup.open(animation=False)
    rv.browser_state = ""
    rv.data = [{"filename": "fixture.cnc", "filedate": "2026-10-29 12:00",
                "filesize": "1 KB", "intsize": 1024, "is_dir": False, "rv_key": 0}]
    pump_frames(20)
    try:
        row = next(row for row in rv.view_adapter.views.values() if row.parent is not None)
        touch = finger(*row.to_window(*row.center))
        dispatch("begin", touch)
        dispatch("end", touch)
        pump_frames(12, sleep=.02)
        assert rv.curr_selected_file.endswith("fixture.cnc")
        assert not any(isinstance(child, VKeyboard) for child in Window.children)
        assert app.android_keyboard_height == 0

        popup._mobile_search_buttons[source].dispatch("on_release")
        pump_frames(12)
        assert getattr(popup, "ti_" + source + "_search").focus
        assert any(isinstance(child, VKeyboard) for child in Window.children)
    finally:
        popup._mobile_search_sheets[source].dismiss(animation=False)
        rv.layout_manager.focus = False
        rv.layout_manager.clear_selection()
        rv.data, rv.browser_state = original
        popup.dismiss(force=True, animation=False)
        pump_frames(10)


def test_maintenance_waits_for_idle_and_restores_controls(kivy_app):
    from carveracontroller import runtime_profile
    from carveracontroller.kiosk_state import read_json, write_json

    runtime = kivy_app._kiosk
    path = runtime.maintenance / "maintenance.request"
    before = (kivy_app.root.keyboard_jog_control, kivy_app.root.pendant_jog_control)
    write_json(path, {"token": "integration", "confirmed_idle": True})
    try:
        runtime.tick(0)
        assert runtime.pending == "integration"
        assert runtime.token is None
        assert runtime_profile.maintenance_active
        pump_frames(50, sleep=0.05)
        assert runtime.token == "integration"
        assert kivy_app.root.disabled
        assert read_json(runtime.directory / "status.json")["maintenance"]
        assert runtime.panel is not None
    finally:
        path.unlink(missing_ok=True)
        runtime.tick(0)
    assert not kivy_app.root.disabled
    assert not runtime_profile.maintenance_active
    assert before == (kivy_app.root.keyboard_jog_control, kivy_app.root.pendant_jog_control)


@pytest.mark.parametrize("which", ["probing", "facing", "cmm"])
def test_kiosk_forms_keep_touch_targets_above_keyboard(kivy_app, which):
    from kivy.core.window import Window
    from kivy.uix.button import Button

    root = kivy_app.root
    if which == "probing":
        from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

        modal = ProbingPopup(root.controller)
    elif which == "facing":
        from carveracontroller.addons.facing.FacingWizardPopup import FacingWizardPopup

        modal = FacingWizardPopup()
    else:
        modal = root._ensure_cmm_workbench_popup()
    try:
        modal.open(animation=False)
        pump_frames(8, sleep=0.04)
        kivy_app.android_keyboard_height = 420
        pump_frames(8, sleep=0.04)
        assert modal.y >= 420
        assert modal.top <= Window.height + 1
        buttons = [widget for widget in modal.walk() if isinstance(widget, Button) and widget.opacity and widget.width]
        assert all(widget.height >= kivy_app.touch_target - 1 for widget in buttons), [
            (widget.text, widget.height) for widget in buttons if widget.height < kivy_app.touch_target - 1
        ]
    finally:
        kivy_app.android_keyboard_height = 0
        modal.dismiss(force=True, animation=False)
        pump_frames(6)
