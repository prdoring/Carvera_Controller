"""Edit numbers without opening the Android keyboard or resizing the workspace."""

from kivy.app import App
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView

from carveracontroller.translation import tr

from . import theme
from .editing import is_complete_number


class NumberPad(BoxLayout):
    _mobile_number_pad = True

    def __init__(self, source, **kwargs):
        self.source = source
        self.integer = source.effective_policy() == "integer"
        self._replace = True
        self._is_open = False
        super().__init__(size_hint=(None, None), **kwargs)
        self.register_event_type("on_dismiss")
        with self.canvas.before:
            Color(*theme.PANEL)
            self._background = RoundedRectangle(radius=[dp(6)])
        self.bind(pos=self._background_geometry, size=self._background_geometry)
        self.owner = source.parent
        while self.owner is not None and not isinstance(self.owner, ModalView):
            self.owner = getattr(self.owner, "parent", None)
        if self.owner is not None:
            self.owner.bind(on_dismiss=self._owner_dismissed)
        self.body = BoxLayout(orientation="vertical")
        self.heading = Label(text=getattr(source, "numeric_title", "")
                             or getattr(source, "tooltip_txt", "")
                             or getattr(self.owner, "title", "") or tr._("Enter value"),
                             font_name=theme.SANS, size_hint_y=None, shorten=True)
        self.display = Label(text=source.text, font_name=theme.SANS, halign="right",
                             valign="middle", size_hint_y=None, shorten=True, shorten_from="left")
        self.display.color = theme.ACCENT
        with self.display.canvas.before:
            Color(*theme.FIELD)
            self._display_background = RoundedRectangle(radius=[dp(4)])
        self.display.bind(pos=self._display_geometry, size=self._display_geometry)
        self.grid = GridLayout(cols=4, rows=4, size_hint_y=None)
        self.keys = {}
        for key in ("7", "8", "9", "back", "4", "5", "6", "clear",
                    "1", "2", "3", "sign", ".", "0", "cancel", "apply"):
            caption = {"back": "\u232b", "clear": tr._("Clear"), "sign": "+/-",
                       "cancel": tr._("Cancel"), "apply": tr._("Apply")}.get(key, key)
            button = Button(text=caption, font_name=theme.font_for(caption))
            button.bind(on_release=lambda _button, value=key: self.press(value))
            self.keys[key] = button
            self.grid.add_widget(button)
        self.keys["."].disabled = self.integer
        self.keys["apply"].background_color = theme.SELECTED
        for widget in (self.heading, self.display, self.grid):
            self.body.add_widget(widget)
        self.add_widget(self.body)
        self.display.bind(text=self._validate)
        Window.bind(size=self._fit)
        Metrics.bind(density=self._fit, fontscale=self._fit)
        self._fit()
        self._validate()

    def open(self, **_kwargs):
        if self._is_open:
            return
        self._is_open = True
        self.source.bind(pos=self._position, size=self._position)
        if self.owner is not None:
            self.owner.bind(pos=self._position, size=self._position)
        Window.bind(on_key_down=self._key_down)
        self._position()
        Window.add_widget(self)

    def dismiss(self, **_kwargs):
        if not self._is_open:
            return
        self._is_open = False
        if self.parent is not None:
            self.parent.remove_widget(self)
        self.dispatch("on_dismiss")

    def _background_geometry(self, *_args):
        self._background.pos, self._background.size = self.pos, self.size

    def _fit(self, *_args):
        app = App.get_running_app()
        left, top, right, bottom = app.safe_area_padding
        width, height = Window.width - left - right, Window.height - top - bottom
        target = max(app.touch_target, sp(18) * 1.3 + dp(12))
        self.body.padding = dp(8)
        self.body.spacing = self.grid.spacing = dp(4)
        self.grid.height = 4 * target + dp(12)
        self.display.height = sp(24) * 1.3 + dp(8)
        self.heading.height = sp(16) * 1.3 + dp(4)
        self.heading.font_size = sp(16)
        self.display.font_size = sp(24)
        desired = self.grid.height + self.display.height + self.heading.height + dp(24)
        if desired > height - dp(16):
            desired -= self.heading.height
            self.heading.height = 0
        self.heading.opacity = int(bool(self.heading.height))
        self.size = (min(width - dp(16), dp(300) * max(1, Metrics.fontscale)),
                     min(height - dp(16), desired))
        self._position()
        self.heading.text_size = self.display.text_size = (max(1, self.width - dp(24)), None)
        for key, button in self.keys.items():
            button.font_size = sp(16 if key in ("clear", "cancel", "apply") else 22)

    def _position(self, *_args):
        app = App.get_running_app()
        left, top, right, bottom = app.safe_area_padding
        gap = dp(8)
        x, y = self.source.to_window(*self.source.pos)
        field_right, field_top = self.source.to_window(self.source.right, self.source.top)
        right_edge = Window.width - right - gap
        left_edge = left + gap
        right_space, left_space = right_edge - field_right - gap, x - gap - left_edge
        if right_space >= self.width or right_space >= left_space:
            target_x = field_right + gap
        else:
            target_x = x - gap - self.width
        self.x = max(left_edge, min(target_x, right_edge - self.width))
        self.y = max(bottom + gap, min((y + field_top - self.height) / 2,
                                      Window.height - top - gap - self.height))

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            self.dismiss()
            return False
        super().on_touch_down(touch)
        return True

    def on_touch_move(self, touch):
        handled = super().on_touch_move(touch)
        return handled or self.collide_point(*touch.pos)

    def on_touch_up(self, touch):
        handled = super().on_touch_up(touch)
        return handled or self.collide_point(*touch.pos)

    def _key_down(self, _window, key, _scancode, text, _modifiers):
        action = {27: "cancel", 13: "apply", 271: "apply", 8: "back", 127: "clear"}.get(key)
        if action is not None:
            self.press(action)
        elif text == "-":
            self.press("sign")
        elif text and text in "0123456789.":
            self.press(text)
        return True

    def _display_geometry(self, *_args):
        self._display_background.pos = self.display.pos
        self._display_background.size = self.display.size

    def _validate(self, *_args):
        text = self.display.text
        self.keys["apply"].disabled = bool(text.strip()) and not is_complete_number(text, integer=self.integer)

    def press(self, key):
        if key == "cancel":
            self.dismiss(animation=False)
        elif key == "apply":
            if not self.keys["apply"].disabled and not self.source.disabled and self.source.get_root_window():
                self.source.text = self.display.text
                self.dismiss(animation=False)
        elif key == "clear":
            self.display.text = ""
            self._replace = False
        elif key == "back":
            self.display.text = "" if self._replace else self.display.text[:-1]
            self._replace = False
        elif key == "sign":
            self.display.text = self.display.text[1:] if self.display.text.startswith("-") else "-" + self.display.text
            self._replace = False
        elif key in "0123456789.":
            if key == "." and (self.integer or (not self._replace and "." in self.display.text)):
                return
            self.display.text = ("" if self._replace else self.display.text) + key
            self._replace = False
        self.display.color = theme.ACCENT if self._replace else theme.TEXT

    def _owner_dismissed(self, *_args):
        self.dismiss(animation=False)

    def on_dismiss(self):
        Window.unbind(size=self._fit)
        Window.unbind(on_key_down=self._key_down)
        self.source.unbind(pos=self._position, size=self._position)
        Metrics.unbind(density=self._fit, fontscale=self._fit)
        if self.owner is not None:
            self.owner.unbind(on_dismiss=self._owner_dismissed)
            self.owner.unbind(pos=self._position, size=self._position)
        self.source._number_pad = None
