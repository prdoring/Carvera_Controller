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
    TOUCH_CANCELLED,
    Gesture,
    JogTouchButton,
    PointerTransform,
    TapBehavior,
    TouchCheckBox,
    TouchPostprocessor,
    cancel_all_touches,
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
    from carveracontroller.Controller import Controller

    controller = SimpleNamespace(
        jog_mode=Controller.JOG_MODE_CONTINUOUS,
        JOG_MODE_CONTINUOUS=Controller.JOG_MODE_CONTINUOUS,
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


def test_step_tap_is_not_blocked_by_an_old_continuous_stop(jog):
    from carveracontroller.Controller import Controller

    _, controller, _ = jog
    controller.jog_mode = Controller.JOG_MODE_STEP
    controller.continuous_jog_active = controller._continuous_jog_stopping = True
    motion = finger()
    dispatch('begin', motion)
    dispatch('end', motion)
    controller.jog.assert_called_once_with('X1')


def test_lost_release_does_not_keep_owning_the_jog_buttons(jog):
    button, controller, _ = jog
    motion = finger()
    dispatch("begin", motion)
    EventLoop.touches.remove(motion)
    button._check_jog(0)
    controller.stopContinuousJog.assert_called_once()
    assert button._jog_touch is None
    fresh = finger(ident="fresh")
    dispatch("begin", fresh)
    dispatch("end", fresh)
    assert controller.jog.call_count == 2


def test_probe_automation_releases_an_unacknowledged_jog_stop(jog, monkeypatch):
    from queue import Queue

    from carveracontroller.CNC import CNC
    from carveracontroller.Controller import Controller

    monkeypatch.setattr(CNC, 'vars', dict(CNC.vars))
    _, _, root = jog
    controller = Controller.__new__(Controller)
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 300
    controller.is_community_firmware = True
    controller.continuous_jog_active = False
    controller._continuous_jog_stopping = False
    controller.stream = object()
    controller.log = Queue()
    controller.status_revision = 0
    controller.executeCommand = Mock()
    controller.executeRealtime = Mock()
    root.controller = controller
    controller.startContinuousJog("Y10")
    controller.stopContinuousJog()
    controller.setJogMode(Controller.JOG_MODE_STEP)
    controller.parseLine("ok")  # Firmware's quick-release abort has no ^Y.
    assert controller._continuous_jog_stopping
    controller.parseLine("<Idle|MPos:0,0,0|WPos:0,0,0|A:0>")
    assert controller._continuous_jog_stopping  # An Idle poll alone is not a stop acknowledgement.
    controller.parseLine("<Run|MPos:0,0,0|WPos:0,0,0|A:1>")
    controller.parseLine("Done ATC")
    controller.parseLine("<Idle|MPos:0,0,0|WPos:0,0,0|A:0>")
    assert not controller.continuous_jog_active
    fresh = finger(ident="after-probe")
    dispatch("begin", fresh)
    dispatch("end", fresh)
    assert controller.executeCommand.call_args_list[-1].args == ("$J X1 F300",)


def test_jog_stop_acknowledgement_is_not_swallowed_by_a_directory_load():
    from queue import Queue

    from carveracontroller.Controller import Controller
    from carveracontroller.protocols.messages import MessageKind, ParsedMessage

    controller = Controller.__new__(Controller)
    controller.continuous_jog_active = controller._continuous_jog_stopping = True
    controller.loadNUM = 1
    controller.load_buffer = Queue()
    controller._handle_protocol_message(ParsedMessage(MessageKind.LINE, "^Y"))
    assert not controller.continuous_jog_active
    assert not controller._continuous_jog_stopping
    assert controller.load_buffer.empty()


def test_folder_data_updates_the_load_activity_time():
    from queue import Queue

    from carveracontroller.Controller import Controller
    from carveracontroller.protocols.messages import MessageKind, ParsedMessage

    controller = Controller.__new__(Controller)
    controller.load_buffer = Queue()
    controller.load_buffer_size = 0
    with patch('carveracontroller.Controller.time.time', return_value=109):
        controller._handle_protocol_message(ParsedMessage(MessageKind.LOAD_CHUNK, 'fixture.cnc 100 12345'))
    assert controller.load_last_activity == 109
    assert controller.load_buffer.get_nowait() == 'fixture.cnc 100 12345'


def test_jog_acknowledgement_and_competing_input_do_not_replay_motion(jog):
    from carveracontroller.Controller import Controller

    button, _, root = jog
    controller = Controller.__new__(Controller)
    controller.jog_mode = Controller.JOG_MODE_CONTINUOUS
    controller.jog_speed = 300
    controller.continuous_jog_active = False
    controller._continuous_jog_stopping = False
    controller.stream = object()
    controller.executeCommand = Mock()
    controller.executeRealtime = Mock()
    root.controller = controller
    owner = finger()
    dispatch("begin", owner)
    controller.executeCommand.assert_called_once_with("$J -c X1 F300")
    # Keyboard and pendant starts share this controller gate.
    controller.jog("Y1")
    controller.startContinuousJog("Z1", 100)
    controller.executeCommand.assert_called_once()
    move(owner, 180, 50)
    dispatch("update", owner)
    controller.executeRealtime.assert_called_once_with(0x19)
    assert controller._continuous_jog_stopping
    dispatch("begin", finger(ident="2"))
    controller.executeCommand.assert_called_once()
    controller._clear_continuous_jog_state()  # Firmware stop acknowledgement.
    move(owner, 50, 50)
    dispatch("update", owner)
    dispatch("end", owner)
    controller.executeCommand.assert_called_once()
    dispatch("begin", finger(ident="3"))
    assert controller.executeCommand.call_count == 2
    controller.stream = None
    controller._clear_continuous_jog_state()
    button._check_jog(0)
    controller.stream = object()
    assert button._jog_touch is None
    assert controller.executeCommand.call_count == 2


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


def test_two_finger_transform_rebases_when_contacts_change():
    transform = PointerTransform()
    first, second = finger(100, 100), finger(200, 100, "2")
    transform.begin(first)
    assert transform.move(first) == (0, 0, 1, 1)
    transform.begin(second)
    assert transform.move(second) == (0, 0, 1, 2)
    move(second, 220, 100)
    dx, dy, ratio, count = transform.move(second)
    assert (dx, dy, count) == pytest.approx((10, 0, 2))
    assert ratio == pytest.approx(1.2)
    transform.end(first)
    assert transform.move(second) == (0, 0, 1, 1)


def test_completed_toggle_does_not_toggle_after_drag_or_cancellation():
    button = TouchCheckBox(size_hint=(None, None), size=(100, 100))
    Window.add_widget(button)
    with patch("carveracontroller.ui.touch.platform", "android"):
        try:
            motion = finger()
            dispatch("begin", motion)
            assert not button.active
            dispatch("end", motion)
            assert button.active
            motion = finger(ident="2")
            dispatch("begin", motion)
            move(motion, 180, 50)
            dispatch("update", motion)
            move(motion, 50, 50)
            dispatch("end", motion)
            assert button.active
            motion = finger(ident="3")
            dispatch("begin", motion)
            motion.ud[TOUCH_CANCELLED] = True
            dispatch("end", motion)
            assert button.active
        finally:
            button.cancel_gestures()
            Window.remove_widget(button)


def test_same_frame_native_cancel_suppresses_initial_press():
    button = Button(size_hint=(None, None), size=(100, 100))
    pressed = Mock()
    button.bind(on_press=pressed)
    Window.add_widget(button)
    try:
        motion = finger()
        motion.ud[TOUCH_CANCELLED] = True
        for phase, touch in TouchPostprocessor().process([("begin", motion), ("end", motion)]):
            dispatch(phase, touch)
        pressed.assert_not_called()
    finally:
        Window.remove_widget(button)


def test_recycled_row_cancels_pending_hold():
    class HoldTestRow(TapBehavior, Widget):
        supports_hold = True
        on_hold = Mock()
        on_tap = Mock()

    row = HoldTestRow(size_hint=(None, None), size=(100, 100))
    Window.add_widget(row)
    try:
        motion = finger()
        dispatch("begin", motion)
        candidate = row._tap_gesture
        row.cancel_gestures()
        candidate._hold(row.on_hold)
        dispatch("end", motion)
        row.on_hold.assert_not_called()
        row.on_tap.assert_not_called()
    finally:
        row.cancel_gestures()
        Window.remove_widget(row)
