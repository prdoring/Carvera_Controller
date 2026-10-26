"""Readable touch dropdowns that keep the job-control footer accessible."""

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.label import Label
from kivy.uix.slider import Slider
from kivy.uix.switch import Switch
from kivy.uix.widget import Widget


class DropdownLayout:
    def __init__(self, dropdown):
        self.dropdown = dropdown
        self.anchor = None
        self.bound = False
        self.refresh = Clock.create_trigger(self.fit, 0)
        dropdown.bind(on_dismiss=self.detach, pos=self.keep_above_footer, size=self.keep_above_footer)

    def open(self, anchor):
        self.anchor = anchor
        dropdown = self.dropdown
        dropdown.container.padding = dp(6)
        dropdown.container.spacing = dp(4)
        dropdown.bar_width = dp(8)
        dropdown.bar_inactive_color = (.55, .60, .65, .65)
        dropdown.scroll_type = ["bars", "content"]
        change = getattr(dropdown, "change_dropdown", None)
        if change is not None:
            button = next((child for child in dropdown.container.children if child == change), None)
            if button is not None and dropdown.container.children[-1] != button:
                dropdown.container.remove_widget(button)
                dropdown.container.add_widget(button, index=len(dropdown.container.children))
        app = App.get_running_app()
        if app is not None:
            if not self.bound:
                Window.bind(size=self.refresh)
                Metrics.bind(density=self.refresh, fontscale=self.refresh)
                self.bound = True
            self.fit()

    def detach(self, *_args):
        self.refresh.cancel()
        Window.unbind(size=self.refresh)
        Metrics.unbind(density=self.refresh, fontscale=self.refresh)
        self.bound = False

    def footer_top(self):
        app = App.get_running_app()
        if app is None or app.root is None:
            return 0
        button = app.root.ids.get("main_file_button")
        if button is None:
            return 0
        return button.to_window(*button.pos)[1] + button.height

    def measure(self, widget, width=None):
        text = getattr(widget, "text", "")
        if not text:
            return (0, 0)
        label = CoreLabel(
            text=text,
            font_name=widget.font_name,
            font_size=widget.font_size,
            bold=getattr(widget, "bold", False),
            text_size=(width, None),
        )
        label.refresh()
        return label.texture.size

    def height(self, widget, width):
        if not widget.opacity:
            return widget.height
        if widget.size_hint_y is None and widget.height == 0:
            return 0
        app = App.get_running_app()
        if isinstance(widget, Button):
            if widget.text.strip() in ("+", "-", "−"):
                widget.halign = "center"
            widget.text_size = (max(dp(24), width - dp(112 if getattr(widget, "icon", "") and widget.text else 24)), None)
            return max(app.touch_target, self.measure(widget, widget.text_size[0])[1] + dp(16))
        if isinstance(widget, Label):
            return self.measure(widget, max(dp(24), width - dp(16)))[1] + dp(8) if widget.text else 0
        if isinstance(widget, (Slider, Switch)):
            return app.touch_target
        if isinstance(widget, BoxLayout):
            inner = max(dp(24), width - sum(widget.padding[::2]))
            if widget.orientation == "horizontal":
                fixed = sum(child.width for child in widget.children if child.size_hint_x is None)
                shares = sum(child.size_hint_x or 0 for child in widget.children)
                available = max(dp(24), inner - fixed - widget.spacing * max(0, len(widget.children) - 1))
                heights = [self.height(child, child.width if child.size_hint_x is None else
                                       available * child.size_hint_x / max(1, shares))
                           for child in widget.children]
            else:
                heights = [self.height(child, inner) for child in widget.children]
            if widget.orientation == "vertical":
                for child, height in zip(widget.children, heights):
                    child.size_hint_y = None
                    child.height = height
                return sum(heights) + max(0, len(heights) - 1) * widget.spacing + sum(widget.padding[1::2])
            return max(heights, default=0) + sum(widget.padding[1::2])
        if type(widget) is Widget:
            return 0
        return widget.height

    def fit(self, *_args):
        app = App.get_running_app()
        if self.anchor is None or app is None:
            return
        if not app.android_touch:
            self.fit_desktop()
            return
        dropdown = self.dropdown
        words = [
            self.measure(widget)[0] + dp(64 if getattr(widget, "icon", "") else 32)
            for widget in dropdown.container.walk()
            if isinstance(widget, (Label, Button)) and widget.opacity and getattr(widget, "text", "")
        ]
        left, top, right, _bottom = app.safe_area_padding
        dropdown.auto_width = False
        dropdown.width = max(1, min(Window.width - left - right - dp(16), max([self.anchor.width, dp(240)] + words)))
        dropdown.max_height = max(1, Window.height - top - self.footer_top() - dp(8))
        inner = max(dp(24), dropdown.width - sum(dropdown.container.padding[::2]))
        for child in dropdown.container.children:
            child.size_hint_y = None
            child.height = self.height(child, inner)
        self.keep_above_footer()

    def fit_desktop(self):
        dropdown = self.dropdown
        options = dropdown.container.children
        if not options or not all(isinstance(child, Button) for child in options):
            return
        needed = max(self.measure(child)[0] + dp(32) for child in options)
        dropdown.auto_width = False
        dropdown.width = min(Window.width - dp(16), max(self.anchor.width, needed)
                             + sum(dropdown.container.padding[::2]))
        dropdown.max_height = max(1, Window.height - dp(16))
        inner = max(1, dropdown.width - sum(dropdown.container.padding[::2]) - dp(24))
        for child in options:
            child.text_size = (inner, None)
            child.size_hint_y = None
            child.height = max(dp(40), self.measure(child, inner)[1] + dp(16))

    def keep_above_footer(self, *_args):
        app = App.get_running_app()
        dropdown = self.dropdown
        if app is not None and app.android_touch and dropdown.attach_to is not None:
            left, top, right, _bottom = app.safe_area_padding
            minimum = self.footer_top()
            maximum = max(minimum, Window.height - top - dropdown.height)
            dropdown.y = max(minimum, min(dropdown.y, maximum))
            dropdown.x = max(left, min(dropdown.x, Window.width - right - dropdown.width))


class ThemedDropDown(DropDown):
    def open(self, widget, *args, **kwargs):
        if not hasattr(self, "_theme_layout"):
            self._theme_layout = DropdownLayout(self)
        self._theme_layout.open(widget)
        return super().open(widget, *args, **kwargs)
