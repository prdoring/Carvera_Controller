"""In-app screensaver, input ownership and lightweight workshop animation."""

import math
import random
import time
from bisect import bisect_right
from datetime import datetime

from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, PopMatrix, PushMatrix, Rectangle, Rotate, Translate
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
        self._clock_minute = None
        self._clock_due = 0.0
        self._prepared = False
        self._geometry_dirty = True
        self._lines = []
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
        self._clock_minute = None
        self._clock_due = 0.0
        self._geometry_dirty = True

    def _new_pattern(self):
        self._prepared = True
        self._geometry_dirty = True
        self._opacity = None
        self.art.canvas.clear()
        self._lines = []
        if self.style == "clock":
            return
        if self.style == "parts":
            self._new_parts()
            return
        paths = pattern(self.style, self.rng)
        self.traces = [Trace(p) for p in paths]
        self._ends = []
        self.total_length = 0.0
        for trace in self.traces:
            self.total_length += trace.length
            self._ends.append(self.total_length)
        with self.art.canvas:
            self._gray_color = Color(*theme.BORDER)
            gray_lines = [Line(points=[], width=1) for _ in paths]
            self._copper_color = Color(*theme.ACCENT)
            copper_lines = [Line(points=[], width=1.3) for _ in paths]
            self._lines = list(zip(gray_lines, copper_lines))
            self.dot = Ellipse(size=(0, 0))

    def _new_parts(self):
        self._part_paths = [
            ellipse(0, 0, 0.034, 0.034, count=6),
            ellipse(0, 0, 0.018, 0.018, count=6),
            [(-0.025, -0.012), (0.025, -0.012), (0.025, 0.012), (-0.025, 0.012), (-0.025, -0.012)],
            [(0.025, -0.023), (0.045, -0.023), (0.045, 0.023), (0.025, 0.023), (0.025, -0.023)],
            *[[(x, -0.012), (x + 0.008, 0.012)] for x in (-0.02, -0.01, 0, 0.01)],
        ]
        self._part_lines = []
        self._part_transforms = []
        with self.art.canvas:
            for start, end, color in ((0, 2, theme.ACCENT), (2, 8, theme.SECONDARY)):
                PushMatrix()
                translation = Translate()
                rotation = Rotate(axis=(0, 0, 1))
                ink = Color(*color)
                self._part_transforms.append((translation, rotation, ink))
                self._part_lines.extend(Line(points=[], width=1) for _ in self._part_paths[start:end])
                PopMatrix()

    def _cache_geometry(self):
        self._geometry_dirty = False
        if self.style == "parts":
            for path, line in zip(self._part_paths, self._part_lines):
                line.points = [coordinate * self.width for point in path for coordinate in point]
        elif self.style != "clock":
            self._pixel_paths = [self._pixels(trace.points) for trace in self.traces]
            self._completed = [0, 0]
            self._distances = [None, None]
            self._tip = None
            for pair in self._lines:
                for line in pair:
                    line.points = []

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
        if self.elapsed < self._clock_due:
            return
        self._clock_due = self.elapsed + 1
        now = datetime.now()
        minute = (now.year, now.month, now.day, now.hour, now.minute)
        if minute == self._clock_minute:
            return
        self._clock_minute = minute
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
            if not self._prepared or self.style not in ("clock", "parts"):
                self._new_pattern()
        if self._geometry_dirty:
            self._cache_geometry()
        if self.show_clock:
            self._update_clock()
        clock_period = CYCLE_SECONDS if self.style not in ("clock", "parts") else 30
        clock_phase = self.elapsed % clock_period
        clock_fade = min(1, clock_phase * 2, (clock_period - clock_phase) * 2)
        self.clock.opacity = fade * clock_fade if self.show_clock else 0
        if self.style == "clock":
            return
        if self.style == "parts":
            self._move_parts(fade)
            return
        phase = self.elapsed % CYCLE_SECONDS
        opacity = min(1, max(0, CYCLE_SECONDS - phase)) * fade
        gray_distance = self.total_length * min(1, phase / 2)
        copper_distance = self.total_length * max(0, min(1, (phase - 2) / 30))
        if opacity != self._opacity:
            self._gray_color.a = self._copper_color.a = opacity
            self._opacity = opacity
        self._draw_progress(gray_distance, 0)
        self._draw_progress(copper_distance, 1)
        if self._tip is not None:
            px, py = self._tip
            self.dot.pos, self.dot.size = (px - 3, py - 3), (6, 6)
        else:
            self.dot.size = (0, 0)

    def _draw_progress(self, distance, layer):
        if distance == self._distances[layer]:
            return
        self._distances[layer] = distance
        completed = bisect_right(self._ends, distance)
        for i in range(self._completed[layer], completed):
            self._lines[i][layer].points = self._pixel_paths[i]
        self._completed[layer] = completed
        tip = self._pixel_paths[completed - 1][-2:] if completed else None
        if completed < len(self.traces):
            start = self._ends[completed - 1] if completed else 0
            if distance > start:
                pixels = self._pixels(self.traces[completed].prefix(distance - start))
                self._lines[completed][layer].points = pixels
                tip = pixels[-2:]
        if layer == 1:
            self._tip = tip

    def _move_parts(self, fade):
        for i, (translation, rotation, ink) in enumerate(self._part_transforms):
            nut = i == 0
            t = self.elapsed * (0.035 if nut else 0.027)
            cx = 0.1 + 0.8 * (1 - abs((t + (0 if nut else 0.85)) % 2 - 1))
            cy = 0.2 + 0.6 * (1 - abs((t * 0.79 + (0.2 if nut else 1.1)) % 2 - 1))
            translation.xy = (self.x + cx * self.width, self.y + cy * self.height)
            rotation.angle = math.degrees(self.elapsed * (0.15 if nut else -0.12)) % 360
            if fade != self._opacity:
                ink.a = fade
        self._opacity = fade

    def frame_delay(self):
        if self.style != "clock":
            return 1 / 20
        phase = self.elapsed % 30
        if self.show_clock and (phase < 0.5 or phase >= 29.5):
            return 1 / 20
        return min(1, 29.5 - phase) if phase < 29.5 else 1


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
        self._root_canvas = None
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
        self._cover_root()
        self.visible_since = self.now()
        self._last_frame = self.visible_since
        self._schedule_frame(0)

    def show(self, style=None, show_clock=None):
        if self.blocked():
            return False
        if style is None:
            _, style, show_clock = self.settings()
        self._selection = (style, show_clock)
        cancel_all_touches()
        self._replace(self.rotation.next() if style == "random" else style, show_clock)
        self._prioritize_keyboard()
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
        self._animation = None
        if self.overlay is not None:
            now = self.now()
            elapsed = now - self._last_frame
            self._last_frame = now
            age = now - self.visible_since
            fade = min(1, age * 2)
            if self._selection[0] == "random":
                fade = min(fade, max(0, (ROTATION_SECONDS - age) * 2))
            self.overlay.advance(elapsed, fade)
            delay = self.overlay.frame_delay()
            if age < 0.5 or (self._selection[0] == "random" and ROTATION_SECONDS - age <= 0.5):
                delay = 1 / 20
            elif self._selection[0] == "random":
                delay = min(delay, ROTATION_SECONDS - age - 0.5)
            self._schedule_frame(delay)

    def _schedule_frame(self, delay):
        if self._animation is not None:
            self._animation.cancel()
        self._animation = Clock.schedule_once(self._frame, delay)

    def hide(self):
        self._raise_event.cancel()
        if self.overlay is not None:
            overlay = self.overlay
            self.overlay = None
            Window.remove_widget(overlay)
        self._restore_root()
        if self._animation is not None:
            self._animation.cancel()
            self._animation = None
        self._preview = None
        self.last_activity = self.now()

    def _cover_root(self):
        if self._root_canvas is not None:
            return
        root = self.app.root
        if root.parent is not Window:
            return
        for group in (Window.canvas, Window.canvas.before, Window.canvas.after):
            index = group.indexof(root.canvas)
            if index >= 0:
                # Keep widgets and machine-status callbacks attached; skip only their covered drawing.
                self._root_canvas = (root, root.canvas, group, index)
                group.remove(root.canvas)
                return

    def _restore_root(self):
        saved = self._root_canvas
        self._root_canvas = None
        if saved is not None:
            root, canvas, group, index = saved
            if root.parent is Window and root.canvas is canvas and group.indexof(canvas) < 0:
                group.insert(min(index, len(group.children)), canvas)

    def process(self, events):
        if not events:
            return events
        if not self.visible and not self._swallowed:
            if any(getattr(touch, "is_touch", False) for _, touch in events):
                self.last_activity = self.now()
            return events
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
