"""Exercise the independent System interface without invoking system commands."""

import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from .conftest import pump_frames, set_window_size

pytestmark = pytest.mark.skipif(os.environ.get("CARVERA_PROFILE") != "kiosk", reason="Dedicated recovery run")


@pytest.fixture(scope="module")
def recovery(tmp_path_factory):
    from kivy.base import EventLoop
    from kivy.core.window import Window
    from kivy.metrics import Metrics

    root = Path(__file__).resolve().parents[2]
    patch = pytest.MonkeyPatch()
    patch.chdir(root)
    patch.setenv("CARVERA_DATA_DIR", str(tmp_path_factory.mktemp("recovery")))
    patch.syspath_prepend(str(root / "carveracontroller"))
    patch.syspath_prepend(str(root / "assets/packaging/kiosk/runtime"))
    spec = importlib.util.spec_from_file_location(
        "kiosk_recovery_ui", root / "assets/packaging/kiosk/runtime/recovery.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requests = []

    def call(request):
        requests.append(request)
        if request["action"] == "status":
            return {
                "controller": {"pid": os.getpid(), "state": "Idle", "updated": time.monotonic()},
                "version": "1.0.0",
                "image_version": "1.0.0",
                "previous_version": "0.9.0",
                "addresses": "192.0.2.10",
                "login": "carvera-admin@workshop.local",
                "identity": "256 SHA256:example (ED25519)",
                "display_mode": "1920x1200",
                "temperature": "49.0 °C",
                "memory": "2200 MiB available / 3800 MiB",
                "storage": "8.0 GiB free / 16.0 GiB",
            }
        if request["action"] == "scan":
            return {"networks": [{"ssid": "Workshop", "signal": 90, "security": "WPA2", "supported": True}]}
        if request["action"] == "display-modes":
            return {"modes": ["1920x1200", "1920x1080"]}
        if request["action"] == "inspect":
            return {"name": request["value"], "bytes": 100, "kind": "preferences", "sha256": "0" * 64}
        if request["action"] == "leave":
            return {"maintenance": False, "controller_available": True}
        return {"message": "Completed."}

    patch.setattr(module, "call_helper", call)
    Metrics.density = 1.5
    app = module.Recovery()
    app._run_prepare()
    pump_frames(12, sleep=0.01)
    app.poll.cancel()
    try:
        yield app, requests, module
    finally:
        app.stop()
        EventLoop.close()
        patch.undo()


def tap(widget):
    from kivy.base import EventLoop
    from kivy.core.window import Window
    from kivy.tests.common import UnitTestTouch

    x, y = widget.to_window(*widget.center)
    touch = UnitTestTouch(x, y)
    touch.touch_down()
    pump_frames(2)
    touch.touch_up()
    pump_frames(8, sleep=0.01)
    return touch


def test_system_boots_without_controller_application(recovery):
    app, requests, _module = recovery
    assert "carveracontroller.main" not in sys.modules
    assert "carveracontroller.Controller" not in sys.modules
    assert app.section == "Overview"
    assert "1.0.0" in app.overview.text
    assert requests and all(item["action"] == "status" for item in requests)


@pytest.mark.parametrize("size", [(1920, 1200), (1920, 1080)])
def test_button_after_typing_acts_once_without_inserting_text(recovery, size):
    from kivy.core.clipboard import Clipboard
    from kivy.core.window import Window
    from kivy.uix.vkeyboard import VKeyboard

    app, requests, _module = recovery
    set_window_size(size)
    app.choose("Network")
    pump_frames(8)
    app.ssid.focus = True
    app.ssid.text = "Workshop"
    Clipboard.copy("UNEXPECTED PASTE")
    pump_frames(16, sleep=0.02)
    keyboard = next(child for child in Window.children if isinstance(child, VKeyboard))
    assert keyboard.scale == 1
    assert max(pos[0] + size[0] for pos, size in keyboard.layout_geometry["LINE_1"]) >= Window.width * 0.9
    assert app.ssid.to_window(*app.ssid.pos)[1] >= keyboard.top
    refresh = next(widget for widget in app.controls if widget.text == "Find Wi-Fi networks")
    app.scroll.scroll_y = 1
    pump_frames(6)
    app.scroll.update_from_scroll()
    assert app.scroll.y <= refresh.to_window(*refresh.center)[1] <= app.scroll.top
    before = len([request for request in requests if request["action"] == "scan"])
    tap(refresh)
    assert app.ssid.text == "Workshop"
    assert len([request for request in requests if request["action"] == "scan"]) == before + 1
    assert not app.ssid.focus
    assert not any(isinstance(child, VKeyboard) for child in Window.children)


def test_middle_click_does_not_paste_but_explicit_paste_does(recovery):
    from kivy.core.clipboard import Clipboard
    from kivy.tests.common import UnitTestTouch

    app, _requests, _module = recovery
    app.choose("Network")
    pump_frames(8)
    app.ssid.focus = True
    app.ssid.text = ""
    pump_frames(12)
    Clipboard.copy("Intentional paste")
    touch = UnitTestTouch(*app.ssid.to_window(*app.ssid.center))
    touch.profile.append("button")
    touch.button = "middle"
    app.ssid.on_touch_down(touch)
    assert app.ssid.text == ""
    from system_ui import paste_into

    paste_into(app.ssid)
    assert app.ssid.text == "Intentional paste"
    app.dismiss_keyboard()


def test_touch_keyboard_types_deletes_and_dismisses_without_submitting(recovery):
    from kivy.core.window import Window
    from kivy.tests.common import UnitTestTouch
    from kivy.uix.vkeyboard import VKeyboard

    app, requests, _module = recovery
    app.choose("Network")
    app.ssid.text = ""
    app.ssid.focus = True
    pump_frames(16)
    keyboard = next(child for child in Window.children if isinstance(child, VKeyboard))

    def key(name):
        layout = keyboard.available_layouts[keyboard.layout]
        for row in range(1, layout["rows"] + 1):
            for index, entry in enumerate(layout[f"normal_{row}"]):
                if entry[2] == name:
                    pos, size = keyboard.layout_geometry[f"LINE_{row}"][index]
                    x, y = keyboard.to_window(pos[0] + size[0] / 2, pos[1] + size[1] / 2)
                    touch = UnitTestTouch(x, y)
                    touch.touch_down()
                    pump_frames(2)
                    touch.touch_up()
                    pump_frames(4)
                    return
        pytest.fail(f"Key {name} is missing")

    key("q")
    key("w")
    assert app.ssid.text == "qw"
    key("backspace")
    assert app.ssid.text == "q"
    before = len(requests)
    key("enter")
    assert not app.ssid.focus
    assert len(requests) == before


def test_native_finger_after_editing_reaches_action_once(recovery):
    import ctypes

    from kivy.core.window import Window

    class Finger(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_uint32),
            ("timestamp", ctypes.c_uint32),
            ("touch_id", ctypes.c_int64),
            ("finger_id", ctypes.c_int64),
            ("x", ctypes.c_float),
            ("y", ctypes.c_float),
            ("dx", ctypes.c_float),
            ("dy", ctypes.c_float),
            ("pressure", ctypes.c_float),
            ("window_id", ctypes.c_uint32),
        ]

    class Event(ctypes.Union):
        _fields_ = [("finger", Finger), ("padding", ctypes.c_uint8 * 56)]

    app, requests, _module = recovery
    app.choose("Network")
    pump_frames(8)
    app.ssid.focus = True
    app.ssid.text = "Native touch"
    pump_frames(12)
    target = next(widget for widget in app.controls if widget.text == "Find Wi-Fi networks")
    app.scroll.scroll_y = 1
    pump_frames(8)
    app.scroll.update_from_scroll()
    assert app.scroll.y <= target.to_window(*target.center)[1] <= app.scroll.top
    x, y = target.to_window(*target.center)
    before = len([request for request in requests if request["action"] == "scan"])
    sdl = ctypes.CDLL("libSDL2-2.0.so.0")
    sdl.SDL_PushEvent.argtypes = [ctypes.POINTER(Event)]
    sdl.SDL_PushEvent.restype = ctypes.c_int
    for kind in (0x700, 0x701):
        event = Event()
        event.finger = Finger(kind, 0, 1, 801, x / Window.width, 1 - y / Window.height, 0, 0, 1, 0)
        assert sdl.SDL_PushEvent(ctypes.byref(event)) == 1
        Window.mainloop()
        pump_frames(6, sleep=0.02)
    pump_frames(15, sleep=0.02)
    assert app.ssid.text == "Native touch"
    assert len([request for request in requests if request["action"] == "scan"]) == before + 1


def test_pending_confirmation_is_visible_from_every_section(recovery, monkeypatch):
    from kivy.metrics import dp

    app, _requests, module = recovery
    monkeypatch.setattr(app, "request", lambda *_args, **_kwargs: None)
    saved = dict(app.details)
    try:
        app.details["network"] = {"expires": time.monotonic() + 90, "remaining": 90}
        for section in module.SECTIONS:
            app.choose(section)
            pump_frames(8)
            assert app.trial_actions.height >= dp(48)
            assert not app.trial_actions.disabled
            assert app.trial_kind == "wifi"
            assert app.trial_keep.to_window(*app.trial_keep.pos)[1] >= 0
    finally:
        app.details = saved
        app.update_controls()


def test_confirmation_error_and_keyboard_render_without_clipped_actions(recovery):
    from kivy.core.window import Window
    from kivy.metrics import dp

    app, _requests, _module = recovery
    output = Path(__file__).parent / "output"
    output.mkdir(exist_ok=True)
    app.choose("Power")
    app.confirm("shutdown")
    pump_frames(12)
    app.sheet.export_to_png(str(output / "system-confirm.png"))
    actions = app.sheet.content.children[0]
    assert actions.height >= dp(48)
    assert actions.to_window(*actions.pos)[1] > 0
    app.sheet.dismiss()
    pump_frames(8)
    app.show_error("The network is unavailable. Check the connection and try again.")
    pump_frames(12)
    app.error_sheet.export_to_png(str(output / "system-error.png"))
    app.error_sheet.dismiss()
    pump_frames(8)
    app.choose("Network")
    app.password.focus = True
    pump_frames(16)
    Window.screenshot(name=str(output / "system-keyboard.png"))
    app.dismiss_keyboard()


@pytest.mark.parametrize("preferences", ["[carvera]\nandroid_ui_scale=1.25\nlanguage=en\n", "invalid preferences"])
@pytest.mark.parametrize("size", [(1920, 1200), (1920, 1080)])
def test_packaged_system_starts_without_an_application_release(tmp_path, preferences, size):
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[2]
    base = tmp_path / "opt/carvera"
    maintenance = base / "maintenance"
    maintenance.mkdir(parents=True)
    for name in ("recovery.py", "system_ui.py", "admin_accounts.py"):
        shutil.copy2(root / "assets/packaging/kiosk/runtime" / name, maintenance / name)
    for name in ("runtime_profile.py", "kiosk_touch.py"):
        shutil.copy2(root / "carveracontroller" / name, maintenance / name)
    package = base / "system-ui/carveracontroller"
    (package / "ui").mkdir(parents=True)
    for relative in ("ui/theme.py", "ui/controls.kv", "translation.py", "ARIALUNI.ttf"):
        shutil.copy2(root / "carveracontroller" / relative, package / relative)
    for relative in ("data/fonts", "data/theme", "locales"):
        shutil.copytree(root / "carveracontroller" / relative, package / relative)
    (package / "__init__.py").touch()
    (package / "ui/__init__.py").touch()
    (tmp_path / "data/.kivy").mkdir(parents=True)
    (tmp_path / "data/.kivy/config.ini").write_text(preferences)
    code = """
import sys
sys.path.insert(0, sys.argv[1])
import recovery
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.vkeyboard import VKeyboard
recovery.call_helper = lambda request: {}
app = recovery.Recovery()
try:
    app._run_prepare()
    Window.fullscreen = False
    for i in range(6):
        EventLoop.idle()
        Clock.tick()
    Window.size = int(sys.argv[2]), int(sys.argv[3])
    for i in range(20):
        EventLoop.idle()
        Clock.tick()
    import carveracontroller.ui.theme as theme
    assert 'system-ui' in str(theme.__file__)
    assert 'carveracontroller.main' not in sys.modules
    assert 'carveracontroller.Controller' not in sys.modules
    assert app.return_button.font_name == 'PlexSans'
    assert tuple(Window.size) == (int(sys.argv[2]), int(sys.argv[3]))
    app.choose('Network')
    app.password.focus = True
    for i in range(30):
        EventLoop.idle()
        Clock.tick()
    keyboard = next(child for child in Window.children if isinstance(child, VKeyboard))
    assert app.password.to_window(*app.password.pos)[1] >= keyboard.top
    label = next(widget for widget in app.password.parent.children if getattr(widget, 'text', '') == 'Wi-Fi password')
    assert label.to_window(*label.pos)[1] >= app.scroll.y
    assert label.to_window(label.x, label.top)[1] <= app.scroll.top
    assert app.keyboard_connect.height >= dp(48)
    assert app.keyboard_connect.to_window(*app.keyboard_connect.pos)[1] >= keyboard.top
finally:
    app.stop()
    Window.close()
"""
    environment = dict(
        os.environ, PYTHONPATH="", CARVERA_DATA_DIR=str(tmp_path / "data"), KIVY_HOME=str(tmp_path / "kivy")
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(maintenance), str(size[0]), str(size[1])],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr[-3000:]


def test_dragging_off_action_never_executes(recovery):
    from kivy.tests.common import UnitTestTouch

    app, requests, _module = recovery
    app.choose("Overview")
    pump_frames(8)
    target = app.controls[0]
    touch = UnitTestTouch(*target.to_window(*target.center))
    before = len(requests)
    touch.touch_down()
    pump_frames(2)
    touch.touch_move(touch.x + 100, touch.y)
    pump_frames(2)
    touch.touch_move(*target.to_window(*target.center))
    pump_frames(2)
    touch.touch_up()
    pump_frames(8)
    assert len(requests) == before


def test_confirmation_can_cancel_without_operation(recovery):
    app, requests, _module = recovery
    app.choose("Power")
    pump_frames(8)
    tap(app.controls[0])
    assert app.sheet is not None
    assert not any(request["action"] == "restart" for request in requests)
    app.sheet.dismiss()
    pump_frames(8)
    assert app.sheet is None


def test_network_draft_survives_navigation(recovery):
    app, _requests, _module = recovery
    app.choose("Network")
    app.ssid.text, app.password.text = "Unsent network", "Unsent password"
    app.choose("Overview")
    app.choose("Network")
    assert app.ssid.text == "Unsent network"
    assert app.password.text == "Unsent password"
    assert app.password.password


def test_return_uses_fresh_backend_state_instead_of_a_stale_screen_snapshot(recovery, monkeypatch):
    app, requests, _module = recovery
    app.choose("Overview")
    app.details = {"controller": {"pid": os.getpid(), "updated": 0}}
    stopped = []
    monkeypatch.setattr(app, "stop", lambda: stopped.append(True))
    before = len(requests)
    tap(app.return_button)
    assert stopped == [True]
    assert sum(request["action"] == "leave" for request in requests[before:]) == 1


def test_staged_file_review_precedes_any_restore(recovery):
    app, requests, _module = recovery
    app.choose("Maintenance")
    app.show_files({"files": [{"name": "preferences.tar.gz", "kind": "preferences", "bytes": 100}]})
    pump_frames(8)
    target = next(widget for widget in app.controls if widget.text == "Review preferences")
    app.scroll.scroll_to(target, animate=False)
    pump_frames(8)
    before = len([request for request in requests if request["action"] == "restore"])
    tap(target)
    assert app.sheet is not None
    assert any("SHA256:" in getattr(widget, "text", "") for widget in app.sheet.content.walk())
    assert len([request for request in requests if request["action"] == "restore"]) == before
    app.sheet.dismiss()
    pump_frames(8)


def test_duplicate_operations_are_not_queued(recovery, monkeypatch):
    import threading

    app, requests, module = recovery
    started, release = threading.Event(), threading.Event()

    def call(request):
        if request["action"] == "logs":
            requests.append(request)
            started.set()
            release.wait(5)
        return {}

    monkeypatch.setattr(module, "call_helper", call)
    try:
        app.request("logs")
        assert started.wait(2)
        app.request("logs")
        assert app.busy
        assert len([request for request in requests if request["action"] == "logs"]) == 1
    finally:
        release.set()
        pump_frames(12, sleep=0.02)
        monkeypatch.undo()
        app.refresh()
        pump_frames(12, sleep=0.02)


@pytest.mark.parametrize("size", [(1920, 1200), (1920, 1080)])
@pytest.mark.parametrize("fontscale", [1, 1.25])
def test_sections_have_reachable_touch_controls_and_capture_layout(recovery, size, fontscale):
    from kivy.core.window import Window
    from kivy.metrics import Metrics, dp

    app, _requests, module = recovery
    set_window_size(size)
    Metrics.fontscale = fontscale
    output = Path(__file__).parent / "output"
    output.mkdir(exist_ok=True)
    try:
        for section in module.SECTIONS:
            app.choose(section)
            pump_frames(12)
            assert app.shell.top <= Window.height + 1
            assert app.return_button.height >= dp(48)
            for widget in app.controls:
                assert widget.height >= dp(48)
                assert widget.width > dp(200)
            Window.canvas.ask_update()
            pump_frames(4)
            app.root.export_to_png(str(output / f"system-{section.lower()}-{size[1]}-{fontscale}.png"))
    finally:
        Metrics.fontscale = 1
