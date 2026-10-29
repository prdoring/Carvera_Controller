"""Android scroll gestures and stable coasting across long frames."""

import weakref

from kivy.app import App
from kivy.core.window import Window
from kivy.effects.dampedscroll import DampedScrollEffect
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.utils import platform

from . import touch as gestures

_views = weakref.WeakSet()


class ScrollEffect(DampedScrollEffect):
    def update_velocity(self, dt):
        remaining = max(0, dt)
        # Friction and spring integration need short steps even on slow frames.
        while remaining > self.std_dt:
            super().update_velocity(self.std_dt)
            remaining -= self.std_dt
            if self.velocity == 0 and self.overscroll == 0:
                return
        super().update_velocity(remaining)


def _enabled():
    app = App.get_running_app()
    return platform == "android" or bool(app and getattr(app, "android_touch", False))


def _point(widget, x, y):
    return widget.to_parent(*widget.to_widget(x, y))


def _visible_at(widget, x, y):
    current = widget
    while current is not None and current is not Window:
        if current.disabled or not current.opacity or not current.width or not current.height:
            return False
        if (current is widget or isinstance(current, ScrollView)) and not current.collide_point(*_point(current, x, y)):
            return False
        current = current.parent
    return current is Window


class ScrollGestures:
    def __init__(self, view):
        self.view = view
        self._change_mode = view._change_touch_mode
        self._simulate_down = view.simulate_touch_down
        view._change_touch_mode = self.change_touch_mode
        view.simulate_touch_down = self.simulate_touch_down
        view.bind(on_scroll_start=self.start, on_scroll_move=self.move, on_scroll_stop=self.stop)
        gestures.gesture_owners.add(self)

    def start(self, _view, _touch):
        if _enabled():
            self.view.scroll_distance = gestures.touch_slop
            for effect in (self.view.effect_x, self.view.effect_y):
                if effect is not None:
                    effect.drag_threshold = gestures.touch_slop
        return False

    def simulate_touch_down(self, touch):
        if not _enabled():
            return self._simulate_down(touch)
        if touch.ud.get(gestures.TOUCH_CANCELLED):
            return False
        state = touch.ud.get(self.view._get_uid())
        if state is not None and state.get("slider_drag"):
            return self._simulate_down(touch)
        if touch.ud.get("carvera_dragged"):
            return False
        if state is not None:
            if state.get("child_down"):
                return True
            state["child_down"] = True
        return self._simulate_down(touch)

    def change_touch_mode(self, *args):
        if not _enabled():
            return self._change_mode(*args)
        touch = self.view._touch
        if not touch or self.view._viewport is None:
            return None
        state = touch.ud.get(self.view._get_uid())
        if state is None or state["mode"] != "unknown" or state["user_stopped"]:
            return None
        # Keep the scroll candidate captured. Only hold-enabled rows need a
        # child down before release; fields must not focus during a slow drag.
        for widget in self.view._viewport.walk(restrict=True):
            if (getattr(widget, "supports_hold", False)
                    and _visible_at(widget, touch.sx * Window.width, touch.sy * Window.height)):
                touch.push()
                touch.apply_transform_2d(self.view.to_widget)
                touch.apply_transform_2d(self.view.to_parent)
                self.simulate_touch_down(touch)
                touch.pop()
                break

    def move(self, _view, touch):
        if not _enabled():
            return False
        state = touch.ud.get(self.view._get_uid())
        if state is not None and state["mode"] == "unknown" and not self.view.do_scroll_x:
            if state["dx"] + abs(touch.dx) > gestures.touch_slop and abs(touch.dx) > abs(touch.dy):
                x, y = touch.sx * Window.width, touch.sy * Window.height
                if any(isinstance(widget, Slider) and _visible_at(widget, x, y)
                       for widget in self.view._viewport.walk(restrict=True)):
                    state["slider_drag"] = True
                    self._change_mode()
                    return True
        if state is not None and state.get("child_down"):
            if ((self.view.do_scroll_x and state["dx"] + abs(touch.dx) > gestures.touch_slop)
                    or (self.view.do_scroll_y and state["dy"] + abs(touch.dy) > gestures.touch_slop)):
                gestures.cancel_touch(touch)
        return False

    def stop(self, _view, touch):
        if _enabled() and touch.ud.get("carvera_native_cancelled") and self.view._touch is touch:
            self.cancel_gestures()
            return True
        return False

    def cancel_gestures(self):
        touch = self.view._touch
        if touch:
            gestures.cancel_touch(touch)
            touch.ungrab(self.view)
            self.view._touch = None
        for effect in (self.view.effect_x, self.view.effect_y):
            if effect is not None:
                effect.velocity = 0
                effect.cancel()


def configure_scroll_view(view):
    if not _enabled() or hasattr(view, "_scroll_gestures"):
        return
    if view.effect_cls is DampedScrollEffect:
        for effect, callback in ((view.effect_x, view._update_effect_x), (view.effect_y, view._update_effect_y)):
            if effect is not None:
                effect.trigger_velocity_update.cancel()
                effect.unbind(scroll=callback)
        view.effect_cls = ScrollEffect
        view._update_effect_bounds()
    view._scroll_gestures = ScrollGestures(view)
    _views.add(view)


def replay_swipe(touch):
    """Scroll a completed queued swipe without dispatching child presses."""
    if not _enabled() or touch.ud.get(gestures.TOUCH_CANCELLED):
        return False
    down = touch.ud.get("carvera_native_down")
    up = touch.ud.get("carvera_native_up")
    if not down or not up or up[2] <= down[2] or not Window.children:
        return False
    x, y = down[0] * Window.width, down[1] * Window.height
    top = Window.children[0]
    candidates = [view for view in top.walk(restrict=True) if view in _views]
    for view in reversed(candidates):
        if view._touch is not None or not _visible_at(view, x, y):
            continue
        start = _point(view, x, y)
        end = _point(view, up[0] * Window.width, up[1] * Window.height)
        axes = [(index, effect) for index, enabled, effect in (
            (0, view.do_scroll_x, view.effect_x), (1, view.do_scroll_y, view.effect_y))
            if enabled and effect is not None and abs(end[index] - start[index]) > gestures.touch_slop]
        if not axes:
            continue
        view._update_effect_bounds()
        view._effect_x_start_width = view.width
        view._effect_y_start_height = view.height
        for index, effect in axes:
            effect.drag_threshold = gestures.touch_slop
            effect.start(start[index], down[2] / 1000)
            effect.update(end[index], up[2] / 1000)
            effect.stop(end[index], up[2] / 1000)
        return True
    return False
