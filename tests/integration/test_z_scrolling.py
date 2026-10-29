import json
from collections import defaultdict, deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from kivy.base import EventLoop
from kivy.core.window import Window
from kivy.core.window.window_sdl2 import SDL2MotionEventProvider
from kivy.tests.common import UnitTestTouch
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from carveracontroller.ui import touch as gestures
from carveracontroller.ui.android_input import AndroidInput
from carveracontroller.ui.android_layout import fit_scroll_view
from carveracontroller.ui.scrolling import ScrollEffect
from carveracontroller.ui.touch import JogTouchButton, TapBehavior, TouchPostprocessor
from tests.integration.conftest import pump_frames, set_window_size


@pytest.fixture
def scroller(mobile, monkeypatch):
    monkeypatch.setattr(gestures, "touch_slop", 12)
    view = ScrollView(size_hint=(None, None), pos=(80, 80), size=(360, 240), do_scroll_x=False)
    button = Button(text="Scroll target", size_hint_y=None, height=1000)
    view.add_widget(button)
    Window.add_widget(view)
    fit_scroll_view(view)
    pump_frames(4)
    view.scroll_y = .5
    view._update_effect_bounds()
    try:
        yield view, button
    finally:
        for motion in list(EventLoop.touches):
            if view._get_uid() in motion.ud:
                gestures.cancel_touch(motion)
                EventLoop.post_dispatch_input("end", motion)
        view._scroll_gestures.cancel_gestures()
        Window.remove_widget(view)
        for effect in (view.effect_x, view.effect_y):
            effect.trigger_velocity_update.cancel()


def drag(motion, x, y):
    motion.move({"x": x / (Window.width - 1), "y": y / (Window.height - 1)})
    TouchPostprocessor().process([("update", motion)])
    EventLoop.post_dispatch_input("update", motion)


def finish(motion, cancelled=False):
    if cancelled:
        motion.ud["carvera_native_cancelled"] = True
    TouchPostprocessor().process([("end", motion)])
    motion.touch_up()


def native_swipe(start, end, action="up", pointer=17):
    provider = SDL2MotionEventProvider("sdl", "")
    provider.q, provider.touchmap = deque(), {}
    for kind, point in (("fingerdown", start), ("fingermotion", end), ("fingerup", end)):
        provider.q.appendleft((kind, pointer, point[0] / Window.width, 1 - point[1] / Window.height, 1))
    events = []

    def collect(*event):
        if event in events:
            events.remove(event)
        events.append(event)

    provider.update(collect)
    bridge = AndroidInput.__new__(AndroidInput)
    bridge.edges = defaultdict(deque)
    state = {"edges": [[pointer, "down", 0, start[0] / Window.width, start[1] / Window.height, 1000],
                       [pointer, action, 80, end[0] / Window.width, end[1] / Window.height, 1100]],
             "slop": 12, "hold_ms": 500, "interrupted": False,
             "insets": [0, 0, 0, 0], "keyboard_height": 0}
    bridge.api = SimpleNamespace(drain=lambda: json.dumps(state))
    from kivy.app import App

    bridge.app = App.get_running_app()
    original = gestures.touch_slop, gestures.hold_timeout
    try:
        return TouchPostprocessor().process(bridge.process(events))
    finally:
        gestures.touch_slop, gestures.hold_timeout = original


def test_slow_drag_remains_scrollable_after_the_tap_timeout(scroller):
    view, button = scroller
    pressed, released = Mock(), Mock()
    button.bind(on_press=pressed, on_release=released)
    motion = UnitTestTouch(180, 180)
    motion.touch_down()
    pump_frames(18, sleep=.02)
    pressed.assert_not_called()
    drag(motion, 180, 204)
    assert motion.ud[view._get_uid()]["mode"] == "scroll"
    assert view.scroll_y < .5
    finish(motion)
    assert view.effect_y.velocity != 0
    released.assert_not_called()


def test_tap_still_activates_once(scroller):
    _view, button = scroller
    released = Mock()
    button.bind(on_release=released)
    motion = UnitTestTouch(180, 180)
    motion.touch_down()
    finish(motion)
    pump_frames(18, sleep=.02)
    released.assert_called_once()


def test_complete_queued_swipe_scrolls_without_pressing_a_child(scroller):
    view, button = scroller
    pressed = Mock()
    button.bind(on_press=pressed, on_release=pressed)
    before = view.scroll_y
    assert native_swipe((180, 160), (180, 220)) == []
    assert view.scroll_y < before
    assert view.effect_y.velocity == pytest.approx(600)
    pressed.assert_not_called()
    assert view._touch is None


def test_native_cancel_does_not_replay_a_queued_swipe(scroller):
    view, button = scroller
    pressed = Mock()
    button.bind(on_press=pressed)
    before = view.scroll_y
    events = native_swipe((180, 160), (180, 220), action="cancel")
    for phase, motion in events:
        EventLoop.post_dispatch_input(phase, motion)
    assert view.scroll_y == before
    pressed.assert_not_called()


def test_second_queued_swipe_does_not_take_over_an_owned_scroll(scroller):
    view, _button = scroller
    owner = UnitTestTouch(180, 180)
    owner.touch_down()
    before = view.scroll_y
    for phase, motion in native_swipe((180, 160), (180, 220), pointer=18):
        EventLoop.post_dispatch_input(phase, motion)
    assert view._touch is owner
    assert view.scroll_y == before
    finish(owner)


def test_native_cancel_stops_coasting(scroller):
    view, _button = scroller
    motion = UnitTestTouch(180, 160)
    motion.touch_down()
    drag(motion, 180, 220)
    finish(motion, cancelled=True)
    assert view._touch is None
    assert view.effect_y.velocity == 0


def test_long_hold_is_preserved_and_drag_cancels_it(scroller):
    class HoldRow(TapBehavior, Widget):
        supports_hold = True
        on_hold = Mock()
        on_tap = Mock()

    view, button = scroller
    view.remove_widget(button)
    row = HoldRow(size_hint_y=None, height=1000)
    view.add_widget(row)
    pump_frames(3)
    view.scroll_y = .5
    motion = UnitTestTouch(180, 180)
    motion.touch_down()
    pump_frames(45, sleep=.02)
    row.on_hold.assert_called_once()
    finish(motion)
    row.on_tap.assert_not_called()
    row.on_hold.reset_mock()
    motion = UnitTestTouch(180, 180)
    motion.touch_down()
    pump_frames(15, sleep=.02)
    drag(motion, 180, 204)
    pump_frames(30, sleep=.02)
    row.on_hold.assert_not_called()
    finish(motion)


def test_horizontal_slider_drag_remains_available(scroller):
    view, button = scroller
    view.remove_widget(button)
    slider = Slider(size_hint_y=None, height=1000)
    view.add_widget(slider)
    pump_frames(3)
    view.scroll_y = .5
    motion = UnitTestTouch(180, 180)
    motion.touch_down()
    pump_frames(4, sleep=.02)
    drag(motion, 240, 180)
    drag(motion, 300, 180)
    finish(motion)
    assert slider.value > 0
    assert view.scroll_y == .5


def test_dropdown_only_scrolls_when_its_contents_overflow(mobile):
    from carveracontroller.ui.dropdown_layout import ThemedDropDown

    anchor = Button(size_hint=(None, None), size=(180, 60), pos=(200, Window.height - 100))
    Window.add_widget(anchor)
    dropdown = ThemedDropDown()
    entry = Button(text="One", size_hint_y=None, height=60)
    dropdown.add_widget(entry)
    try:
        dropdown.open(anchor)
        pump_frames(5)
        assert not dropdown.do_scroll_y
        x, y = entry.to_window(*entry.center)
        motion = UnitTestTouch(x, y)
        motion.touch_down()
        assert entry.state == "down"
        finish(motion)
        extra = [Button(text=str(i), size_hint_y=None, height=100) for i in range(30)]
        for button in extra:
            dropdown.add_widget(button)
        pump_frames(5)
        assert dropdown.do_scroll_y
        for button in extra:
            dropdown.remove_widget(button)
        pump_frames(5)
        assert not dropdown.do_scroll_y
    finally:
        dropdown.dismiss()
        Window.remove_widget(anchor)


@pytest.mark.parametrize("dt", [.4, .8, 10])
def test_coasting_does_not_reverse_after_a_stall(dt):
    effect = ScrollEffect(min=-5000, max=0, value=-1500, velocity=1000)
    try:
        effect.update_velocity(dt)
        assert effect.velocity >= 0
        assert effect.value >= -1500
        assert effect.value <= 0
    finally:
        effect.trigger_velocity_update.cancel()


def test_angle_settings_scroll_without_focusing_fields_or_sending_commands(mobile):
    from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

    app, _layout = mobile
    set_window_size((1280, 720))
    popup = ProbingPopup(app.root.controller)
    commands = list(app.simulation.commands)
    popup.open(animation=False)
    try:
        pump_frames(12, sleep=.02)
        panel = popup.ids.tabbedpanelid
        panel.switch_to(next(tab for tab in panel.tab_list if tab.text == "Angle"))
        pump_frames(12, sleep=.02)
        settings = popup.ids.angle_settings
        assert settings._settings is not None
        view = next(widget for widget in settings.walk(restrict=True) if isinstance(widget, ScrollView))
        assert view.do_scroll_y, (view.size, view._viewport.size, panel.current_tab.text)
        assert isinstance(view.effect_y, ScrollEffect)
        view.scroll_y = .5
        pump_frames(3)
        x, y = view.to_window(view.center_x, view.center_y)
        before = view.scroll_y
        motion = UnitTestTouch(x, y)
        motion.touch_down()
        pump_frames(18, sleep=.02)
        drag(motion, x, y + 32)
        assert view.scroll_y < before
        finish(motion, cancelled=True)
        assert view.effect_y.velocity == 0
        assert not any(widget.focus for widget in popup.walk() if isinstance(widget, TextInput))
        pump_frames(3)
        before = view.scroll_y
        assert native_swipe((x, y), (x, y + 60)) == []
        assert view.scroll_y < before
        assert app.simulation.commands == commands
    finally:
        popup.dismiss(force=True, animation=False)


def test_queued_drag_over_jog_control_never_starts_motion(mobile, monkeypatch):
    app, _layout = mobile
    button = JogTouchButton(size_hint=(None, None), pos=(80, 80), size=(300, 240), jog_command="X1")
    jog = Mock()
    monkeypatch.setattr(app.root, "_machine_allows_jogging", lambda: True)
    monkeypatch.setattr(app.root.controller, "jog", jog)
    monkeypatch.setattr(app.root.controller, "continuous_jog_active", False)
    monkeypatch.setattr(app.root.controller, "_continuous_jog_stopping", False)
    Window.add_widget(button)
    try:
        motion = UnitTestTouch(180, 160)
        motion.touch_down()
        motion.touch_up()
        jog.assert_called_once_with("X1")
        jog.reset_mock()
        for phase, motion in native_swipe((180, 160), (180, 220)):
            EventLoop.post_dispatch_input(phase, motion)
        jog.assert_not_called()
        assert button._jog_touch is None
        assert button.state == "normal"
    finally:
        button.cancel_jog()
        Window.remove_widget(button)


def test_zero_length_frame_does_not_stop_the_coasting_clock():
    effect = ScrollEffect(min=-5000, max=0, value=-1500, velocity=1000)
    try:
        effect.trigger_velocity_update.cancel()
        effect.update_velocity(0)
        assert effect.value == -1500
        assert effect.trigger_velocity_update.is_triggered
    finally:
        effect.trigger_velocity_update.cancel()


def test_overscroll_returns_to_its_bound_after_a_long_frame():
    effect = ScrollEffect(min=-5000, max=0, value=-10, velocity=1000)
    try:
        effect.update_velocity(.8)
        for _ in range(120):
            effect.update_velocity(effect.std_dt)
        assert -2 <= effect.value <= 0
        assert effect.overscroll == 0
        assert effect.velocity == 0
    finally:
        effect.trigger_velocity_update.cancel()
