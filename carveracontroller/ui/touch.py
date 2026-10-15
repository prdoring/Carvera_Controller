"""Touch ownership shared by machine controls, rows and Android input."""

import math
import weakref

from kivy.app import App
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior, ToggleButtonBehavior
from kivy.uix.checkbox import CheckBox
from kivy.uix.settings import SettingItem
from kivy.uix.tabbedpanel import TabbedPanelItem
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget
from kivy.utils import platform

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton

TOUCH_CANCELLED = "carvera_touch_cancelled"
_gestures = weakref.WeakSet()
gesture_owners = weakref.WeakSet()
_jog_owner = None
touch_slop = dp(8)
hold_timeout = 0.5


def cancel_all_touches():
    cancel_jog()
    for owner in list(gesture_owners):
        owner.cancel_gestures()
    for gesture in list(_gestures):
        gesture.cancel()
    for touch in list(EventLoop.touches):
        cancel_touch(touch)


def cancel_touch(touch):
    touch.ud[TOUCH_CANCELLED] = True
    for ref in list(touch.grab_list):
        widget = ref()
        if isinstance(widget, SettingItem):
            widget.selected_alpha = 0
            touch.ungrab(widget)
        if isinstance(widget, ButtonBehavior):
            if isinstance(widget, JogTouchButton):
                widget.cancel_jog()
            if not isinstance(widget, ToggleButtonBehavior):
                widget.state = "normal"
            touch.ungrab(widget)


class Gesture:
    """One finger's tap/hold candidate, cancelled permanently by a drag."""

    def __init__(self, touch, hold=None):
        self.touch = touch
        self.start = tuple(touch.pos)
        self.cancelled = False
        self.held = False
        self._event = Clock.schedule_once(lambda dt: self._hold(hold), hold_timeout) if hold else None
        _gestures.add(self)

    def move(self):
        if (math.dist(self.start, self.touch.pos) > touch_slop or self.touch.ud.get(TOUCH_CANCELLED)
                or self.touch.ud.get("carvera_dragged")):
            self.cancel()

    def _hold(self, callback):
        self._event = None
        self.move()
        if not self.cancelled:
            self.held = True
            callback(self.touch)

    def finish(self):
        self.move()
        accepted = not self.cancelled and not self.held
        self.cancel()
        return accepted

    def cancel(self):
        self.cancelled = True
        if self._event is not None:
            self._event.cancel()
            self._event = None
        _gestures.discard(self)


class PointerTransform:
    """Incremental pan and scale deltas; finger-count changes have no delta."""

    def __init__(self):
        self.points = {}

    def begin(self, touch):
        self.points[touch.uid] = tuple(touch.pos)

    def move(self, touch):
        if touch.uid not in self.points:
            return None
        previous = list(self.points.values())[:2]
        self.points[touch.uid] = tuple(touch.pos)
        current = list(self.points.values())[:2]
        count = len(current)
        dx = sum(p[0] for p in current) / count - sum(p[0] for p in previous) / count
        dy = sum(p[1] for p in current) / count - sum(p[1] for p in previous) / count
        ratio = 1.0
        if count == 2:
            old_span = math.dist(*previous)
            if old_span > touch_slop:
                ratio = max(0.1, math.dist(*current) / old_span)
        return dx, dy, ratio, count

    def end(self, touch):
        self.points.pop(touch.uid, None)


class TapBehavior:
    """Completed taps and holds that coexist with a parent ScrollView."""

    touch_pressed = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        gesture_owners.add(self)

    def on_touch_down(self, touch):
        if super().on_touch_down(touch):
            return True
        if (touch.ud.get(TOUCH_CANCELLED) or self.disabled or not self.collide_point(*touch.pos)
                or getattr(touch, "is_mouse_scrolling", False)):
            return False
        if getattr(touch, "button", "left") == "right":
            self.on_hold(touch)
            return True
        if getattr(self, "_tap_gesture", None) is not None:
            return True
        self._tap_gesture = Gesture(touch, self.on_hold if getattr(self, "supports_hold", False) else None)
        self.touch_pressed = True
        touch.grab(self)
        return True

    def on_touch_move(self, touch):
        gesture = getattr(self, "_tap_gesture", None)
        if gesture is not None and gesture.touch is touch:
            gesture.move()
            self.touch_pressed = not gesture.cancelled
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        gesture = getattr(self, "_tap_gesture", None)
        if gesture is not None and gesture.touch is touch:
            accepted = gesture.finish() and self.collide_point(*touch.pos) and not self.disabled
            self._tap_gesture = None
            self.touch_pressed = False
            touch.ungrab(self)
            if accepted:
                self.on_tap(touch)
            return True
        return super().on_touch_up(touch)

    def cancel_gestures(self):
        self.touch_pressed = False
        gesture = getattr(self, "_tap_gesture", None)
        if gesture is not None:
            gesture.cancel()
            gesture.touch.ungrab(self)
            self._tap_gesture = None

    def on_hold(self, touch):
        pass


class CompletedToggle:
    touch_pressed = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._toggle_gesture = None
        super().__init__(**kwargs)
        gesture_owners.add(self)

    def on_touch_down(self, touch):
        if platform != "android":
            return super().on_touch_down(touch)
        if Widget.on_touch_down(self, touch):
            return True
        if (self.disabled or not self.collide_point(*touch.pos) or getattr(touch, "is_mouse_scrolling", False)
                or touch.ud.get(TOUCH_CANCELLED)):
            return False
        if self._toggle_gesture is None:
            self._toggle_gesture = Gesture(touch)
            self.touch_pressed = True
            touch.grab(self)
        return True

    def on_touch_move(self, touch):
        if platform != "android":
            return super().on_touch_move(touch)
        if self._toggle_gesture is not None and self._toggle_gesture.touch is touch:
            self._toggle_gesture.move()
            if self._toggle_gesture.cancelled:
                self.touch_pressed = False
            return True
        return False

    def on_touch_up(self, touch):
        if platform != "android":
            return super().on_touch_up(touch)
        gesture = self._toggle_gesture
        if gesture is None or gesture.touch is not touch:
            return False
        accepted = gesture.finish() and self.collide_point(*touch.pos) and not self.disabled
        self.cancel_gestures()
        if accepted:
            self._do_press()
            self.dispatch("on_press")
            self.dispatch("on_release")
        return True

    def cancel_gestures(self):
        if self._toggle_gesture is not None:
            self._toggle_gesture.cancel()
            self._toggle_gesture.touch.ungrab(self)
            self._toggle_gesture = None
        self.touch_pressed = False


class TouchCheckBox(CompletedToggle, CheckBox):
    pass


class TouchToggleButton(CompletedToggle, ToggleButton):
    pass


class TouchTabbedPanelItem(CompletedToggle, TabbedPanelItem):
    pass


class JogTouchButton(ToolTipButton):
    jog_command = StringProperty("")

    def __init__(self, **kwargs):
        self._jog_touch = None
        self._jog_controller = None
        self._jog_check = None
        super().__init__(**kwargs)
        self.bind(disabled=lambda *_: self.cancel_jog() if self.disabled else None)
        self.bind(parent=lambda *_: self.cancel_jog() if self.get_root_window() is None else None)

    def on_touch_down(self, touch):
        global _jog_owner
        if (touch.ud.get(TOUCH_CANCELLED) or self.disabled or not self.collide_point(*touch.pos)
                or getattr(touch, "is_mouse_scrolling", False)):
            return False
        if "button" in touch.profile and touch.button != "left":
            return False
        app = App.get_running_app()
        controller = app.root.controller
        if _jog_owner is not None or controller.continuous_jog_active or controller._continuous_jog_stopping:
            return True
        if not app.root._machine_allows_jogging() or not self.jog_command:
            return True
        _jog_owner = self
        self._jog_touch = touch
        self._jog_controller = controller
        self.state = "down"
        touch.grab(self)
        controller.jog(self.jog_command)
        self._jog_check = Clock.schedule_interval(self._check_jog, 0.05)
        return True

    def _check_jog(self, dt):
        app = App.get_running_app()
        if (self.disabled or self.get_root_window() is None or self._jog_controller.stream is None
                or not app.root._machine_allows_jogging()):
            self.cancel_jog()

    def on_touch_move(self, touch):
        if touch is self._jog_touch:
            margin = touch_slop
            if (touch.ud.get(TOUCH_CANCELLED) or not
                    (self.x - margin <= touch.x <= self.right + margin
                     and self.y - margin <= touch.y <= self.top + margin)):
                self.cancel_jog()
            return True
        return False

    def on_touch_up(self, touch):
        if touch is self._jog_touch:
            self.cancel_jog()
            return True
        return False

    def cancel_jog(self):
        global _jog_owner
        if self._jog_touch is None:
            return
        self._jog_controller.stopContinuousJog()
        self._jog_touch.ungrab(self)
        self._jog_touch = None
        self._jog_controller = None
        self.state = "normal"
        if self._jog_check is not None:
            self._jog_check.cancel()
            self._jog_check = None
        if _jog_owner is self:
            _jog_owner = None


def cancel_jog():
    if _jog_owner is not None:
        _jog_owner.cancel_jog()


class TouchPostprocessor:
    """Cancel button activation after dragging, before release is dispatched."""

    def process(self, events):
        for phase, touch in events:
            if not touch.is_touch:
                continue
            pos = (touch.sx * Window.width, touch.sy * Window.height)
            if phase == "begin":
                touch.ud["carvera_start"] = pos
                touch.ud.setdefault("carvera_dragged", False)
            else:
                start = touch.ud.get("carvera_start", pos)
                if math.dist(start, pos) > touch_slop:
                    touch.ud["carvera_dragged"] = True
            if phase == "end" and (touch.ud.get("carvera_dragged") or touch.ud.get(TOUCH_CANCELLED)):
                cancel_touch(touch)
        # A cancel may arrive in the same frame as its down event. Its grabbed
        # widgets do not exist yet, so suppress that down instead of activating it.
        return [(phase, touch) for phase, touch in events if phase != "begin"
                or not (touch.ud.get(TOUCH_CANCELLED) or touch.ud.get("carvera_dragged"))]


Factory.register("JogTouchButton", cls=JogTouchButton)
Factory.register("TouchCheckBox", cls=TouchCheckBox)
Factory.register("TouchToggleButton", cls=TouchToggleButton)
Factory.register("TouchTabbedPanelItem", cls=TouchTabbedPanelItem)
