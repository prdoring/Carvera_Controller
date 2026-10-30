"""Android touch sizing, keyboard space, help and Back navigation."""

import weakref
from functools import lru_cache

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import Metrics, dp, sp
from kivy.properties import BooleanProperty, ObjectProperty, OptionProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.settings import SettingItem
from kivy.uix.slider import Slider
from kivy.uix.splitter import Splitter
from kivy.uix.switch import Switch
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelHeader
from kivy.uix.textinput import TextInput

from carveracontroller.runtime_profile import is_kiosk
from carveracontroller.translation import tr

from . import theme
from .scrolling import configure_scroll_view
from .touch import JogStepSpinner, JogTouchButton, TapBehavior


@lru_cache(maxsize=256)
def _text_width(text, font, size, bold=False):
    label = CoreLabel(text=text, font_name=font, font_size=size, bold=bold)
    label.refresh()
    return label.texture.size[0]


def control_height():
    """One readable line with padding and a full touch target."""
    app = App.get_running_app()
    return max(app.touch_target if app else dp(48), sp(16) * 1.25 + dp(12))


def _focus_changed(field, focused):
    layout = getattr(App.get_running_app(), "_touch_layout", None)
    if focused and layout is not None:
        layout.focus_field(field)
        layout._dialogs_update()


def style_action(button, role="secondary", *, explicit=True):
    if not isinstance(button, Button):
        return
    if explicit:
        button._mobile_action_role = role
    role = getattr(button, "_mobile_action_role", role)
    button.background_normal = "data/theme/button.png"
    button.background_down = "data/theme/button-down.png"
    button.background_color = {"primary": theme.SELECTED, "danger": theme.DANGER}.get(role, theme.CONTROL)
    if type(button).__name__ != "TopDataView":
        button.color = (0, 0, 0, 0) if type(button).__name__ == "IconButton" else theme.TEXT


def style_field(field):
    if getattr(field, "_mobile_style", False):
        return
    field._mobile_style = True
    field.background_normal = field.background_disabled_normal = "data/theme/field.png"
    field.background_active = "data/theme/field-focus.png"
    field.background_color = theme.FIELD
    field.foreground_color = theme.TEXT
    field.disabled_foreground_color = theme.MUTED
    field.hint_text_color = theme.MUTED
    field.cursor_color = theme.ACCENT


def fit_tabs(panel):
    width = sum(max(dp(96), _text_width(tab.text, tab.font_name, sp(16)) + dp(24))
                for tab in panel.tab_list)
    return width <= panel.width - dp(8)


def fit_form_grid(grid):
    """Let each form row accommodate its own wrapped wording."""
    if getattr(grid, "_mobile_form_fitted", False):
        return
    grid._mobile_form_fitted = True
    grid.row_force_default = False
    grid.row_default_height = control_height()
    for cell in grid.children:
        cell.size_hint_y = None
        labels = [item for item in cell.walk(restrict=True) if isinstance(item, Label)]
        def resize(*_args, cell=cell, labels=labels):
            if getattr(cell, "_mobile_stacked_form", False):
                cell.height = cell.minimum_height
            else:
                cell.height = max([control_height()] + [item.texture_size[1] + dp(12) for item in labels if item.text])
        if isinstance(cell, BoxLayout):
            cell.bind(minimum_height=resize)
        for label in labels:
            Builder.unbind_property(label, "text_size")
            label.text_size = (max(1, label.width - dp(16)), None)
            label.bind(width=lambda item, value: setattr(item, "text_size", (max(1, value - dp(16)), None)))
            label.bind(texture_size=resize)
        resize()


def fit_scroll_view(view):
    configure_scroll_view(view)
    if getattr(view, "_mobile_scroll_bound", False):
        return
    view._mobile_scroll_bound = True
    body = [None]
    def update(*_args):
        child = view.children[0] if view.children else None
        if body[0] is not child:
            if body[0] is not None:
                body[0].unbind(height=update)
            body[0] = child
            if child is not None:
                child.bind(height=update)
        if child is not None and child.size_hint_y is None:
            view.do_scroll_y = child.height > view.height + 1
    view.bind(height=update, children=update)
    update()


def style_splitter(view):
    strip = view._strip
    if strip is None or getattr(strip, "_mobile_divider", False):
        return
    strip._mobile_divider = True
    strip.background_normal = strip.background_down = strip.background_disabled_normal = ""
    strip.background_color = (0, 0, 0, 0)
    for child in strip.children:
        if isinstance(child, Image):
            child.opacity = 0


class DisclosurePanel(BoxLayout):
    """Keep hidden toolbar children out of the surrounding touch area."""

    def on_touch_down(self, touch):
        if not self.opacity or not self.height or not self.collide_point(*touch.pos):
            return False
        return super().on_touch_down(touch)


class TouchActionRow(GridLayout):
    """Action buttons wrap into full touch rows on a narrow interface."""

    stacked = BooleanProperty(False)

    def __init__(self, **kwargs):
        kwargs.setdefault("rows", None)
        super().__init__(**kwargs)
        self.bind(width=self._columns, children=self._columns, stacked=self._columns,
                  padding=self._columns, spacing=self._columns)
        self.bind(minimum_height=self.setter("height"))
        self.size_hint_y = None
        self._columns()

    def _columns(self, *_args):
        app = App.get_running_app()
        mobile = app is not None and app.android_touch
        width = max([app.touch_target if mobile else dp(48)] + [
            _text_width(str(getattr(child, "main_text", child.text)), getattr(child, "font_name", "Roboto"), sp(16), getattr(child, "bold", False)) + dp(24)
            for child in self.children if mobile and hasattr(child, "text")])
        available = max(1, self.width - self.padding[0] - self.padding[2])
        self.cols = (1 if self.stacked else max(1, min(len(self.children) or 1,
                     int((available + self.spacing[0]) / (width + self.spacing[0]))))) if mobile else (1 if self.stacked else max(1, len(self.children)))
        widths = None
        self.cols_minimum = {}
        if mobile and not self.stacked and self.cols < len(self.children):
            children = list(reversed(self.children))
            needed = [max(app.touch_target, _text_width(str(getattr(child, "main_text", getattr(child, "text", ""))),
                      getattr(child, "font_name", "Roboto"), sp(16)) + dp(24)) for child in children]
            for columns in range(len(children), self.cols, -1):
                minimums = [max(needed[column::columns]) for column in range(columns)]
                spare = available - sum(minimums) - self.spacing[0] * (columns - 1)
                if spare >= 0:
                    self.cols = columns
                    self.cols_minimum = dict(enumerate(minimums))
                    widths = [value + spare / columns for value in minimums]
                    break
        self.row_force_default = True
        self.row_default_height = control_height() if mobile else dp(40)
        if mobile:
            for index, child in enumerate(reversed(self.children)):
                help_slot = type(child).__name__ == "HelpButton" or (isinstance(child, BoxLayout)
                            and len(child.children) == 1 and type(child.children[0]).__name__ == "HelpButton")
                child.size_hint_x = None if help_slot else 1
                if help_slot:
                    child.width = max(app.touch_target, dp(72), sp(16) * 4)
                if isinstance(child, Button):
                    child.font_size = sp(16)
                    column_width = widths[index % self.cols] if widths else (available - self.spacing[0] * (self.cols - 1)) / self.cols
                    child.text_size = (max(1, column_width - dp(24)), None)
                    child.halign = "center"
                    child.valign = "middle"
                    child.texture_update()
                    self.row_default_height = max(self.row_default_height, child.texture_size[1] + dp(16))


class DialogActions(TouchActionRow):
    """Fixed actions, outside the dialog's scrolling body."""


class DialogLabel(Label):
    """Full wording that grows vertically instead of shrinking or clipping."""

    text_role = OptionProperty("body", options=("body", "secondary", "title"))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(width=self._fit, texture_size=self._fit, text=self._fit, text_role=self._fit)
        self._fit()

    def _fit(self, *_args):
        app = App.get_running_app()
        if app is not None and app.android_touch:
            Builder.unbind_property(self, "text_size")
            self.size_hint_y = None
            self.font_size = sp(18 if self.bold or self.text_role == "title" else 14 if self.text_role == "secondary" else 16)
            self.text_size = (max(1, self.width - dp(16)), None)
            self.height = self.texture_size[1] + dp(8) if self.text else 0
            self.halign = "left"
            self.valign = "middle"


class DialogSurface(BoxLayout):
    """An explicitly managed dialog with a content viewport and fixed footer."""

    presentation = OptionProperty("content", options=("content", "workspace"))
    body = ObjectProperty(None, allownone=True)
    actions = ObjectProperty(None, allownone=True)

    def on_parent(self, *_args):
        Clock.schedule_once(self._prepare_attached, -1)

    def _prepare_attached(self, _dt):
        app = App.get_running_app()
        if app is not None and app.android_touch and self.get_root_window() is not None:
            self.prepare()
            layout = getattr(app, "_touch_layout", None)
            if layout is not None:
                layout._update()

    def prepare(self):
        if getattr(self, "_prepared", False):
            return
        self._prepared = True
        self.orientation = "vertical"
        self.spacing = dp(8)
        children = list(reversed(self.children))
        if not children:
            return
        footer = next((item for item in children if isinstance(item, DialogActions)), None)
        if footer is not None:
            children.remove(footer)
        self.clear_widgets()
        content = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        viewport = ScrollView(do_scroll_x=False)
        self.body, self.actions = content, footer
        self.viewport = viewport
        viewport.bind(height=lambda *_: setattr(viewport, "do_scroll_y", content.height > viewport.height + 1))
        content.bind(height=lambda *_: setattr(viewport, "do_scroll_y", content.height > viewport.height + 1))
        for child in children:
            self._natural_height(child)
            content.add_widget(child)
        viewport.add_widget(content)
        self.add_widget(viewport)
        if footer is not None:
            self.add_widget(footer)
        content.bind(height=self._changed)
        if footer is not None:
            footer.bind(height=self._changed)

    def _changed(self, *_args):
        app = App.get_running_app()
        layout = getattr(app, "_touch_layout", None)
        if layout is not None:
            layout._dialogs_update()

    def _natural_height(self, widget):
        if isinstance(widget, DialogLabel):
            widget._fit()
            return
        if isinstance(widget, ScrollView):
            return
        if isinstance(widget, BoxLayout) and widget.orientation == "vertical":
            for child in widget.children:
                self._natural_height(child)
            widget.size_hint_y = None
            widget.bind(minimum_height=widget.setter("height"))
            widget.height = widget.minimum_height
        elif isinstance(widget, GridLayout) and not isinstance(widget, TouchActionRow):
            widget.size_hint_y = None
            widget.row_force_default = True
            widget.row_default_height = max(control_height(), getattr(widget, "_content_row_height", 0))
            widget.bind(minimum_height=widget.setter("height"))
        elif isinstance(widget, BoxLayout):
            widget.size_hint_y = None
            widget.height = control_height() if widget.children else 0
        elif isinstance(widget, Label):
            widget.size_hint_y = None
            widget.text_size = (max(1, widget.width - dp(8)), None)
            widget.bind(width=lambda item, width: setattr(item, "text_size", (max(1, width - dp(8)), None)))
            widget.bind(texture_size=lambda item, size: setattr(item, "height", size[1] + dp(12) if item.text else 0))
            widget.height = widget.texture_size[1] + dp(12) if widget.text else 0


class AndroidTouchLayout:
    def __init__(self, app):
        self.app = app
        self.dialogs = weakref.WeakKeyDictionary()
        self._update = Clock.create_trigger(self.update, -1)
        self._dialogs_update = Clock.create_trigger(self.resize_dialogs, -1)
        self._history = []
        if not hasattr(app.root, "_mobile_root_keyboard_state"):
            app.root._mobile_root_keyboard_state = {}
        self._root_keyboard_state = app.root._mobile_root_keyboard_state
        self._last_page = app.root.content.current
        browse = app.root.ids.get("main_file_button")
        self._footer = browse.parent if browse is not None else None
        self._footer_spacing = self._footer.spacing if self._footer is not None else 0
        if self._footer is not None:
            self._footer.bind(width=self._update)
        self._window_content = tuple(Window.children)
        Window.bind(children=self._window_children, size=self._update, on_resize=self._update)
        Metrics.bind(density=self._update, fontscale=self._update)
        app.bind(android_keyboard_height=self._dialogs_update, safe_area_padding=self._update)
        app.root.content.bind(current=self._page_changed)
        self.size_controls(app.root)
        self._update()

    def _page_changed(self, _manager, page):
        if page != self._last_page:
            self._history.append(self._last_page)
            self._last_page = page

    def _window_children(self, _window, children):
        content = tuple(child for child in children if not getattr(child, "_mobile_number_pad", False))
        if content != self._window_content:
            self._window_content = content
            self._update()

    def _action_width(self, button):
        if is_kiosk() and button.icon:
            return max(self.app.touch_target, dp(50))
        return max(self.app.touch_target, _text_width(button.android_label, button.font_name, sp(16)) + dp(16))

    def size_controls(self, root):
        target = self.app.touch_target
        if root == self.app.root:
            browse = root.ids.get("main_file_button")
            if browse is not None:
                required = sum(self._action_width(button)
                               for button in browse.parent.children if getattr(button, "android_label", "")
                               and (not button.disabled or button.android_label == tr._("Stop")))
                required += root.ids.main_page_button.width + dp(16)
                browse._mobile_overflow_hidden = self.app.compact_layout and required + dp(120) > browse.parent.width
        for widget in root.walk(restrict=True):
            if isinstance(widget, TabbedPanelHeader):
                widget.size_hint_min_y = target
            if getattr(widget, "android_label", ""):
                visible = not self.app.compact_layout or not widget.disabled or widget.android_label == tr._("Stop")
                visible = visible and not getattr(widget, "_mobile_overflow_hidden", False)
                widget.opacity = int(visible)
                if not visible:
                    widget.size_hint_min_x = 0
                    widget.width = 0
                    continue
            if not widget.opacity or not widget.height or not widget.width:
                if getattr(widget, "android_label", "") and widget.opacity:
                    widget.width = target
                else:
                    continue
            if getattr(widget, "android_label", ""):
                if not is_kiosk() or not widget.icon:
                    widget.text = widget.android_label
                    widget.icon = ""
                widget.width = self._action_width(widget)
                style_action(widget, "danger" if widget.android_label in (tr._("Stop"), tr._("Abort")) else "secondary")
            if isinstance(widget, (ButtonBehavior, TextInput, Slider, Switch, SettingItem, TapBehavior)):
                if not hasattr(widget, "_mobile_minimum_dp"):
                    widget._mobile_minimum_dp = ((widget.size_hint_min_x or 0) / dp(1), (widget.size_hint_min_y or 0) / dp(1))
                    widget._mobile_dimensions_dp = (widget.width / dp(1), widget.height / dp(1))
                minimum_x, minimum_y = widget._mobile_minimum_dp
                widget.size_hint_min_x = max(minimum_x * dp(1), target)
                widget.size_hint_min_y = max(minimum_y * dp(1), target)
                if widget.size_hint_y is None and widget.height and not isinstance(widget, SettingItem) and not isinstance(widget.parent, RecycleBoxLayout) and not getattr(widget.parent, "_mobile_form_fitted", False):
                    if isinstance(widget, TextInput) and widget.multiline:
                        desired = max(control_height(), widget._mobile_dimensions_dp[1] * dp(1))
                        ancestor = widget.parent
                        while ancestor is not None and ancestor != Window and not isinstance(ancestor, ScrollView):
                            ancestor = ancestor.parent
                        if widget.focus and self.app.android_keyboard_height and isinstance(ancestor, ScrollView):
                            desired = min(desired, max(control_height(), ancestor.height - dp(16)))
                        widget.height = desired
                    else:
                        widget.height = max(control_height(), widget.texture_size[1] + dp(16)) if isinstance(widget, Button) and widget.text else control_height()
                if widget.size_hint_x is None and widget.width and not getattr(widget, "android_label", ""):
                    text_width = _text_width(widget.text, widget.font_name, sp(16)) + dp(24) if isinstance(widget, Button) and widget.text else 0
                    width_text = getattr(widget, "_mobile_width_text", "")
                    if width_text:
                        text_width = max(text_width, _text_width(width_text, widget.font_name, sp(16))
                                         + sum(widget.padding[::2]) + dp(12))
                    widget.width = max(widget._mobile_dimensions_dp[0] * dp(1), target, text_width)
                if isinstance(widget, TextInput):
                    if widget.input_filter in ("int", "float") or getattr(widget, "input_policy", "") in ("integer", "decimal"):
                        widget.multiline = False
                        Builder.unbind_property(widget, "height")
                        widget.size_hint_y = None
                        widget.pos_hint = {**widget.pos_hint, "center_y": .5}
                        widget.height = max(control_height(), widget.line_height + dp(8))
                        if not getattr(widget, "_mobile_numeric_height_bound", False):
                            def fit_number(item, *_args):
                                item.height = max(control_height(), item.line_height + dp(8))
                            widget.bind(line_height=fit_number, padding=fit_number)
                            widget._mobile_numeric_height_bound = True
                    widget._mobile_text_sp = 16
                    widget.font_size = sp(widget._mobile_text_sp)
                    style_field(widget)
                    if not getattr(widget, "_mobile_focus_bound", False):
                        widget.bind(focus=_focus_changed)
                        widget._mobile_focus_bound = True
                if isinstance(widget, Button) and widget.text:
                    widget._mobile_text_sp = 20 if isinstance(widget, (JogTouchButton, JogStepSpinner)) else 14 if getattr(widget, "_compact_auxiliary", False) else 16
                    widget.font_size = sp(widget._mobile_text_sp)
                    widget.text_size = (max(1, widget.width - dp(4 if getattr(widget, "_compact_auxiliary", False) else 12)), None)
                    if not getattr(widget, "_mobile_wrap_bound", False):
                        widget.bind(width=lambda item, width: setattr(item, "text_size", (max(1, width - dp(4 if getattr(item, "_compact_auxiliary", False) else 12)), None)))
                        widget.bind(texture_size=lambda item, size: setattr(item, "height", max(control_height(), size[1] + dp(16))) if item.size_hint_y is None else None)
                        widget._mobile_wrap_bound = True
                    widget.halign = "center"
                    widget.valign = "middle"
            if isinstance(widget, TouchActionRow):
                widget._columns()
            elif isinstance(widget, GridLayout) and widget.row_force_default:
                if hasattr(widget, "_content_row_height"):
                    widget.row_default_height = max(control_height(), widget._content_row_height)
                else:
                    if not hasattr(widget, "_mobile_row_height_dp"):
                        widget._mobile_row_height_dp = widget.row_default_height / dp(1)
                    widget.row_default_height = max(control_height(), widget._mobile_row_height_dp * dp(1))
            if isinstance(widget, RecycleBoxLayout):
                width, height = widget.default_size
                if height is not None:
                    widget.default_size = (width, max(height, target))
            if isinstance(widget, ScrollView):
                fit_scroll_view(widget)
            if isinstance(widget, Splitter):
                widget.strip_size = target
                style_splitter(widget)
            if isinstance(widget, TabbedPanel):
                widget.tab_height = 0 if getattr(widget, "mobile_selector", None) is not None and not widget._tab_layout.opacity else max(widget.tab_height, target)
            if isinstance(widget, Label) and widget.text and not getattr(widget, "_mobile_preserve_font", False):
                if isinstance(widget, DialogLabel):
                    widget._fit()
                    continue
                widget._mobile_text_sp = getattr(widget, "_mobile_text_sp", 18 if widget.bold else 14 if widget.font_size < sp(15) else 16)
                widget.font_size = sp(widget._mobile_text_sp)

        if root == self.app.root and self._footer is not None:
            footer = self._footer
            fixed = sum(child.width for child in footer.children if child.size_hint_x is None)
            remaining = footer.width - fixed - sum(footer.padding[::2]) - dp(1)
            footer.spacing = min(dp(2), max(0, remaining / max(1, len(footer.children) - 1)))

    def _keyboard_space(self, modal, state, tight):
        collapsed = state.setdefault("keyboard_collapsed", {})
        candidates = [widget for widget in modal.walk(restrict=True) if getattr(widget, "_mobile_keyboard_secondary", False)]
        if isinstance(modal, Popup):
            frame = modal._container.parent
            candidates += [widget for widget in frame.children if widget != modal._container]
            if not hasattr(frame, "_mobile_frame_padding_dp"):
                frame._mobile_frame_padding_dp = [value / dp(1) for value in frame.padding]
            original = state.setdefault("frame_padding_dp", frame._mobile_frame_padding_dp)
            frame.padding = [dp(4)] * 4 if tight else [value * dp(1) for value in original]
        if tight:
            positions = [(widget, widget.parent, widget.parent.children.index(widget))
                         for widget in candidates if widget.parent is not None]
            for widget, parent, index in positions:
                collapsed.setdefault(widget, (parent, index))
                parent.remove_widget(widget)
        else:
            for widget, (parent, index) in sorted(collapsed.items(), key=lambda item: item[1][1]):
                if widget.parent is None:
                    parent.add_widget(widget, index=min(index, len(parent.children)))
            collapsed.clear()
        padded = list(state.get("surfaces", []))
        padded += [widget for widget in modal.children if isinstance(widget, BoxLayout) and widget not in padded]
        if isinstance(modal, Popup) and isinstance(modal.content, BoxLayout) and modal.content not in padded:
            padded.append(modal.content)
        padded += [widget for widget in modal.walk(restrict=True) if isinstance(widget, BoxLayout)
                   and getattr(widget, "_mobile_keyboard_padding", False) and widget not in padded]
        saved = state.setdefault("keyboard_padding", {})
        for surface in padded:
            if not hasattr(surface, "_mobile_keyboard_spacing_dp"):
                surface._mobile_keyboard_spacing_dp = ([value / dp(1) for value in surface.padding], surface.spacing / dp(1))
            original = saved.setdefault(surface, surface._mobile_keyboard_spacing_dp)
            surface.padding = [min(value, 4) * dp(1) for value in original[0]] if tight else [value * dp(1) for value in original[0]]
            surface.spacing = min(original[1], 4) * dp(1) if tight else original[1] * dp(1)
        tabs = state.setdefault("keyboard_tab_padding", {})
        for panel in (widget for widget in modal.walk(restrict=True) if isinstance(widget, TabbedPanel)):
            if not hasattr(panel, "_mobile_keyboard_tab_padding_dp"):
                panel._mobile_keyboard_tab_padding_dp = [value / dp(1) for value in panel.padding]
            original = tabs.setdefault(panel, panel._mobile_keyboard_tab_padding_dp)
            panel.padding = [dp(2)] * 4 if tight else [value * dp(1) for value in original]

    def _prepare_dialog(self, modal):
        from .mobile_tools import prepare_tool_dialog

        prepare_tool_dialog(modal, self.app)
        if type(modal).__name__ == "WCSSettingsPopup":
            for widget in modal.walk(restrict=True):
                if isinstance(widget, Button) and widget.text == tr._("Clear All"):
                    widget._mobile_keyboard_secondary = True
                if type(widget).__name__ == "HelpButton":
                    widget.parent._mobile_keyboard_secondary = True
                if type(widget) is Label and widget.text == tr._("WCS Settings"):
                    widget._mobile_keyboard_secondary = True
        if isinstance(modal, Popup) and type(modal.content).__name__ == "LocalFilePickerSheet":
            modal.content.prepare_mobile_layout(modal)
        if isinstance(modal, Popup):
            modal.title_size = sp(18)
            for widget in modal._container.parent.children:
                if isinstance(widget, Label):
                    widget._mobile_text_sp = 18
                    widget.bind(texture_size=self._dialogs_update)
        self.size_controls(modal)
        primary = {tr._(word) for word in ("Apply", "Apply offsets", "Confirm", "Run", "Generate", "Save", "Open", "Use value", "Ok")}
        for widget in modal.walk(restrict=True):
            if type(widget) is Button:
                style_action(widget, "primary" if widget.text in primary else "secondary", explicit=False)
        state = {"size_hint_y": modal.size_hint_y, "size_hint_x": modal.size_hint_x,
                 "height": modal.height, "width": modal.width, "pos_hint": dict(modal.pos_hint)}
        self.dialogs[modal] = state
        if isinstance(modal, Popup):
            state["measured_labels"] = tuple(widget for widget in modal._container.parent.children if isinstance(widget, Label))
        if type(modal).__name__ == "ConfirmPopup":
            state["measured_labels"] = (modal.lb_title, modal.lb_content)
            for label in state["measured_labels"]:
                label.bind(texture_size=self._dialogs_update)
        jog_panel = modal.ids.get("jog_panel")
        if jog_panel is not None and type(modal).__name__ != "ProbingPopup":
            state["jog_panel"] = (jog_panel, jog_panel.height)
        state["drafts"] = {}
        def remember_drafts(_dt):
            if modal.__class__.__name__ in ("SetXPopup", "SetYPopup", "SetZPopup", "SetAPopup",
                                            "MoveAPopup", "SetToolPopup", "ChangeToolPopup", "WCSSettingsPopup"):
                state["drafts"] = {field: field.text for field in modal.walk(restrict=True) if isinstance(field, TextInput)
                                   and not getattr(field, "saves_immediately", False)}
        draft_event = Clock.schedule_once(remember_drafts, 0.2)
        modal_ref = weakref.ref(modal)
        def dismissed(*_args):
            draft_event.cancel()
            Clock.schedule_once(cleanup, .3)
        def cleanup(_dt):
            target = modal_ref()
            if target is None or target._is_open or self.dialogs.get(target) is not state:
                return
            for field in target.walk(restrict=True):
                if isinstance(field, TextInput):
                    field.focus = False
            self._keyboard_space(target, state, False)
            for label in state.get("measured_labels", ()):
                label.unbind(texture_size=self._dialogs_update)
            self.dialogs.pop(target, None)
            target.unbind(on_dismiss=dismissed)
            target.size_hint = (state["size_hint_x"], state["size_hint_y"])
            target.size = (state["width"], state["height"])
            target.pos_hint = state["pos_hint"]
        modal.bind(on_dismiss=dismissed)
        surfaces = [w for w in modal.walk(restrict=True) if isinstance(w, DialogSurface)]
        if surfaces:
            for surface in surfaces:
                surface.prepare()
            state["managed"] = True
            state["surfaces"] = surfaces
            return
        # Existing tabbed and split-pane forms own their scrolling.

    def update(self, _dt=0):
        left, top, right, bottom = self.app.safe_area_padding
        width = max(1, Window.width - left - right)
        available = max(1, Window.height - top - bottom)
        self.app.root.size_hint = (None, None)
        self.app.root.pos = (left, bottom)
        self.app.root.size = (width, available)
        text_scale = max(1, Metrics.fontscale)
        self.app.compact_layout = width / dp(1) / text_scale < 960 or available / dp(1) / text_scale < 560
        self._keyboard_space(self.app.root, self._root_keyboard_state, False)
        self.size_controls(self.app.root)
        for modal in list(Window.children):
            if isinstance(modal, ModalView) and not getattr(modal, "_mobile_number_pad", False):
                if modal not in self.dialogs:
                    self._prepare_dialog(modal)
                self.size_controls(modal)
        self.resize_dialogs()

    def resize_dialogs(self, _dt=0):
        keyboard = self.app.android_keyboard_height
        left, top, right, bottom = self.app.safe_area_padding
        bottom = max(bottom, keyboard)
        width = max(1, Window.width - left - right)
        available = max(1, Window.height - top - bottom)
        tight = bool(keyboard) and available < control_height() * 3 + dp(60)
        modals = [widget for widget in Window.children if isinstance(widget, ModalView)
                  and not getattr(widget, "_mobile_number_pad", False)]
        if keyboard:
            modals = modals[:1]
        for modal in modals:
            if modal not in self.dialogs:
                self._prepare_dialog(modal)
            state = self.dialogs[modal]
            if keyboard and not state.get("keyboard_adapted", False):
                focused = next((field for field in modal.walk(restrict=True) if isinstance(field, TextInput) and field.focus), None)
                if focused is not None and focused.to_window(*focused.pos)[1] >= keyboard + dp(8):
                    state["keyboard_overlay"] = True
                    self.focus_field(focused)
                    continue
                if focused is None and state.get("keyboard_overlay", False):
                    continue
                state["keyboard_adapted"] = True
            elif not keyboard:
                state["keyboard_adapted"] = state["keyboard_overlay"] = False
            self._keyboard_space(modal, state, tight)
            if "jog_panel" in state:
                panel, height = state["jog_panel"]
                if keyboard and panel.height:
                    from .touch import cancel_jog

                    cancel_jog()
                panel.height = 0 if keyboard else height
                panel.opacity = 0 if keyboard else 1
                panel.disabled = bool(keyboard)
            # ModalView adds another fbind on every open, including reused dialogs.
            for name in ("center", "size"):
                for callback in modal.get_property_observers(name):
                    if callback == modal._align_center:
                        modal.funbind(name, callback)
            Window.unbind(on_resize=modal._align_center, on_keyboard=modal._handle_keyboard)
            modal.size_hint_y = None
            desired = state["height"] if state["size_hint_y"] is None else Window.height * state["size_hint_y"]
            modal.size_hint_x = None
            workspace = type(modal).__name__ in ("ConfigPopup", "CoordPopup", "WCSSettingsPopup", "FilePopup",
                "ProbingPopup", "CMMWorkbenchPopup", "FacingWizardPopup", "DiagnosePopup")
            workspace = workspace or any(surface.presentation == "workspace" for surface in state.get("surfaces", []))
            workspace = workspace or getattr(modal, "_mobile_workspace", False)
            margin = dp(8 if tight else 16)
            full_width = workspace or getattr(modal, "_mobile_full_width", False)
            modal.width = max(1, width - margin) if full_width and self.app.compact_layout else min(width - margin, max(dp(420), width * .8))
            if workspace:
                desired = available - margin if self.app.compact_layout else available * .9
            elif type(modal).__name__ == "ConfirmPopup":
                desired = modal.lb_title.texture_size[1] + modal.lb_content.texture_size[1]
                desired += modal.ids.confirm_actions.height + dp(62)
            elif state.get("surfaces"):
                surface = state["surfaces"][0]
                desired = (surface.body.height if surface.body is not None else 0) + (surface.actions.height if surface.actions else 0)
                desired += sum(surface.padding[1::2]) + surface.spacing
                if isinstance(modal, Popup):
                    frame = modal._container.parent
                    desired += sum(frame.padding[1::2]) + sum(child.height for child in frame.children if child != modal._container)
                else:
                    desired += dp(16)
            modal.height = max(1, min(desired, available - margin))
            modal.pos_hint = {}
            modal.center = (left + width / 2, bottom + available / 2)
            for field in modal.walk(restrict=True):
                if isinstance(field, TextInput) and field.focus:
                    self.focus_field(field)

    def focus_field(self, field):
        def contain(view):
            if not field.focus or field.get_root_window() is None or not view.children:
                return
            overflow = view.children[0].height - view.height
            if overflow <= 0:
                return
            _, bottom = view.to_window(*view.pos)
            _, y = field.to_window(*field.pos)
            movement = max(0, bottom - y) if y < bottom else min(0, bottom + view.height - y - field.height)
            if movement:
                view.scroll_y = max(0, min(1, view.scroll_y - movement / overflow))

        def reveal(_dt):
            if not field.focus or field.get_root_window() is None:
                return
            parent = field.parent
            while parent is not None and parent is not Window:
                if isinstance(parent, ScrollView):
                    Clock.schedule_once(lambda _dt, view=parent: contain(view), 0)
                parent = parent.parent

        if not hasattr(field, "_mobile_geometry_reveal"):
            field._mobile_geometry_reveal = Clock.create_trigger(reveal, 0)
            field._mobile_reveal_geometry = set()
        parent = field.parent
        while parent is not None and parent is not Window:
            if isinstance(parent, ScrollView):
                if parent not in field._mobile_reveal_geometry:
                    parent.bind(pos=field._mobile_geometry_reveal, size=field._mobile_geometry_reveal)
                    field._mobile_reveal_geometry.add(parent)
                if parent.children and parent.children[0] not in field._mobile_reveal_geometry:
                    body = parent.children[0]
                    body.bind(height=field._mobile_geometry_reveal)
                    field._mobile_reveal_geometry.add(body)
            parent = parent.parent
        field._mobile_geometry_reveal()
        if any(event.is_triggered for event in getattr(field, "_mobile_reveal_events", [])):
            return
        field._mobile_reveal_events = [Clock.schedule_once(reveal, .15), Clock.schedule_once(reveal, .35)]

    def back(self):
        number_pad = next((child for child in Window.children if getattr(child, "_mobile_number_pad", False)), None)
        if number_pad is not None:
            number_pad.dismiss()
            return True
        if self.app.android_keyboard_height:
            Window.release_all_keyboards()
            return True
        modals = [child for child in Window.children if isinstance(child, ModalView)]
        if modals:
            modal = modals[0]
            root = self.app.root
            if modal is getattr(root, "progress_popup", None) or getattr(modal, "is_probing", False):
                return True
            if self.app.playing or self.app.state not in ("Idle", "N/A", "Sleep", "Alarm"):
                return True
            # Each form retains its own apply/discard and operation-cancellation policy.
            drafts = self.dialogs.get(modal, {}).get("drafts", {})
            if any(field.text != original for field, original in drafts.items()):
                self._confirm_discard(modal, drafts)
                return True
            modal.dismiss()
            return True
        if self.app.playing or self.app.state not in ("Idle", "N/A", "Sleep", "Alarm"):
            return True
        if self._history:
            page = self._history.pop()
            self._last_page = page
            self.app.root.content.current = page
            return True
        confirm = self.app.root.confirm_popup
        confirm.lb_title.text = tr._("Exit controller?")
        confirm.lb_content.text = tr._("Close the controller application?")
        confirm.confirm = lambda *_: self.app.stop()
        confirm.cancel = None
        confirm.open()
        return True

    def _confirm_discard(self, modal, drafts):
        actions = BoxLayout(spacing=dp(8))
        prompt = Popup(title=tr._("Discard unapplied edits?"), content=actions,
                       size_hint=(0.7, None), height=dp(160), auto_dismiss=False)
        keep = Button(text=tr._("Keep editing"))
        discard = Button(text=tr._("Discard"))
        keep.bind(on_release=lambda *_: prompt.dismiss())
        def discard_edits(*_args):
            for field, original in drafts.items():
                field.text = original
            prompt.dismiss()
            modal.dismiss()
        discard.bind(on_release=discard_edits)
        actions.add_widget(keep)
        actions.add_widget(discard)
        prompt.open()

    def show_help(self, source=None, *, introduction="", documentation=None):
        from .help_images import ViewportHelpImage

        modals = [child for child in Window.children if isinstance(child, ModalView)]
        source = source or (modals[0] if modals else self.app.root)
        entries, seen = [], set()
        for widget in source.walk(restrict=True):
            text = getattr(widget, "tooltip_txt", "")
            for image in dict.fromkeys((getattr(widget, "tooltip_image", ""), getattr(widget, "overview_image", ""))):
                key = (text, image)
                if (not text and not image) or key in seen or not widget.opacity or not widget.width or not widget.height:
                    continue
                seen.add(key)
                entries.append((getattr(widget, "text", ""), text, image))
        scroll = ScrollView(do_scroll_x=False, bar_width=dp(3))
        images = []
        listing = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(16), padding=dp(12))
        listing.bind(minimum_height=listing.setter("height"))
        if introduction:
            listing.add_widget(DialogLabel(text=introduction))
        cards = GridLayout(cols=1, spacing=dp(16), size_hint_y=None)
        cards.bind(minimum_height=cards.setter("height"))
        def columns(_grid, width):
            cards.cols = max(1, min(2, int(width / max(dp(280), sp(16) * 15))))
        cards.bind(width=columns)
        for title, text, image in entries:
            card = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
            card.bind(minimum_height=card.setter("height"))
            if image:
                picture = ViewportHelpImage(viewport=scroll, image_path=image)
                images.append(picture)
                card.add_widget(picture)
            if title or text:
                label = Label(text=(title + "\n" if title else "") + text, size_hint_y=None,
                              text_size=(None, None), halign="left", valign="top", font_size=sp(16))
                label.bind(width=lambda item, width: setattr(item, "text_size", (width, None)))
                label.bind(texture_size=lambda item, size: setattr(item, "height", size[1] + dp(12)))
                card.add_widget(label)
            cards.add_widget(card)
        listing.add_widget(cards)
        if not entries and not introduction:
            listing.add_widget(DialogLabel(text=tr._("No additional help for this screen.")))
        scroll.add_widget(listing)
        surface = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        surface.add_widget(scroll)
        footer = DialogActions()
        if documentation is not None:
            if documentation.parent is not None:
                documentation.parent.remove_widget(documentation)
            footer.add_widget(documentation)
        close = Button(text=tr._("Close"))
        footer.add_widget(close)
        surface.add_widget(footer)
        popup = Popup(title=tr._("Control help"), content=surface, size_hint=(0.9, 0.92))
        popup._mobile_workspace = True
        close.bind(on_release=lambda *_: popup.dismiss())
        def release_images(*_args):
            for picture in images:
                picture.close()
        popup.bind(on_dismiss=release_images)
        popup.open()
        return popup

    def stop(self):
        for state in self.dialogs.values():
            for label in state.get("measured_labels", ()):
                label.unbind(texture_size=self._dialogs_update)
        self._keyboard_space(self.app.root, self._root_keyboard_state, False)
        self._update.cancel()
        self._dialogs_update.cancel()
        if self._footer is not None:
            self._footer.unbind(width=self._update)
            self._footer.spacing = self._footer_spacing
        Window.unbind(children=self._window_children, size=self._update, on_resize=self._update)
        Metrics.unbind(density=self._update, fontscale=self._update)
        self.app.unbind(android_keyboard_height=self._dialogs_update, safe_area_padding=self._update)
        self.app.root.content.unbind(current=self._page_changed)
