from unittest.mock import Mock, patch

import pytest
from kivy.core.window import Window
from kivy.uix.button import Button
from kivy.uix.modalview import ModalView

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


