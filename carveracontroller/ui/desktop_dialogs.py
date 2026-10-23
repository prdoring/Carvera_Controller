"""Content-sized desktop messages and editors with fixed dialog actions."""

import math
import weakref

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

from carveracontroller.translation import tr

from . import theme
from .android_layout import DialogActions, DialogSurface, TouchActionRow, style_action, style_field


class DesktopDialogLayout:
    """Fit short dialogs without replacing fields, action bindings or drafts."""

    SHORT_DIALOGS = {
        "ConfirmPopup", "InputPopup", "ManualWifiPopup", "UnlockPopup", "MessagePopup",
        "ReconnectionPopup", "ProgressPopup", "LanguagePopup", "PairingPopup",
        "SelectAndCalibrateProbePopup", "SetXPopup", "SetYPopup", "SetZPopup", "SetAPopup",
        "MoveAPopup", "SetToolPopup", "ChangeToolPopup", "SetRotationPopup", "ProbingPreviewPopup",
    }
    EXCLUDED_CONTENT = {
        "ColorPicker", "LocalFilePickerSheet", "PickFilePopup", "TabbedPanel", "RecycleView",
        "FileChooserListView", "FileChooserIconView",
    }

    def __init__(self, app):
        self.app = app
        self.dialogs = weakref.WeakKeyDictionary()
        self._update = Clock.create_trigger(self.update, 0)
        Window.bind(children=self._update, size=self._update)
        Metrics.bind(density=self._update, fontscale=self._update)
        self._update()

    def _root(self, modal):
        if isinstance(modal, Popup):
            return modal.content
        return next((child for child in modal.children if isinstance(child, BoxLayout)), None)

    def _eligible(self, modal):
        if type(modal).__name__ in self.SHORT_DIALOGS:
            return True
        if type(modal) is not Popup or getattr(modal, "_mobile_workspace", False):
            return False
        root = self._root(modal)
        if not isinstance(root, BoxLayout):
            return False
        widgets = list(root.walk(restrict=True))
        if any(type(widget).__name__ in self.EXCLUDED_CONTENT for widget in widgets):
            return False
        if any(isinstance(widget, DialogSurface) and widget.presentation == "workspace" for widget in widgets):
            return False
        return (not any(isinstance(widget, ScrollView) for widget in widgets)
                or hasattr(root, "_desktop_content")
                or isinstance(root, DialogSurface) and getattr(root, "_prepared", False))

    def _prepare(self, modal):
        root = self._root(modal)
        state = {"root": root, "bindings": []}
        fields = [widget for widget in modal.walk(restrict=True) if isinstance(widget, TextInput) and widget.focus]
        if type(modal).__name__ != "ConfirmPopup":
            if isinstance(root, DialogSurface):
                root.prepare()
                state.update(body=root.body, viewport=root.viewport, actions=root.actions)
            elif hasattr(root, "_desktop_content"):
                state.update(root._desktop_content)
            else:
                children = list(reversed(root.children))
                actions = next((child for child in children if isinstance(child, DialogActions)), None)
                if actions is None and children:
                    last = children[-1]
                    if isinstance(last, Button) or self._button_row(last):
                        actions = last
                body = BoxLayout(orientation="vertical", spacing=dp(16), size_hint_y=None)
                viewport = ScrollView(do_scroll_x=False, do_scroll_y=False)
                root.clear_widgets()
                for child in children:
                    if child is not actions:
                        body.add_widget(child)
                viewport.add_widget(body)
                root.add_widget(viewport)
                if actions is not None:
                    root.add_widget(actions)
                root._desktop_content = {"body": body, "viewport": viewport, "actions": actions}
                state.update(root._desktop_content)
        for widget in modal.walk(restrict=True):
            if isinstance(widget, Label):
                widget.bind(text=self._update)
                state["bindings"].append((widget, "text"))
                if isinstance(widget, ToggleButton):
                    widget.bind(state=self._update)
                    state["bindings"].append((widget, "state"))
        if fields:
            def restore_focus(_dt):
                if modal in Window.children:
                    for field in fields:
                        field.focus = True
            Clock.schedule_once(restore_focus, 0)
        if isinstance(modal, Popup):
            modal._container.bind(size=self._update)
            state["bindings"].append((modal._container, "size"))
        self.dialogs[modal] = state
        return state

    @staticmethod
    def _button_row(widget):
        return isinstance(widget, BoxLayout) and bool(widget.children) and all(
            isinstance(child, Button) or type(child).__name__ == "HelpButton"
            for child in widget.children
        )

    @staticmethod
    def _measure(label, width):
        core = CoreLabel(text=label.text, font_name=label.font_name, font_size=label.font_size,
                         bold=label.bold, text_size=(max(1, width), None), markup=label.markup)
        core.refresh()
        return core.texture.size[1]

    def _label(self, label, width, title=False):
        Builder.unbind_property(label, "text_size")
        Builder.unbind_property(label, "height")
        label.font_name = theme.font_for(label.text)
        label.font_size = sp(22 if title else 18)
        label.halign = "left"
        label.valign = "middle"
        label.text_size = (max(1, width), None)
        label.size_hint_y = None
        label.height = self._measure(label, width) + dp(8) if label.text else 0
        return label.height

    def _button(self, button, width):
        button.font_name = theme.font_for(button.text)
        button.font_size = sp(18)
        Builder.unbind_property(button, "text_size")
        button.text_size = (max(1, width - dp(24)), None)
        button.halign = "center"
        button.valign = "middle"
        primary = button.text in {tr._(text) for text in ("Ok", "Confirm", "Save", "Use value")}
        primary = primary or isinstance(button, ToggleButton) and button.state == "down"
        style_action(button, "primary" if primary else "secondary", explicit=False)
        return max(dp(48), self._measure(button, width - dp(24)) + dp(20))

    def _action_row(self, row, width, stacked=False):
        if not getattr(row, "_desktop_sized", False):
            row.unbind(width=row._columns, children=row._columns, stacked=row._columns,
                       padding=row._columns, spacing=row._columns)
            row._desktop_sized = True
        row.spacing = dp(8)
        row.cols = 1 if stacked else max(1, len(row.children))
        row.rows = None
        row.row_force_default = True
        available = max(1, width - row.padding[0] - row.padding[2] - row.spacing[0] * (row.cols - 1))
        help_slots = [child for child in row.children if type(child).__name__ == "HelpButton"
                      or isinstance(child, BoxLayout) and len(child.children) == 1
                      and type(child.children[0]).__name__ == "HelpButton"]
        help_width = dp(72) * len(help_slots)
        text_count = max(1, row.cols - int(bool(help_width)))
        cell_width = available if stacked else (available - help_width) / text_count
        height = dp(48)
        for child in row.children:
            if child in help_slots and not stacked:
                child.size_hint_x = None
                Builder.unbind_property(child, "width")
                child.width = dp(72)
                child.size_hint_min_x = 0
                child.size_hint_max_x = None
                if isinstance(child, BoxLayout) and type(child).__name__ != "HelpButton":
                    help_button = child.children[0]
                    Builder.unbind_property(help_button, "width")
                    help_button.size_hint = (1, 1)
                    help_button.size_hint_min_x = 0
                    help_button.size_hint_max_x = None
            else:
                child.size_hint_x = 1
            if isinstance(child, Button):
                height = max(height, self._button(child, cell_width))
        row.row_default_height = height
        row.size_hint_y = None
        count = math.ceil(len(row.children) / row.cols)
        row.height = count * height + max(0, count - 1) * row.spacing[1] + sum(row.padding[1::2])
        return row.height

    def _natural_height(self, widget, width, *, title=False, stacked=False):
        if isinstance(widget, TouchActionRow):
            return self._action_row(widget, width, stacked or widget.stacked)
        if isinstance(widget, Button):
            height = self._button(widget, width)
        elif isinstance(widget, Label):
            return self._label(widget, width, title)
        elif isinstance(widget, TextInput):
            style_field(widget)
            widget.font_size = sp(18)
            widget.padding = [dp(12), dp(12)]
            height = dp(260) if widget.multiline else max(dp(48), widget.line_height + dp(24))
        elif isinstance(widget, BoxLayout):
            if not widget.children:
                widget.padding = 0
                height = 0
            else:
                widget.spacing = dp(12)
                inner = max(1, width - sum(widget.padding[::2]))
                children = list(reversed(widget.children))
                if widget.orientation == "vertical":
                    heights = [self._natural_height(child, inner) for child in children]
                    height = sum(heights) + max(0, len(heights) - 1) * widget.spacing
                    height += sum(widget.padding[1::2])
                else:
                    if any(isinstance(child, TextInput) for child in children):
                        for child in children:
                            if isinstance(child, Label) and not isinstance(child, Button):
                                child.size_hint_x = None
                                child.width = min(dp(160), inner * .3)
                    fixed = sum(child.width for child in children if child.size_hint_x is None)
                    shares = sum(child.size_hint_x or 0 for child in children)
                    available = max(1, inner - fixed - widget.spacing * (len(children) - 1))
                    heights = [self._natural_height(child, child.width if child.size_hint_x is None else
                               available * child.size_hint_x / max(1, shares)) for child in children]
                    height = max(heights, default=0) + sum(widget.padding[1::2])
        elif isinstance(widget, GridLayout):
            columns = max(1, widget.cols or len(widget.children))
            cell_width = max(1, (width - sum(widget.padding[::2]) - widget.spacing[0] * (columns - 1)) / columns)
            heights = [self._natural_height(child, cell_width) for child in reversed(widget.children)]
            rows = [max(heights[index:index + columns]) for index in range(0, len(heights), columns)]
            height = sum(rows) + max(0, len(rows) - 1) * widget.spacing[1] + sum(widget.padding[1::2])
        elif type(widget).__name__ in ("Widget", "SettingSpacer"):
            height = 0
        else:
            height = widget.height if widget.size_hint_y is None else dp(48)
        widget.size_hint_y = None
        widget.height = height
        return height

    def _fit(self, modal, state):
        root = state["root"]
        widgets = list(root.walk(restrict=True))
        multiline = any(isinstance(widget, TextInput) and widget.multiline for widget in widgets)
        name = type(modal).__name__
        width = dp(900 if multiline else 740 if name in ("UnlockPopup", "SelectAndCalibrateProbePopup") else 680)
        width = max(1, min(width, Window.width - dp(48)))
        modal.size_hint = (None, None)
        modal.width = width
        modal.pos_hint = {}
        chrome = 0
        if isinstance(modal, Popup):
            modal.title_size = sp(22)
            modal.title_align = "left"
            frame = modal._container.parent
            frame.do_layout()
            for child in frame.children:
                if isinstance(child, Label):
                    child.texture_update()
            frame.do_layout()
            chrome = sum(frame.padding[1::2]) + frame.spacing[1] * max(0, len(frame.children) - 1)
            chrome += sum(child.height for child in frame.children if child != modal._container)
            width = modal._container.width
        root.orientation = "vertical"
        root.padding = dp(24)
        root.spacing = dp(16)
        inner = max(1, width - sum(root.padding[::2]))
        limit = max(dp(160), Window.height - dp(112))
        if name == "ConfirmPopup":
            title_height = self._label(modal.lb_title, inner, True)
            body_height = self._label(modal.lb_content, inner)
            actions = modal.ids.confirm_actions
            action_height = self._action_row(actions, inner)
            fixed = title_height + action_height + sum(root.padding[1::2]) + root.spacing * 2
            modal.content_scroll.size_hint_y = None
            modal.content_scroll.height = max(1, min(body_height, limit - fixed))
            desired = fixed + modal.content_scroll.height
        else:
            body, viewport, actions = state["body"], state["viewport"], state["actions"]
            body.spacing = dp(16)
            heights = []
            for index, child in enumerate(reversed(body.children)):
                is_title = (index == 0 and isinstance(child, Label) and not isinstance(modal, Popup)
                            and name not in ("MessagePopup", "ReconnectionPopup", "ProgressPopup"))
                stacked = name in ("UnlockPopup", "SelectAndCalibrateProbePopup") and isinstance(child, TouchActionRow)
                heights.append(self._natural_height(child, inner, title=is_title, stacked=stacked))
            body.height = sum(heights) + max(0, len(heights) - 1) * body.spacing
            action_height = self._natural_height(actions, inner) if actions is not None else 0
            fixed = chrome + sum(root.padding[1::2]) + (root.spacing if actions is not None else 0) + action_height
            viewport.size_hint_y = 1
            viewport.bar_width = dp(6)
            viewport.bar_color = theme.ACCENT
            viewport.bar_inactive_color = (*theme.MUTED[:3], .5)
            viewport.do_scroll_y = body.height > max(1, limit - fixed)
            desired = fixed + body.height
        modal.height = min(limit, max(dp(160), desired))
        modal.center = (Window.width / 2, Window.height / 2)
        if isinstance(modal, Popup):
            frame.do_layout()
            modal._container.do_layout()
        root.do_layout()

    def update(self, _dt=0):
        if self.app.android_touch:
            return
        opened = [child for child in Window.children if isinstance(child, ModalView)]
        for modal, state in list(self.dialogs.items()):
            if modal not in opened:
                self._detach(state)
                self.dialogs.pop(modal, None)
        for modal in opened:
            if modal in self.dialogs or self._eligible(modal):
                state = self.dialogs.get(modal) or self._prepare(modal)
                self._fit(modal, state)

    def _detach(self, state):
        for widget, property_name in state["bindings"]:
            widget.unbind(**{property_name: self._update})

    def stop(self):
        self._update.cancel()
        Window.unbind(children=self._update, size=self._update)
        Metrics.unbind(density=self._update, fontscale=self._update)
        for state in self.dialogs.values():
            self._detach(state)
        self.dialogs.clear()
