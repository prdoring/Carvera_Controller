"""Compact settings navigation, search and vertically arranged values."""

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.settings import SettingItem
from kivy.uix.spinner import Spinner
from kivy.utils import escape_markup

from carveracontroller.translation import tr

from .android_layout import DialogLabel
from .editing import EditingTextInput


class MobileSettings:
    def __init__(self, settings, popup):
        self.settings, self.popup = settings, popup
        self.app = App.get_running_app()
        self.interface = settings.interface
        self.content = self.interface.content
        self._rows = {}
        self._filter = Clock.create_trigger(self.filter, .15)
        column = BoxLayout(orientation="vertical", spacing=dp(8))
        self.interface.remove_widget(self.content)
        self.navigation = BoxLayout(size_hint_y=None, spacing=dp(8))
        self.categories = Spinner(font_size=sp(16))
        self.categories.bind(text=self.choose_category)
        self.navigation.add_widget(self.categories)
        close = Button(text=tr._("Close"), size_hint_x=None, width=dp(96))
        close.bind(on_release=lambda *_: popup.dismiss())
        self.navigation.add_widget(close)
        self.search = EditingTextInput(hint_text=tr._("Search settings"), multiline=False,
                                       size_hint_y=None, height=max(dp(48), sp(16) * 2 + dp(16)))
        self.search.bind(text=self._filter)
        self.popup.ids.mobile_settings_search = self.search
        column.add_widget(self.navigation)
        column.add_widget(self.search)
        self.empty = DialogLabel()
        column.add_widget(self.empty)
        column.add_widget(self.content)
        self.interface.add_widget(column)
        self.app.bind(compact_layout=self.reflow)
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
        self.navigation.height = max(dp(48), sp(16) * 2 + dp(16)) if compact else 0
        self.navigation.opacity = 1 if compact else 0
        self.navigation.disabled = not compact
        for item in self._rows:
            if isinstance(item, SettingItem):
                item.content.height = max(dp(56), sp(16) * 2 + dp(16))

    def _stack_value(self, item):
        label = item.ids.get("labellayout")
        if label is None:
            return
        label.parent.orientation = "vertical"
        label.parent.spacing = dp(8)
        label.size_hint = (1, None)
        label.font_size = sp(16)
        label.halign = "left"
        label.valign = "middle"
        def wording(*_args):
            label.text = f"[b]{escape_markup(item.title or '')}[/b]\n[size=14sp][color=aaaaaa]{escape_markup(item.desc or '')}[/color][/size]"
        item.bind(title=wording, desc=wording)
        wording()
        label.bind(width=lambda widget, width: setattr(widget, "text_size", (max(1, width - dp(24)), None)))
        item.content.size_hint = (1, None)
        item.content.height = max(dp(56), sp(16) * 2 + dp(16))
        def fit(*_args):
            label.height = label.texture_size[1] + dp(12)
            desired = label.height + item.content.height + dp(20)
            if item._search_hidden:
                self._rows[item] = (desired, self._rows[item][1])
                item.height = 0
            else:
                item.height = desired
        label.bind(texture_size=fit)
        item.content.bind(height=fit)
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
                visible = not query or query in (title + " " + desc).casefold()
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
