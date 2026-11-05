"""Screensaver choices with stable saved values and a non-saving preview."""

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.settings import SettingItem

from carveracontroller.translation import tr

from .android_layout import DialogActions, DialogSurface
from .screensaver_patterns import STYLES, TIMEOUTS


def style_labels():
    return dict(
        zip(
            (*STYLES, "random"),
            (
                tr._("Workshop Clock"),
                tr._("Toolpath Trace"),
                tr._("Contour Map"),
                tr._("Isometric Block"),
                tr._("Orbit Lines"),
                tr._("Nut & Bolt"),
                tr._("Random rotation"),
            ),
        )
    )


class SettingScreensaver(SettingItem):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.button = Button()
        self.add_widget(self.button)
        self.button.bind(on_release=self.choose)
        self.bind(value=self.refresh)
        self.refresh()

    def choices(self):
        if self.key == "screensaver_style":
            return style_labels()
        return {
            str(value): tr._("Off") if value == 0 else tr._("{minutes} minutes").format(minutes=value)
            for value in TIMEOUTS
        }

    def refresh(self, *_):
        self.button.text = self.choices().get(str(self.value), str(self.value))

    def choose(self, *_):
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        popup = Popup(title=self.title, content=surface, size_hint=(0.9, 0.85))
        scroll = ScrollView()
        column = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        column.bind(minimum_height=column.setter("height"))
        for value, caption in self.choices().items():
            button = Button(text=caption, size_hint_y=None, height=max(dp(48), App.get_running_app().touch_target))

            def select(_button, selected=value):
                self.value = selected
                popup.dismiss()

            button.bind(on_release=select)
            column.add_widget(button)
        scroll.add_widget(column)
        surface.add_widget(scroll)
        actions = DialogActions()
        cancel = Button(text=tr._("Cancel"))
        cancel.bind(on_release=lambda *_: popup.dismiss())
        actions.add_widget(cancel)
        surface.add_widget(actions)
        popup.open()


class SettingScreensaverPreview(SettingItem):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        button = Button(text=tr._("Preview"))
        button.bind(on_release=self.preview)
        self.add_widget(button)

    def preview(self, *_):
        app = App.get_running_app()
        values = {
            item.key: item.value
            for item in app.root.config_popup._all_setting_items()
            if item.section == "carvera" and item.key.startswith("screensaver_")
        }
        if not app._screensaver.preview(values):
            popup = Popup(title=tr._("Screensaver unavailable"), size_hint=(0.8, 0.4))
            button = Button(text=tr._("Wait for the current operation to finish."))
            button.bind(on_release=popup.dismiss)
            popup.content = button
            popup.open()
