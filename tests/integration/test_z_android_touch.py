from unittest.mock import Mock, patch

import pytest
from kivy.core.window import Window
from kivy.uix.button import Button
from kivy.uix.modalview import ModalView

from carveracontroller.ui.android_layout import AndroidTouchLayout
from tests.integration.conftest import pump_frames
from tests.unit.test_touch import dispatch, finger, move


def test_slider_owns_one_finger_and_syncs_release_outside(kivy_app):
    from carveracontroller.main import GcodePlaySlider

    slider = GcodePlaySlider(size_hint=(None, None), pos=(0, 0), size=(400, 80), max=1000)
    viewer = Mock()
    root = Mock(gcode_viewer=viewer, gcode_viewer_distance=100)
    Window.add_widget(slider)
    try:
        with patch("carveracontroller.main.App.get_running_app", return_value=Mock(root=root)):
            owner, other = finger(100, 40), finger(200, 40, "2")
            dispatch("begin", owner)
            first = slider.value
            dispatch("begin", other)
            move(other, 350, 40)
            dispatch("update", other)
            dispatch("end", other)
            assert slider.value == first
            move(owner, 500, 40)
            dispatch("end", owner)
            assert slider.value == slider.max
            viewer.set_pos_by_distance.assert_called_with(100)
            assert slider._scrub_touch is None
            slider.cancel_gestures()
    finally:
        slider.cancel_gestures()
        Window.remove_widget(slider)


def test_menu_dismissal_consumes_the_underlying_tap(kivy_app):
    from carveracontroller.main import GCodeLineContextMenu

    button = Button(size_hint=(None, None), size=(100, 100))
    released = Mock()
    button.bind(on_release=released)
    Window.add_widget(button)
    menu = GCodeLineContextMenu(1, size_hint=(None, None), size=(250, 150))
    menu.open(animation=False)
    try:
        motion = finger()
        dispatch("begin", motion)
        dispatch("end", motion)
        released.assert_not_called()
        pump_frames(3, sleep=0.05)
        assert not menu._is_open
    finally:
        menu.dismiss(force=True, animation=False)
        Window.remove_widget(button)


def test_viewer_contacts_rebase_without_a_jump(kivy_app, monkeypatch):
    viewer = kivy_app.root.gcode_viewer
    monkeypatch.setattr(viewer, "_view_cube_active", lambda: False)
    monkeypatch.setattr(viewer, "collide_point", lambda *_: True)
    first, second = finger(100, 100), finger(200, 100, "2")
    original = (viewer.m_xRot, viewer.m_yRot, viewer.m_xPan, viewer.m_yPan, viewer.m_zoom)
    try:
        viewer.dispatch("on_touch_down", first)
        viewer.dispatch("on_touch_down", second)
        viewer.dispatch("on_touch_move", second)
        assert (viewer.m_xRot, viewer.m_yRot, viewer.m_xPan, viewer.m_yPan, viewer.m_zoom) == original
        move(second, 220, 100)
        viewer.dispatch("on_touch_move", second)
        changed = (viewer.m_xRot, viewer.m_yRot, viewer.m_xPan, viewer.m_yPan, viewer.m_zoom)
        assert changed != original
        viewer.dispatch("on_touch_up", first)
        viewer.dispatch("on_touch_move", second)
        assert (viewer.m_xRot, viewer.m_yRot, viewer.m_xPan, viewer.m_yPan, viewer.m_zoom) == changed
        move(second, Window.width + 20, Window.height + 20)
        viewer.dispatch("on_touch_up", second)
        assert not viewer._view_gesture.points
    finally:
        viewer.cancel_gestures()
        viewer.m_xRot, viewer.m_yRot, viewer.m_xPan, viewer.m_yPan, viewer.m_zoom = original


def test_sketch_selects_completed_taps_and_offers_overlaps(kivy_app):
    from carveracontroller.addons.cmm_workbench.core.session import CMMWorkbenchFeature
    from carveracontroller.addons.cmm_workbench.ui.sketch import CMMWorkbenchPreviewSketch

    sketch = CMMWorkbenchPreviewSketch(size_hint=(None, None), size=(400, 300))
    first = CMMWorkbenchFeature.new_point("first", 0, 0, 0)
    second = CMMWorkbenchFeature.new_point("second", 0, 0, 0)
    sketch.set_features([first, second])
    selected = Mock()
    sketch.on_feature_tap = selected
    Window.add_widget(sketch)
    try:
        motion = finger(200, 150)
        dispatch("begin", motion)
        selected.assert_not_called()
        dispatch("end", motion)
        pump_frames(6, sleep=.03)
        chooser = next(child for child in Window.children if isinstance(child, ModalView))
        choice = next(widget for widget in chooser.walk() if isinstance(widget, Button) and widget.text == "second")
        choice.dispatch("on_release")
        selected.assert_called_once_with(second.id)
        chooser.dismiss(force=True, animation=False)
        sketch.zoom(1.25)
        pump_frames(2)
        assert sketch._view_zoom == 1.25
        assert len(sketch._zoom_controls.children) == 3
        sketch.fit_view()
        assert sketch._view_zoom == 1
    finally:
        sketch.cancel_gestures()
        sketch._redraw_trigger.cancel()
        Window.remove_widget(sketch)


def test_numeric_setting_keeps_an_invalid_draft_open(kivy_app, tmp_path):
    from kivy.config import ConfigParser
    from kivy.uix.settings import SettingsPanel
    from carveracontroller.ui.settings_fields import EditingSettingNumeric

    config = ConfigParser()
    config.filename = str(tmp_path / "numeric.ini")
    config.add_section("example")
    config.set("example", "value", "1.0")
    panel = SettingsPanel(config=config)
    setting = EditingSettingNumeric(panel=panel, section="example", key="value")
    setting._create_popup(None)
    popup = setting.popup
    try:
        setting.textinput.text = "-."
        setting._validate(None)
        assert setting.value == "1.0"
        assert setting.popup is popup
        assert setting.textinput.validation_error
        setting.textinput.text = "-1.5"
        setting._validate(None)
        assert setting.value == "-1.5"
        assert setting.popup is None
    finally:
        popup.dismiss(force=True, animation=False)


@pytest.mark.parametrize("which", ["config", "position", "probing", "facing", "cmm", "files"])
def test_android_forms_remain_above_keyboard(kivy_app, which):
    app, root = kivy_app, kivy_app.root
    original_target = app.touch_target
    app.android_touch = True
    app.touch_target = 72
    layout = AndroidTouchLayout(app)
    app._touch_layout = layout
    modal = None
    try:
        if which == "config":
            modal = root.config_popup
        elif which == "position":
            modal = root.coord_popup.setx_popup
        elif which == "probing":
            from carveracontroller.addons.probing.ProbingPopup import ProbingPopup
            modal = ProbingPopup(root.controller)
        elif which == "facing":
            from carveracontroller.addons.facing.FacingWizardPopup import FacingWizardPopup
            modal = FacingWizardPopup()
        elif which == "cmm":
            modal = root._ensure_cmm_workbench_popup()
        else:
            modal = root.file_popup
        modal.open(animation=False)
        pump_frames(8, sleep=0.04)
        if which == "probing":
            for name in ("step_xy", "step_a", "step_z"):
                selector = modal.ids[name]
                assert selector.height >= 72
                assert selector.y >= selector.parent.y
                assert selector.top <= selector.parent.top + 1
            assert modal.ids.step_a.center_y == pytest.approx(modal.ids.step_z.center_y)
        app.android_keyboard_height = 420
        pump_frames(8, sleep=0.04)
        assert modal.y >= 420
        assert modal.top <= Window.height + 1
        if which == "probing":
            assert modal.ids.jog_panel.height == 0
            assert modal.ids.jog_panel.disabled
        buttons = [widget for widget in modal.walk() if isinstance(widget, Button) and widget.opacity and widget.width]
        assert buttons
        assert all(widget.size_hint_min_y >= 72 for widget in buttons)
        if which == "position":
            button = modal.ids.btn_ok
            assert button.to_window(*button.pos)[1] >= 420
        app.android_keyboard_height = 0
        pump_frames(4)
    finally:
        if modal is not None:
            modal.dismiss(force=True, animation=False)
        for child in list(Window.children):
            if isinstance(child, ModalView):
                child.dismiss(force=True, animation=False)
        app.android_keyboard_height = 0
        layout.stop()
        app._touch_layout = None
        app.android_touch = False
        app.touch_target = original_target
        root.size_hint = (1, 1)
        root.pos = (0, 0)
        root.size = Window.size
