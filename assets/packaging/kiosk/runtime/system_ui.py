"""Touch controls and Slate Workshop presentation for standalone recovery."""

import math
from copy import deepcopy
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.resources import resource_add_path
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.vkeyboard import VKeyboard

from carveracontroller.translation import tr
from carveracontroller.ui import theme


def install_style():
    package = Path(theme.__file__).resolve().parents[1]
    resource_add_path(str(package))
    fonts = package / "data/fonts"
    LabelBase.register(
        name="PlexSans",
        fn_regular=str(fonts / "IBMPlexSans-Regular.ttf"),
        fn_bold=str(fonts / "IBMPlexSans-SemiBold.ttf"),
    )
    LabelBase.register(name="PlexMono", fn_regular=str(fonts / "IBMPlexMono-Regular.ttf"))
    LabelBase.register(name="ARIALUNI", fn_regular=str(package / "ARIALUNI.ttf"))
    Builder.load_file(str(package / "ui/controls.kv"))
    Window.clearcolor = theme.BACKGROUND


class SystemButton(Button):
    """Keep a button gesture stable until release, including keyboard dismissal."""

    def __init__(self, **kwargs):
        self._touch = None
        self._start = None
        self._cancelled = False
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(52)
        self.bind(width=self._wrap, disabled=self._disabled, parent=self._disabled)

    def _wrap(self, *_args):
        self.text_size = (max(dp(20), self.width - dp(24)), None)
        self.halign = "center"
        self.valign = "middle"

    def _disabled(self, *_args):
        if self.disabled or self.parent is None:
            self.cancel()

    def cancel(self):
        if self._touch is not None:
            self._touch.ungrab(self)
        self._touch = None
        self.state = "normal"

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if self.disabled or self._touch is not None:
            return True
        if "button" in touch.profile and touch.button != "left":
            return False
        self._touch, self._start, self._cancelled = touch, (touch.sx * Window.width, touch.sy * Window.height), False
        touch.grab(self)
        FocusBehavior.ignored_touch.append(touch)
        self.state = "down"
        return True

    def on_touch_move(self, touch):
        if touch is self._touch:
            if math.dist(self._start, (touch.sx * Window.width, touch.sy * Window.height)) > dp(
                8
            ) or not self.collide_point(*touch.pos):
                self._cancelled = True
                self.state = "normal"
            return True
        return False

    def on_touch_up(self, touch):
        if touch is not self._touch:
            return False
        accepted = (
            not self._cancelled
            and not self.disabled
            and self.collide_point(*touch.pos)
            and not touch.ud.get("system_dragged")
            and not touch.ud.get("carvera_native_cancelled")
        )
        self.cancel()
        if accepted:
            # Focus/layout changes happen after this complete pointer dispatch.
            Clock.schedule_once(
                lambda _dt: self.dispatch("on_release") if self.get_root_window() and not self.disabled else None
            )
        return True


class SystemInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(
            multiline=False,
            use_bubble=False,
            use_handles=False,
            unfocus_on_touch=False,
            size_hint_y=None,
            height=dp(52),
            **kwargs,
        )
        self.bind(focus=self._focused)

    def _focused(self, _widget, focused):
        if focused:
            app = App.get_running_app()
            if hasattr(app, "focus_field"):
                app.focus_field(self)

    def on_touch_down(self, touch):
        if "button" in touch.profile and touch.button in ("middle", "right"):
            return False
        return super().on_touch_down(touch)


class SystemScrollView(ScrollView):
    """Do not replay a dragged pointer as a field focus or button press."""

    def __init__(self, **kwargs):
        super().__init__(always_overscroll=False, **kwargs)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.ud.setdefault("system_start", (touch.sx * Window.width, touch.sy * Window.height))
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        start = touch.ud.get("system_start")
        if start and math.dist(start, (touch.sx * Window.width, touch.sy * Window.height)) > dp(8):
            touch.ud["system_dragged"] = True
        return super().on_touch_move(touch)

    def _change_touch_mode(self, *_args):
        # Keep the scroll candidate until release so a slow swipe cannot edit a field.
        return None

    def simulate_touch_down(self, touch):
        if touch.ud.get("system_dragged"):
            return False
        return super().simulate_touch_down(touch)


class Paragraph(Label):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, halign="left", valign="middle", **kwargs)
        self.bind(width=self._fit, texture_size=self._fit)
        self._fit()

    def _fit(self, *_args):
        self.text_size = (max(dp(20), self.width), None)
        self.height = max(dp(28), self.texture_size[1] + dp(8))


class Panel(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(12), padding=dp(16), size_hint_y=None, **kwargs)
        self.bind(minimum_height=self.setter("height"))
        from kivy.graphics import Color, RoundedRectangle

        with self.canvas.before:
            Color(*theme.PANEL)
            self._surface = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
        self.bind(pos=self._paint, size=self._paint)

    def _paint(self, *_args):
        self._surface.pos, self._surface.size = self.pos, self.size


class KeyboardLayout:
    def __init__(self, app, shell):
        self.app, self.shell = app, shell
        self.keyboards = set()
        self._reveal_signature = None
        self.event = Clock.create_trigger(self.reflow, 0)
        Window.bind(children=self.changed, size=self.event, on_focus=self.window_focus)
        app.scroll.bind(size=self.event)
        self.changed()

    def changed(self, *_args):
        keyboards = {child for child in Window.children if isinstance(child, VKeyboard)}
        for keyboard in self.keyboards - keyboards:
            keyboard.unbind(size=self.event, pos=self.event)
        for keyboard in keyboards - self.keyboards:
            keyboard.bind(size=self.event, pos=self.event)
            keyboard.background_color = theme.PANEL
            keyboard.key_background_color = theme.CONTROL
            keyboard.background = "data/theme/panel.png"
            keyboard.background_disabled = "data/theme/panel.png"
            keyboard.key_background_normal = "data/theme/button.png"
            keyboard.key_background_down = "data/theme/button-down.png"
            keyboard.key_disabled_background_normal = "data/theme/button-disabled.png"
            keyboard.font_name = theme.SANS
            keyboard.font_size = sp(18)
            layouts = deepcopy(dict(keyboard.available_layouts))
            names = {
                "tab": tr._("Tab"),
                "capslock": tr._("Caps"),
                "shift": tr._("Shift"),
                "enter": tr._("Enter"),
                "backspace": tr._("Delete"),
                "layout": tr._("Layout"),
                "escape": tr._("Hide"),
            }
            for layout in layouts.values():
                for row in layout.values():
                    if isinstance(row, list):
                        for key in row:
                            if isinstance(key, list) and len(key) == 4 and key[2] in names:
                                key[0] = names[key[2]]
            keyboard.available_layouts = layouts
            Clock.schedule_once(lambda _dt, keyboard=keyboard: keyboard.refresh_keys())
        self.keyboards = keyboards
        self.event()

    def reflow(self, *_args):
        for keyboard in self.keyboards:
            keyboard.size = (Window.width, min(dp(300), Window.height * 0.5))
            keyboard.scale = 1
            keyboard.pos = (0, 0)
        bottom = max((keyboard.top for keyboard in self.keyboards), default=0)
        self.shell.size_hint = (None, None)
        self.shell.pos = (0, bottom)
        self.shell.size = (Window.width, max(1, Window.height - bottom))
        field = self.app.active_field
        visible = field is not None and field.focus
        connect = visible and self.app.section == "Network"
        self.app.keyboard_connect.width = dp(160) if connect else 0
        self.app.keyboard_connect.opacity = int(connect)
        self.app.keyboard_connect.disabled = not connect or self.app.busy
        self.app.keyboard_actions.width = dp(460 if connect else 300) if visible else 0
        self.app.keyboard_actions.opacity = int(visible)
        self.app.keyboard_actions.disabled = not visible
        signature = (tuple(self.shell.size), tuple(self.app.scroll.size), field if visible else None)
        if signature != self._reveal_signature and visible and field.parent is not None:
            Clock.schedule_once(lambda _dt: self.reveal(field))
        self._reveal_signature = signature

    def reveal(self, field):
        if not field.focus or field.parent is None:
            return
        region = getattr(field, "focus_region", field)
        scroll, content = self.app.scroll, self.app.content
        top = content.to_widget(*region.to_window(region.x, region.top))[1]
        overflow = content.height - scroll.height
        if overflow > 0:
            scroll.scroll_y = max(0, min(1, (top + dp(8) - scroll.height) / overflow))
            scroll.update_from_scroll()

    def window_focus(self, _window, focused):
        if not focused:
            for widget in self.shell.walk():
                if isinstance(widget, SystemButton):
                    widget.cancel()
            self.app.dismiss_keyboard()

    def close(self):
        self.event.cancel()
        Window.unbind(children=self.changed, size=self.event, on_focus=self.window_focus)
        self.app.scroll.unbind(size=self.event)
        for keyboard in self.keyboards:
            keyboard.unbind(size=self.event, pos=self.event)


def paste_into(field):
    if field is not None and field.focus:
        field.paste()


def button(text, callback, danger=False):
    widget = SystemButton(text=tr._(text))
    if danger:
        widget.background_color = theme.DANGER
    widget.bind(on_release=lambda *_args: callback())
    return widget
