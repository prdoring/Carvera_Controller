import gc
import weakref
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from kivy.base import EventLoop
from kivy.config import Config
from kivy.core.window import Window
from kivy.graphics import Callback
from kivy.tests.common import UnitTestTouch
from kivy.uix.button import Button

from carveracontroller import runtime_profile
from carveracontroller.ui.screensaver import ScreensaverCanvas
from carveracontroller.ui.screensaver_patterns import ROTATION_SECONDS, STYLES
from tests.integration.conftest import pump_frames, set_window_size


@pytest.fixture
def saver(kivy_app):
    manager = kivy_app._screensaver
    manager.hide()
    clock = [100.0]
    original = manager.now
    manager.now = lambda: clock[0]
    manager.last_activity = clock[0]
    manager._was_blocked = False
    manager._focused = True
    manager._swallowed.clear()
    manager._keys.clear()
    manager._keyboard_tail = 0
    keys = ("screensaver_timeout_minutes", "screensaver_style", "screensaver_show_clock")
    saved = {key: Config.get("carvera", key) for key in keys}
    for key, value in zip(keys, ("30", "random", "1")):
        Config.set("carvera", key, value)
    try:
        yield manager, clock
    finally:
        manager.hide()
        manager.now = original
        manager.last_activity = original()
        for key, value in saved.items():
            Config.set("carvera", key, value)


def test_timeout_rotation_and_off(saver):
    manager, clock = saver
    with patch.object(manager, "blocked", return_value=False):
        clock[0] += 1799
        manager.check(0)
        assert not manager.visible
        clock[0] += 1
        manager.check(0)
        assert manager.visible
        seen = [manager.current_style]
        for _ in range(5):
            clock[0] += ROTATION_SECONDS
            manager.check(0)
            seen.append(manager.current_style)
        assert set(seen) == set(STYLES)
        Config.set("carvera", "screensaver_timeout_minutes", "0")
        manager.check(0)
        assert not manager.visible
        assert manager._animation is None


def test_blockers_and_sleep(saver):
    manager, clock = saver
    status = {"flags": {"playing": False}, "connected": True, "state": "Sleep"}
    with (
        patch("carveracontroller.ui.screensaver.activity", return_value=status),
        patch.object(runtime_profile, "maintenance_active", False),
    ):
        assert not manager.blocked()
        for state in ("Idle", "Alarm"):
            status["state"] = state
            assert not manager.blocked()
        for state in ("Run", "Hold", "Home", "Tool", "Unknown"):
            status["state"] = state
            assert manager.blocked()
        status["state"] = "Sleep"
        for flag in ("playing", "jogging", "probing", "sending", "connecting", "transport", "settings"):
            status["flags"] = {flag: True}
            assert manager.blocked()
        status["flags"] = {}
        with patch.object(runtime_profile, "maintenance_active", True):
            assert manager.blocked()
    with patch.object(manager, "blocked", return_value=True):
        clock[0] += 4000
        manager.check(0)
        assert not manager.visible
    with patch.object(manager, "blocked", return_value=False):
        manager.check(0)
        assert not manager.visible
        clock[0] += 1800
        manager.check(0)
        assert manager.visible


def test_waking_fingers_and_keyboard_do_not_pass_through(saver):
    manager, _ = saver
    with patch.object(manager, "blocked", return_value=False):
        assert manager.show("clock", True)
        a = SimpleNamespace(uid="a", is_touch=True)
        b = SimpleNamespace(uid="b", is_touch=True)
        assert manager.process([("begin", a), ("begin", b)]) == []
        assert not manager.visible
        assert manager.process([("update", a), ("end", a)]) == []
        assert manager.process([("end", b)]) == []
        assert manager.process([("begin", a)]) == [("begin", a)]
        assert manager.show("clock", True)
        assert Window.dispatch("on_key_down", 13, 0, "\r", [])
        assert not manager.visible
        assert Window.dispatch("on_textinput", "\r")
        assert Window.dispatch("on_key_up", 13, 0)


def test_preview_uses_drafts_without_saving_and_preserves_dialog(saver):
    manager, _ = saver
    app = manager.app
    app.root._ensure_controller_settings_panels()
    popup = app.root.config_popup
    popup.open()
    pump_frames(5)
    items = {item.key: item for item in popup._all_setting_items() if item.key.startswith("screensaver_")}
    try:
        items["screensaver_style"].value = "contours"
        items["screensaver_show_clock"].value = "0"
        before = len(app.simulation.commands)
        with patch.object(manager, "blocked", return_value=False):
            items["screensaver_preview"].preview()
        assert manager.visible and manager.current_style == "contours"
        assert not manager.overlay.show_clock
        assert Config.get("carvera", "screensaver_style") == "random"
        assert len(app.simulation.commands) == before
        manager.hide()
        assert popup.parent is not None
        assert items["screensaver_style"].value == "contours"
    finally:
        popup._discard_and_close()


@pytest.mark.parametrize("style", STYLES)
def test_renderers_resize_and_complete_cycles(kivy_app, style):
    view = ScreensaverCanvas(style, True, size=(1920, 1200))
    try:
        assert view.background.size == (1920, 1200)
        for _ in range(70):
            view.advance(0.5)
        assert view.cycle == 1
        view.size = (1920, 1080)
        view.advance(0.5)
        assert view.background.size == (1920, 1080)
        assert view.x <= view.clock.x and view.clock.right <= view.right
        assert view.y <= view.clock.y and view.clock.top <= view.top
    finally:
        view.clear_widgets()


def test_overlay_stays_above_new_dialog_and_shutdown_cleans_callbacks(saver):
    manager, _ = saver
    with patch.object(manager, "blocked", return_value=False):
        assert manager.preview({"screensaver_style": "toolpath"})
    dialog = Button(text="underneath")
    Window.add_widget(dialog)
    try:
        pump_frames(2)
        assert Window.children[0] == manager.overlay
        manager.hide()
        assert dialog.parent is Window
        assert manager._animation is None
    finally:
        Window.remove_widget(dialog)


def test_capture_native_screens(kivy_app, saver, tmp_path):
    manager, clock = saver
    original = Window.size
    try:
        set_window_size((1920, 1200))
        for style in STYLES:
            with patch.object(manager, "blocked", return_value=False):
                manager.preview({"screensaver_style": style})
                clock[0] += 1
                manager.overlay.advance(8)
                pump_frames(6)
                assert manager.visible
                Window.screenshot(name=str(tmp_path / f"screensaver-{style}.png"))
            manager.hide()
    finally:
        set_window_size(original)


def test_real_touch_dispatch_does_not_press_button_beneath_overlay(saver):
    manager, _ = saver
    pressed = []
    button = Button(size_hint=(None, None), size=(300, 200), pos=(100, 100))
    button.bind(on_release=lambda *_: pressed.append(True))
    Window.add_widget(button)
    before = len(manager.app.simulation.commands)

    def dispatch(kind, touch):
        events = [(kind, touch)]
        for processor in EventLoop.postproc_modules:
            events = processor.process(events=events)
        for event in events:
            EventLoop.post_dispatch_input(*event)

    try:
        with patch.object(manager, "blocked", return_value=False):
            assert manager.preview({"screensaver_style": "clock"})
        touch = UnitTestTouch(200, 150)
        dispatch("begin", touch)
        assert not manager.visible
        touch.touch_up()
        dispatch("end", touch)
        assert pressed == []
        assert len(manager.app.simulation.commands) == before
        fresh = UnitTestTouch(200, 150)
        dispatch("begin", fresh)
        fresh.touch_up()
        dispatch("end", fresh)
        assert pressed == [True]
    finally:
        Window.remove_widget(button)


def test_new_alarm_and_focus_loss_reveal_underlying_screen(saver):
    from carveracontroller.CNC import CNC

    manager, clock = saver
    app = manager.app
    state = app.state
    reason = CNC.vars.get("halt_reason")
    try:
        with patch.object(manager, "blocked", return_value=False):
            app.state = "Sleep"
            assert manager.preview({"screensaver_style": "clock"})
            manager.check(0)
            assert manager.visible
            app.state = "Alarm"
            manager.check(0)
            assert not manager.visible
            clock[0] += 1800
            manager.check(0)
            assert manager.visible
            CNC.vars["halt_reason"] = 999
            manager.check(0)
            assert not manager.visible
            assert manager.preview({"screensaver_style": "clock"})
            manager._focus(Window, False)
            assert not manager.visible
        assert manager.blocked()
    finally:
        app.state = state
        CNC.vars["halt_reason"] = reason
        manager._focus(Window, True)


def test_apply_saves_pending_selection_and_clock(saver):
    manager, _ = saver
    app = manager.app
    app.root._ensure_controller_settings_panels()
    popup = app.root.config_popup
    popup.open()
    pump_frames(3)
    items = {item.key: item for item in popup._all_setting_items() if item.key.startswith("screensaver_")}
    try:
        items["screensaver_style"].value = "parts"
        items["screensaver_timeout_minutes"].value = "5"
        items["screensaver_show_clock"].value = "0"
        popup._apply_changes()
        assert manager.settings() == (5, "parts", False)
    finally:
        popup.dismiss(force=True)


@pytest.mark.parametrize("style", ("toolpath", "contours", "block", "orbits"))
def test_completed_paths_are_cached_during_tracing(kivy_app, style):
    view = ScreensaverCanvas(style, False, size=(1920, 1200))
    view.advance(4)
    gray = [list(pair[0].points) for pair in view._lines]
    with patch.object(view, "_pixels", wraps=view._pixels) as conversions:
        for _ in range(20):
            view.advance(0.05)
        assert conversions.call_count <= 20
    assert [list(pair[0].points) for pair in view._lines] == gray
    view.size = (960, 600)
    view.advance(0)
    assert [list(pair[0].points) for pair in view._lines] == [[value / 2 for value in path] for path in gray]


def test_parts_move_without_rebuilding_vertices(kivy_app):
    view = ScreensaverCanvas("parts", False, size=(1920, 1200))
    geometry = [list(line.points) for line in view._part_lines]
    initial_position = tuple(view._part_transforms[0][0].xy)
    with patch.object(view, "_new_pattern", wraps=view._new_pattern) as patterns:
        for _ in range(700):
            view.advance(0.05)
        patterns.assert_not_called()
    assert [list(line.points) for line in view._part_lines] == geometry
    assert tuple(view._part_transforms[0][0].xy) != initial_position
    assert view._part_transforms[0][1].angle != 0


def test_clock_reads_are_throttled_and_hidden_clock_does_no_work(kivy_app):
    with patch("carveracontroller.ui.screensaver.datetime") as wall_clock:
        wall_clock.now.return_value = datetime(2026, 11, 4, 12, 30)
        view = ScreensaverCanvas("contours", True)
        for _ in range(600):
            view.advance(0.05)
        assert wall_clock.now.call_count <= 31
        wall_clock.now.reset_mock()
        hidden = ScreensaverCanvas("contours", False)
        for _ in range(50):
            hidden.advance(0.05)
        wall_clock.now.assert_not_called()


def test_clock_uses_slow_callbacks_between_fades_and_stops_when_hidden(saver):
    manager, clock = saver
    with patch.object(manager, "blocked", return_value=False):
        assert manager.preview({"screensaver_style": "clock"})
        clock[0] += 1
        manager._animation.cancel()
        manager._frame(0)
        assert manager._animation.timeout == 1
        clock[0] += 28.6
        manager._animation.cancel()
        manager._frame(0)
        assert manager._animation.timeout == 0.05
        manager.hide()
        assert manager._animation is None
    events = []
    assert manager.process(events) is events


def test_rotation_releases_old_renderers(saver):
    manager, _ = saver
    references = []
    with patch.object(manager, "blocked", return_value=False):
        for style in STYLES * 5:
            manager.preview({"screensaver_style": style})
            manager.overlay.advance(5)
            references.append(weakref.ref(manager.overlay))
        manager.hide()
    pump_frames(3)
    gc.collect()
    assert all(reference() is None for reference in references)


def test_covered_controller_drawing_stops_and_restores_without_detaching_widgets(saver):
    manager, _ = saver
    root = manager.app.root
    draws = []
    with root.canvas.after:
        callback = Callback(lambda *_: draws.append(True))
    try:
        Window.dispatch("on_draw")
        assert draws
        draws.clear()
        with patch.object(manager, "blocked", return_value=False):
            assert manager.preview({"screensaver_style": "contours"})
        saved = manager._root_canvas
        assert saved is not None and root.parent is Window
        Window.dispatch("on_draw")
        assert draws == []
        manager.hide()
        Window.dispatch("on_draw")
        assert draws
        assert saved[2].indexof(root.canvas) == saved[3]
    finally:
        manager.hide()
        root.canvas.after.remove(callback)
