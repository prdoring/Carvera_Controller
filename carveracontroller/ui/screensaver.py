"""In-app screensaver, input ownership and lightweight workshop animation."""

import math
import random
import time
from datetime import datetime

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, Rectangle
from kivy.uix.label import Label
from kivy.uix.widget import Widget

from carveracontroller import runtime_profile
from carveracontroller.CNC import CNC
from carveracontroller.kiosk_state import activity

from . import theme
from .screensaver_patterns import CYCLE_SECONDS, ROTATION_SECONDS, Rotation, Trace, ellipse, pattern, preferences
from .touch import cancel_all_touches


class ScreensaverCanvas(Widget):
    def __init__(self, style, show_clock, **kwargs):
        super().__init__(**kwargs)
        self.rng = random.Random()
        self.style, self.show_clock = style, show_clock
        self.elapsed = 0.0
        self.cycle = -1
        self.clock_slot = -1
        self._clock_text = None
        self._lines = []
        self._colors = []
        self.traces = []
        with self.canvas:
            Color(*theme.FIELD)
            self.background = Rectangle(pos=self.pos, size=self.size)
        self.art = Widget()
        self.add_widget(self.art)
        self.clock = Label(font_name=theme.MONO, color=theme.TEXT, halign="center", markup=True)
        self.add_widget(self.clock)
        self.bind(size=self._resize, pos=self._resize)
        self._resize()
        self.advance(0)

    def _resize(self, *_):
        self.background.pos, self.background.size = self.pos, self.size
        self.clock.font_size = self.height * 0.032
        self.clock.size = (self.width * (0.82 if self.style == "clock" else 0.36), self.height * 0.2)
        self.clock_slot = -1
        self._clock_text = None

    def _new_pattern(self):
        self.art.canvas.clear()
        self._lines, self._colors = [], []
        paths = pattern(self.style, self.rng)
        if self.style == "parts":
            paths = [
                ellipse(0, 0, 0.034, 0.034, count=6),
                ellipse(0, 0, 0.018, 0.018, count=6),
                [(-0.025, -0.012), (0.025, -0.012), (0.025, 0.012), (-0.025, 0.012), (-0.025, -0.012)],
                [(0.025, -0.023), (0.045, -0.023), (0.045, 0.023), (0.025, 0.023), (0.025, -0.023)],
                *[[(x, -0.012), (x + 0.008, 0.012)] for x in (-0.02, -0.01, 0, 0.01)],
            ]
        self.traces = [Trace(p) for p in paths]
        self.total_length = sum(t.length for t in self.traces)
        with self.art.canvas:
            for _ in paths:
                gray = Color(*theme.BORDER)
                line = Line(points=[], width=1)
                copper = Color(*theme.ACCENT)
                traced = Line(points=[], width=1.3)
                self._colors.append((gray, copper))
                self._lines.append((line, traced))
            self.dot_color = Color(*theme.ACCENT)
            self.dot = Ellipse(size=(0, 0))

    def _pixels(self, points):
        return [coordinate for x, y in points for coordinate in (self.x + x * self.width, self.y + y * self.height)]

    def _update_clock(self):
        slot = int(self.elapsed // (CYCLE_SECONDS if self.style not in ("clock", "parts") else 30))
        if slot != self.clock_slot:
            self.clock_slot = slot
            if self.style == "clock":
                x, y = self.rng.uniform(0.42, 0.58), self.rng.uniform(0.25, 0.75)
            else:
                x, y = self.rng.choice(((0.22, 0.9), (0.78, 0.9), (0.22, 0.1), (0.78, 0.1)))
            self.clock.center = (self.x + x * self.width, self.y + y * self.height)
        now = datetime.now()
        text = now.strftime("%H:%M\n%A, %d %B" if self.style == "clock" else "%H:%M\n%a %d %b")
        if self._clock_text != text:
            self._clock_text = text
            self.clock.font_name = theme.font_for(text, mono=True)
            if self.style == "clock":
                clock, date = text.split("\n")
                self.clock.text = f"[size={int(self.height * 0.12)}]{clock}[/size]\n{date}"
            else:
                self.clock.text = text

    def advance(self, dt, fade=1):
        self.elapsed += dt
        cycle = int(self.elapsed // CYCLE_SECONDS)
        if cycle != self.cycle:
            self.cycle = cycle
            self._new_pattern()
        self._update_clock()
        clock_period = CYCLE_SECONDS if self.style not in ("clock", "parts") else 30
        clock_phase = self.elapsed % clock_period
        clock_fade = min(1, clock_phase * 2, (clock_period - clock_phase) * 2)
        self.clock.opacity = fade * clock_fade if self.show_clock else 0
        if self.style == "clock":
            return
        phase = self.elapsed % CYCLE_SECONDS
        opacity = min(1, max(0, CYCLE_SECONDS - phase)) * fade
        gray_distance = self.total_length * min(1, phase / 2)
        copper_distance = self.total_length * max(0, min(1, (phase - 2) / 30))
        self.dot.size = (0, 0)
        for i, (trace, (gray, copper), (line, traced)) in enumerate(zip(self.traces, self._colors, self._lines)):
            gray.a = copper.a = opacity
            if self.style == "parts":
                nut = i < 2
                speed = 0.035 if nut else 0.027
                t = self.elapsed * speed
                bounce = lambda value: 1 - abs(value % 2 - 1)
                cx = 0.1 + 0.8 * bounce(t + (0 if nut else 0.85))
                cy = 0.2 + 0.6 * bounce(t * 0.79 + (0.2 if nut else 1.1))
                angle = self.elapsed * (0.15 if nut else -0.12)
                ca, sa = math.cos(angle), math.sin(angle)
                points = [
                    (cx + x * ca - y * sa, cy + (x * sa + y * ca) * self.width / self.height) for x, y in trace.points
                ]
                line.points = self._pixels(points)
                gray.rgba = (*theme.ACCENT[:3], fade) if nut else (*theme.SECONDARY[:3], fade)
                traced.points = []
                continue
            line.points = self._pixels(trace.prefix(gray_distance))
            prefix = trace.prefix(copper_distance)
            traced.points = self._pixels(prefix)
            if 0 < copper_distance <= trace.length and prefix:
                px, py = self._pixels([prefix[-1]])
                self.dot.pos, self.dot.size = (px - 3, py - 3), (6, 6)
                self.dot_color.a = opacity
            gray_distance -= trace.length
            copper_distance -= trace.length


class Screensaver:
    def __init__(self, app, now=time.monotonic):
        self.app, self.now = app, now
        self.overlay = None
        self.rotation = Rotation()
        self.last_activity = now()
        self.visible_since = 0.0
        self.current_style = None
        self._swallowed = set()
        self._keys = set()
        self._keyboard_tail = 0.0
        self._was_blocked = False
        self._last_state = str(app.state)
        self._last_alarm = (CNC.vars.get("halt_reason"), CNC.vars.get("alarm_message"))
        self._focused = True
        self._preview = None
        self._animation = None
        self._restacking = False
        self._raise_event = Clock.create_trigger(self._raise_overlay, 0)
        self._bindings = {
            "on_key_down": self._key_down,
            "on_key_up": self._key_up,
            "on_textinput": self._text,
            "on_textedit": self._text,
            "mouse_pos": self._mouse,
            "focus": self._focus,
            "size": self._resize,
            "children": self._children,
        }
        Window.bind(**self._bindings)
        EventLoop.add_postproc_module(self)
        self._timer = Clock.schedule_interval(self.check, 0.25)

    @property
    def visible(self):
        return self.overlay is not None

    def settings(self):
        return preferences(
            {
                key: Config.get("carvera", key, fallback=default)
                for key, default in (
                    ("screensaver_timeout_minutes", "30"),
                    ("screensaver_style", "random"),
                    ("screensaver_show_clock", "1"),
                )
            }
        )

    def blocked(self):
        status = activity(self.app)
        return (
            not self._focused
            or runtime_profile.maintenance_active
            or any(status["flags"].values())
            or (status["connected"] and status["state"] not in ("Idle", "Sleep", "Alarm"))
            or bool(EventLoop.touches)
        )

    def check(self, _dt):
        blocked = self.blocked()
        state = str(self.app.state)
        alarm = (CNC.vars.get("halt_reason"), CNC.vars.get("alarm_message"))
        new_alarm = state == "Alarm" and (self._last_state != state or alarm != self._last_alarm)
        self._last_alarm = alarm
        self._last_state = state
        if blocked or new_alarm or self._was_blocked:
            self.hide()
            self.last_activity = self.now()
        self._was_blocked = blocked
        if blocked or new_alarm:
            return
        minutes, style, show_clock = self._preview or self.settings()
        if self.visible:
            if not minutes or (style, show_clock) != self._selection:
                self.hide()
            elif style == "random" and self.now() - self.visible_since >= ROTATION_SECONDS:
                self._replace(self.rotation.next(), show_clock)
        elif minutes and self.now() - self.last_activity >= minutes * 60:
            self.show(style, show_clock)

    def _replace(self, style, show_clock):
        old = self.overlay
        self.overlay = ScreensaverCanvas(style, show_clock, size=Window.size, size_hint=(None, None))
        self.current_style = style
        Window.add_widget(self.overlay)
        if old is not None:
            Window.remove_widget(old)
        self.visible_since = self.now()

    def show(self, style=None, show_clock=None):
        if self.blocked():
            return False
        if style is None:
            _, style, show_clock = self.settings()
        self._selection = (style, show_clock)
        cancel_all_touches()
        self._replace(self.rotation.next() if style == "random" else style, show_clock)
        self._prioritize_keyboard()
        if self._animation is None:
            self._animation = Clock.schedule_interval(self._frame, 1 / 20)
        return True

    def _prioritize_keyboard(self):
        # Focused fields may have acquired a keyboard after application startup.
        for name in ("on_key_down", "on_key_up", "on_textinput", "on_textedit"):
            binding = {name: self._bindings[name]}
            Window.unbind(**binding)
            Window.bind(**binding)

    def preview(self, values):
        minutes, style, show_clock = preferences(values)
        self._preview = (minutes or 30, style, show_clock)
        if not self.show(style, show_clock):
            self._preview = None
            return False
        return True

    def _frame(self, dt):
        if self.overlay is not None:
            age = self.now() - self.visible_since
            fade = min(1, age * 2)
            if self._selection[0] == "random":
                fade = min(fade, max(0, (ROTATION_SECONDS - age) * 2))
            self.overlay.advance(dt, fade)

    def hide(self):
        self._raise_event.cancel()
        if self.overlay is not None:
            overlay = self.overlay
            self.overlay = None
            Window.remove_widget(overlay)
        if self._animation is not None:
            self._animation.cancel()
            self._animation = None
        self._preview = None
        self.last_activity = self.now()

    def process(self, events):
        result = []
        # Consume every finger arriving in the same batch as the waking touch.
        waking = self.visible and any(getattr(touch, "is_touch", False) for _, touch in events)
        for kind, touch in events:
            if not getattr(touch, "is_touch", False):
                result.append((kind, touch))
                continue
            self.last_activity = self.now()
            if waking or self._swallowed:
                self._swallowed.add(touch.uid)
            if touch.uid in self._swallowed:
                if kind == "end":
                    self._swallowed.discard(touch.uid)
                continue
            result.append((kind, touch))
        if waking:
            self.hide()
        return result

    def _key_down(self, _window, key, *_):
        self.last_activity = self.now()
        if self.visible or self._keys:
            self._keys.add(key)
            self._keyboard_tail = self.now() + 0.25
            self.hide()
            return True
        self._keyboard_tail = 0.0
        return False

    def _key_up(self, _window, key, *_):
        self.last_activity = self.now()
        if key in self._keys:
            self._keys.discard(key)
            self._keyboard_tail = self.now() + 0.25
            return True
        return False

    def _text(self, *_):
        if self.visible or self._keys or self.now() < self._keyboard_tail:
            self.hide()
            return True
        self.last_activity = self.now()
        return False

    def _mouse(self, *_):
        if not self.visible:
            self.last_activity = self.now()

    def _focus(self, _window, focused):
        self._focused = focused
        self.hide()
        cancel_all_touches()

    def _resize(self, *_):
        if self.overlay is not None:
            self.overlay.size = Window.size

    def _children(self, *_):
        if not self._restacking and self.visible:
            self._raise_event()

    def _raise_overlay(self, *_):
        if not self._restacking and self.overlay is not None and Window.children and Window.children[0] != self.overlay:
            self._restacking = True
            overlay = self.overlay
            Window.remove_widget(overlay)
            Window.add_widget(overlay)
            self._restacking = False
            self._prioritize_keyboard()

    def stop(self):
        self.hide()
        self._timer.cancel()
        EventLoop.remove_postproc_module(self)
        Window.unbind(**self._bindings)
