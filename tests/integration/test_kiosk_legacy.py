import threading
import time

import pytest

from .conftest import pump_frames, set_window_size


@pytest.fixture
def legacy(mobile, tmp_path, monkeypatch):
    from carveracontroller.translation import tr
    from carveracontroller.ui.kiosk_legacy import LegacySystem
    from carveracontroller.ui.kiosk_system import KioskSystem

    app, _layout = mobile
    previous_language = tr.lang
    if tr.lang != "en":
        tr.switch_lang("en")
    backend = LegacySystem(tmp_path / "runtime", tmp_path / "maintenance")
    monkeypatch.setattr(backend, "guard", lambda _action: None)
    monkeypatch.setattr(backend, "overview", lambda: {"controller": {"updated": time.monotonic(), "state": "Idle"}})
    view = KioskSystem(app, backend)
    view.open(animation=False)
    pump_frames(16, sleep=0.01)
    try:
        yield view, backend
    finally:
        view.dismiss(force=True, animation=False)
        pump_frames(8)
        if tr.lang != previous_language:
            tr.switch_lang(previous_language)


def tap(widget):
    from kivy.tests.common import UnitTestTouch

    touch = UnitTestTouch(*widget.to_window(*widget.center))
    touch.touch_down()
    pump_frames(2)
    touch.touch_up()
    pump_frames(8, sleep=0.01)


def test_legacy_typing_then_first_tap_never_pastes(legacy):
    from kivy.core.clipboard import Clipboard

    view, _backend = legacy
    view.choose("Network")
    view.ssid.text = "Workshop"
    view.ssid.focus = True
    Clipboard.copy("Unexpected clipboard")
    pump_frames(20, sleep=0.01)
    tap(view.hide)
    assert not view.ssid.focus
    assert view.ssid.text == "Workshop"


def test_explicit_paste_and_drag_cancellation(legacy):
    from kivy.core.clipboard import Clipboard
    from kivy.tests.common import UnitTestTouch

    view, _backend = legacy
    view.choose("Network")
    view.ssid.focus = True
    pump_frames(12)
    Clipboard.copy("Workshop")
    tap(view.paste)
    assert view.ssid.text == "Workshop"
    touch = UnitTestTouch(*view.hide.to_window(*view.hide.center))
    touch.touch_down()
    touch.touch_move(touch.x + 100, touch.y)
    touch.touch_up()
    pump_frames(8)
    assert view.ssid.focus


def test_confirmation_cancel_does_not_execute_and_preserves_draft(legacy, monkeypatch):
    view, backend = legacy
    calls = []
    monkeypatch.setattr(backend, "perform", lambda *args, **kwargs: calls.append((args, kwargs)))
    view.choose("Network")
    view.ssid.text, view.password.text = "Workshop", "secret-pass"
    view.confirm("wifi")
    pump_frames(10)
    sheet = view._sheet
    cancel = next(widget for widget in sheet.walk() if getattr(widget, "text", "") == "Cancel")
    tap(cancel)
    assert not calls and view.password.text == "secret-pass"
    view.choose("Overview")
    view.choose("Network")
    assert view.ssid.text == "Workshop" and view.password.text == "secret-pass"


@pytest.mark.parametrize("mode", ["below_target", ""])
def test_system_owns_keyboard_exclusion_and_restores_window_mode(legacy, mode):
    from kivy.core.clipboard import Clipboard
    from kivy.core.window import Window

    view, _backend = legacy
    view.dismiss(animation=False)
    original_mode = Window.softinput_mode
    try:
        Window.softinput_mode = mode
        view.open(animation=False)
        assert Window.softinput_mode == ""
        view.choose("Network")
        view.ssid.focus = True
        pump_frames(12)
        Clipboard.copy("Workshop")
        tap(view.paste)
        assert view.ssid.text == "Workshop"
        view.dismiss(animation=False)
        assert Window.softinput_mode == mode
        view.open(animation=False)
        assert Window.softinput_mode == ""
        view.dismiss(force=True, animation=False)
        assert Window.softinput_mode == mode
    finally:
        view.dismiss(force=True, animation=False)
        Window.softinput_mode = original_mode


def test_duplicate_operations_and_stale_callbacks_are_blocked(legacy, monkeypatch):
    view, backend = legacy
    entered, finish = threading.Event(), threading.Event()
    calls = []

    def perform(action, **kwargs):
        calls.append(action)
        entered.set()
        finish.wait(5)
        return {}

    monkeypatch.setattr(backend, "perform", perform)
    try:
        view.perform("wifi")
        assert entered.wait(2)
        view.perform("wifi")
        assert calls == ["wifi"]
        view.dismiss(force=True, animation=False)
        status = view.status.text
        finish.set()
        pump_frames(15, sleep=0.01)
        assert view.status.text == status
    finally:
        finish.set()


def test_expired_wifi_can_close_without_leaving_maintenance(legacy):
    view, backend = legacy
    backend.wifi_attempted = True
    backend.wifi_started = time.monotonic() - 121
    view.update_controls()
    assert "Maintenance may remain active" in view.notice.text
    view.dismiss(animation=False)
    assert not view._is_open
    assert backend.wifi_attempted


def test_reopening_preserves_uncertain_state_and_drafts(legacy):
    view, backend = legacy
    backend.uncertain = True
    view.ssid.text, view.password.text = "Workshop", "secret-pass"
    view.dismiss(animation=False)
    view.open(animation=False)
    pump_frames(12)
    assert backend.uncertain and "unknown outcome" in view.notice.text
    assert view.ssid.text == "Workshop" and view.password.text == "secret-pass"


@pytest.mark.parametrize("size", [(1920, 1200), (1920, 1080)])
@pytest.mark.parametrize("density", [1.5, 1.875])
def test_legacy_keyboard_keeps_label_field_and_actions_visible(legacy, size, density):
    from pathlib import Path

    from kivy.core.window import Window
    from kivy.metrics import Metrics, dp

    view, _backend = legacy
    previous = Metrics.density
    previous_target = view.app.touch_target
    Metrics.density = density
    view.app.touch_target = dp(48)
    try:
        set_window_size(size)
        view.choose("Network")
        view.password.focus = True
        pump_frames(30, sleep=0.01)
        assert view.password.to_window(*view.password.pos)[1] >= view.app.android_keyboard_height
        assert view.password.to_window(*view.password.pos)[1] >= view.scroll.y - 1
        group = view.password.parent
        assert group.to_window(group.x, group.top)[1] <= view.scroll.top + 1
        assert view.connect.to_window(*view.connect.pos)[1] >= view.app.android_keyboard_height
        for widget in (view.connect, view.paste, view.hide, view.stop):
            assert widget.height >= dp(48)
        output = Path(__file__).parent / "output"
        output.mkdir(exist_ok=True)
        view.export_to_png(str(output / f"legacy-system-{size[1]}-{density}.png"))
        assert view.top <= Window.height + 1
    finally:
        Metrics.density = previous
        view.app.touch_target = previous_target


def test_owned_wifi_view_stays_above_maintenance_with_emergency_stop(legacy):
    from kivy.core.window import Window
    from kivy.uix.modalview import ModalView

    view, backend = legacy
    overlay = ModalView()
    backend.wifi_attempted = True
    view.details = {"controller": {"maintenance": True}}
    overlay.open(animation=False)
    try:
        view.raise_above_maintenance()
        view.update_controls()
        assert Window.children[0] is view
        assert not view.stop.disabled and view.stop.opacity == 1
    finally:
        overlay.dismiss(animation=False)


def test_emergency_stop_remains_available_during_first_pending_request(legacy, monkeypatch):
    from kivy.tests.common import UnitTestTouch

    view, _backend = legacy
    calls = []
    monkeypatch.setattr(view.app.root.controller, "estopCommand", lambda: calls.append("stop"))
    view.details = {"controller": {"maintenance": False}}
    view.busy = True
    view.update_controls()
    assert not view.stop.disabled and view.stop.opacity == 1
    pump_frames(8)
    touch = UnitTestTouch(*view.stop.to_window(*view.stop.center))
    touch.touch_down()
    view.update_controls()
    touch.touch_up()
    pump_frames(8)
    assert calls == ["stop"]
    view.busy = False
