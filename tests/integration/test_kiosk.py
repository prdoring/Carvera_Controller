"""Linux kiosk checks with simulated machine hardware."""

import os
import sys

import pytest

from .conftest import pump_frames

pytestmark = pytest.mark.skipif(os.environ.get("CARVERA_PROFILE") != "kiosk", reason="Dedicated kiosk run")


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
