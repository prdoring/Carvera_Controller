from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.input.motionevent import MotionEvent
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.widget import Widget

from carveracontroller.ui.touch import (
    TOUCH_CANCELLED, Gesture, JogTouchButton, TapBehavior, TouchPostprocessor, cancel_all_touches,
)


class Finger(MotionEvent):
    def depack(self, args):
        self.sx, self.sy = args
        self.profile = ["pos"]
        super().depack(args)


def finger(x=50, y=50, ident="1"):
    motion = Finger("test", ident, (x / (Window.width - 1), y / (Window.height - 1)), is_touch=True, type_id="touch")
    motion.scale_for_screen(Window.width, Window.height)
    return motion


def move(motion, x, y):
    motion.move((x / (Window.width - 1), y / (Window.height - 1)))
    motion.scale_for_screen(Window.width, Window.height)


@pytest.fixture
def jog():
    controller = SimpleNamespace(
        continuous_jog_active=False, _continuous_jog_stopping=False,
        jog=Mock(), stopContinuousJog=Mock(), stream=object(),
    )
    root = BoxLayout(size_hint=(None, None), size=Window.size)
    root.controller = controller
    root._machine_allows_jogging = lambda: True
    button = JogTouchButton(size_hint=(None, None), size=(100, 100), jog_command="X1")
    root.add_widget(button)
    Window.add_widget(root)
    with patch("carveracontroller.ui.touch.App.get_running_app", return_value=SimpleNamespace(root=root)):
        yield button, controller, root
        cancel_all_touches()
    Window.remove_widget(root)


def dispatch(phase, motion):
    EventLoop.post_dispatch_input(phase, motion)


def test_jog_release_outside_sends_stop(jog):
    button, controller, _ = jog
    motion = finger()
    dispatch("begin", motion)
    assert controller.jog.call_args_list, (button.pos, button.size, motion.pos, button.disabled, Window.children, motion.grab_list)
    controller.jog.assert_called_once_with("X1")
    move(motion, 200, 50)
    dispatch("end", motion)
    controller.stopContinuousJog.assert_called_once()
    assert button.state == "normal"


def test_slide_off_stops_without_rearming(jog):
    _, controller, _ = jog
    motion = finger()
    dispatch("begin", motion)
    move(motion, 200, 50)
    dispatch("update", motion)
    move(motion, 50, 50)
    dispatch("update", motion)
    dispatch("end", motion)
    controller.jog.assert_called_once()
    controller.stopContinuousJog.assert_called_once()


def test_other_finger_cannot_release_or_replace_jog(jog):
    _, controller, _ = jog
    owner, other = finger(), finger(60, 60, "2")
    dispatch("begin", owner)
    dispatch("begin", other)
    dispatch("end", other)
    controller.stopContinuousJog.assert_not_called()
    controller.jog.assert_called_once()
    dispatch("end", owner)
    controller.stopContinuousJog.assert_called_once()


@pytest.mark.parametrize("reason", ["disable", "pause", "connection", "popup"])
def test_jog_cancellation(jog, reason):
    button, controller, root = jog
    dispatch("begin", finger())
    if reason == "disable":
        button.disabled = True
    elif reason == "connection":
        controller.stream = None
        button._check_jog(0)
    elif reason == "popup":
        root.remove_widget(button)
    else:
        cancel_all_touches()
    controller.stopContinuousJog.assert_called_once()


def test_stopping_jog_cannot_restart(jog):
    _, controller, _ = jog
    controller._continuous_jog_stopping = True
    dispatch("begin", finger())
    controller.jog.assert_not_called()


def test_drag_away_and_return_never_becomes_tap_or_hold():
    motion = finger()
    callback = Mock()
    gesture = Gesture(motion, callback)
    move(motion, 120, 50)
    gesture.move()
    move(motion, 50, 50)
    gesture._hold(callback)
    assert not gesture.finish()
    callback.assert_not_called()


def test_native_cancellation_does_not_release_button_action():
    button = Button(size_hint=(None, None), size=(100, 100))
    released = Mock()
    button.bind(on_release=released)
    Window.add_widget(button)
    try:
        motion = finger()
        dispatch("begin", motion)
        motion.ud[TOUCH_CANCELLED] = True
        TouchPostprocessor().process([("end", motion)])
        dispatch("end", motion)
        released.assert_not_called()
        assert button.state == "normal"
    finally:
        Window.remove_widget(button)


def test_tap_behavior_dispatches_once_and_drag_dispatches_nothing():
    class TouchTestRow(TapBehavior, Widget):
        on_tap = Mock()

    row = TouchTestRow(size_hint=(None, None), size=(100, 100))
    Window.add_widget(row)
    try:
        motion = finger()
        dispatch("begin", motion)
        dispatch("end", motion)
        row.on_tap.assert_called_once()
        row.on_tap.reset_mock()
        motion = finger(ident="2")
        dispatch("begin", motion)
        move(motion, 180, 50)
        dispatch("update", motion)
        move(motion, 50, 50)
        dispatch("end", motion)
        row.on_tap.assert_not_called()
    finally:
        row.cancel_gestures()
        Window.remove_widget(row)
