"""Compact settings navigation, search and vertically arranged values."""

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.settings import SettingItem, SettingTitle
from kivy.uix.spinner import Spinner
from kivy.utils import escape_markup

from carveracontroller.translation import tr

from .android_layout import DialogActions, DialogLabel, DialogSurface, _text_width, control_height
from .editing import EditingTextInput


class MobileSettings:
    def __init__(self, settings, popup):
        self.settings, self.popup = settings, popup
        self.app = App.get_running_app()
        self.interface = settings.interface
        self.content = next(child for child in self.interface.children if child == self.interface.content)
        self._rows = {}
        self._filter = Clock.create_trigger(self.filter, .15)
        column = BoxLayout(orientation="vertical", spacing=dp(8))
        self.interface.remove_widget(self.content)
        self.navigation = BoxLayout(size_hint_y=None, spacing=dp(8))
        self.categories = Spinner(font_size=sp(16))
        self.categories.bind(text=self.choose_category)
        self.navigation.add_widget(self.categories)
        self.search_button = Button(text=tr._("Search"), size_hint_x=None)
        self.search_button.bind(on_release=self.toggle_search)
        self.navigation.add_widget(self.search_button)
        close = Button(text=tr._("Close"), size_hint_x=None, width=dp(96))
        close.bind(on_release=self.close)
        self.close_button = close
        self.navigation.add_widget(close)
        self.search = EditingTextInput(hint_text=tr._("Search settings"), multiline=False,
                                       size_hint_y=None, height=control_height())
        self.search_open = False
        self.search.bind(text=self._filter, focus=self.reflow)
        self.search_row = BoxLayout(size_hint_y=None, spacing=dp(8))
        self.search_row.add_widget(self.search)
        self._keyboard_buttons = []
        apply = getattr(popup, "btn_apply", None)
        if apply is not None:
            apply = next(child for child in apply.parent.children if child == apply)
            apply.parent._mobile_keyboard_secondary = True
            self._keyboard_buttons.append((apply, apply.parent, apply.parent.children.index(apply)))
        self._keyboard_buttons.append((close, self.navigation, self.navigation.children.index(close)))
        self.navigation._mobile_keyboard_secondary = True
        self.popup.ids.mobile_settings_search = self.search
        column.add_widget(self.navigation)
        column.add_widget(self.search_row)
        self.empty = DialogLabel()
        column.add_widget(self.empty)
        column.add_widget(self.content)
        self.interface.add_widget(column)
        self.app.bind(compact_layout=self.reflow, android_keyboard_height=self.reflow)
        Metrics.bind(density=self.reflow, fontscale=self.reflow)
        self.content.bind(current_uid=self.sync_category)
        self.refresh()

    def refresh(self):
        self.names = {}
        for uid, panel in self.content.panels.items():
            if not getattr(panel, "_mobile_search_bound", False):
                panel.bind(children=self._filter)
                panel._mobile_search_bound = True
            name = panel.title
            suffix = 2
            while name in self.names:
                name = f"{panel.title} ({suffix})"
                suffix += 1
            self.names[name] = uid
            self._remember_rows(panel)
        self.categories.values = list(self.names)
        current = self.content.current_uid
        self.categories.text = next((name for name, uid in self.names.items() if uid == current), next(iter(self.names), ""))
        self.reflow()
        self.filter()

    def _remember_rows(self, panel):
        for item in panel.children:
            if item not in self._rows:
                self._rows[item] = (item.height, item.disabled)
                item._search_hidden = False
                item._mobile_category_title = ((isinstance(item, SettingTitle) and item.title == panel.title)
                    or (type(item) is Label and item.text == panel.title))
                item.bind(height=self._keep_hidden)
                if isinstance(item, SettingItem):
                    self._stack_value(item)

    def choose_category(self, _spinner, title):
        if title in getattr(self, "names", {}):
            self.interface.menu.selected_uid = self.names[title]

    def sync_category(self, *_args):
        for name, uid in getattr(self, "names", {}).items():
            if uid == self.content.current_uid:
                self.categories.text = name
                break

    def reflow(self, *_args):
        self.sync_category()
        compact = self.app.compact_layout
        self.interface.menu.width = 0 if compact else dp(200)
        self.interface.menu.opacity = 0 if compact else 1
        self.interface.menu.disabled = compact
        self.navigation.height = control_height() if compact else 0
        self.navigation.opacity = 1 if compact else 0
        self.navigation.disabled = not compact
        for button in (self.search_button, self.close_button):
            button.width = max(self.app.touch_target, _text_width(button.text, button.font_name, sp(16)) + dp(24))
        visible = not compact or self.search_open or bool(self.search.text) or self.search.focus
        available = Window.height - max(self.app.android_keyboard_height, self.app.safe_area_padding[3]) - self.app.safe_area_padding[1]
        tight = self.search.focus and bool(self.app.android_keyboard_height) and available < control_height() * 3 + dp(60)
        for button, parent, index in self._keyboard_buttons:
            destination = self.search_row if tight else parent
            if button.parent != destination:
                if button.parent is not None:
                    button.parent.remove_widget(button)
                destination.add_widget(button, index=0 if tight else min(index, len(destination.children)))
        self.search.size_hint = (1, 1)
        self.search_row.height = control_height() if visible else 0
        self.search.opacity = int(visible)
        self.search.disabled = not visible
        for item in self._rows:
            if isinstance(item, SettingItem) and hasattr(item, "_mobile_fit"):
                item._mobile_fit()
        self.filter()

    def close(self, *_args):
        self.search.focus = False
        self.popup.dismiss()

    def toggle_search(self, *_args):
        self.search_open = not self.search_open
        if not self.search_open:
            self.search.focus = False
        self.reflow()
        if self.search_open:
            self.search.focus = True

    def _stack_value(self, item):
        label = item.ids.get("labellayout")
        if label is None:
            return
        label.parent.spacing = dp(8)
        label.size_hint = (1, None)
        label.font_size = sp(16)
        label.halign = "left"
        label.valign = "middle"
        parent = item.content.parent
        content = next(child for child in parent.children if child == item.content)
        index = parent.children.index(content)
        parent.remove_widget(content)
        value_row = BoxLayout(size_hint_y=None, spacing=dp(8))
        value_row.add_widget(content)
        info = Button(text=tr._("Info"), size_hint_x=None)
        def show_info(*_args):
            surface = DialogSurface(orientation="vertical", padding=dp(12))
            surface.add_widget(DialogLabel(text=item.desc or item.title))
            actions = DialogActions()
            close = Button(text=tr._("Close"))
            actions.add_widget(close)
            surface.add_widget(actions)
            sheet = Popup(title=item.title, content=surface)
            close.bind(on_release=lambda *_: sheet.dismiss())
            sheet.open()
        info.bind(on_release=show_info)
        value_row.add_widget(info)
        parent.add_widget(value_row, index=index)
        item._mobile_value_row = value_row
        item._mobile_info = info
        def wording(*_args):
            text = f"[b]{escape_markup(item.title or '')}[/b]"
            if not (self.app.compact_layout and Metrics.fontscale > 1.25):
                text += f"\n[size=14sp][color=aaaaaa]{escape_markup(item.desc or '')}[/color][/size]"
            label.text = text
        item.bind(title=wording, desc=wording)
        wording()
        label.bind(width=lambda widget, width: setattr(widget, "text_size", (max(1, width - dp(24)), None)))
        item.content.size_hint = (1, 1)
        def fit(*_args):
            wording()
            stacked = item.width < dp(260) * max(1, Metrics.fontscale)
            label.parent.orientation = "vertical" if stacked else "horizontal"
            label.size_hint_x = 1
            info_visible = self.app.compact_layout and Metrics.fontscale > 1.25 and bool(item.desc)
            info.width = max(self.app.touch_target, sp(16)*3) if info_visible else 0
            info.opacity = int(info_visible)
            info.disabled = not info_visible
            value_row.size_hint_x = 1 if stacked else None
            value_row.width = max(dp(160), sp(16) * 8) + info.width
            value_row.height = control_height()
            label.height = label.texture_size[1] + dp(12)
            desired = (label.height + value_row.height if stacked else max(label.height, value_row.height)) + dp(12)
            if item._search_hidden:
                self._rows[item] = (desired, self._rows[item][1])
                item.height = 0
            else:
                item.height = desired
        label.bind(texture_size=fit)
        item.bind(width=fit)
        item._mobile_fit = fit
        fit()

    def _keep_hidden(self, item, height):
        if item._search_hidden and height:
            item.height = 0

    def filter(self, *_args):
        query = self.search.text.strip().casefold()
        matching = set()
        for uid, panel in self.content.panels.items():
            self._remember_rows(panel)
            for item in panel.children:
                title, desc = (getattr(item, "title", "") or ""), (getattr(item, "desc", "") or "")
                visible = (not query or query in (title + " " + desc).casefold()) and not (self.app.compact_layout and item._mobile_category_title)
                hidden = not visible
                if hidden != item._search_hidden:
                    if hidden:
                        self._rows[item] = (item.height, item.disabled)
                    item._search_hidden = hidden
                    item.height = 0 if hidden else self._rows[item][0]
                    item.opacity = 0 if hidden else 1
                    item.disabled = True if hidden else self._rows[item][1]
                    item.size_hint_min_y = 0 if hidden else self.app.touch_target
                if visible:
                    matching.add(uid)
        if query and matching and self.content.current_uid not in matching:
            uid = next(uid for uid in self.names.values() if uid in matching)
            self.categories.text = next(name for name, value in self.names.items() if value == uid)
        self.empty.text = tr._("No settings match this search.") if query and not matching else ""
