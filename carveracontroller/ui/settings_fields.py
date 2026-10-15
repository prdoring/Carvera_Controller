"""Settings editors using the same native keyboard policy as other fields."""

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.settings import SettingOptions, SettingString
from kivy.uix.widget import Widget

from carveracontroller.translation import tr

from .android_layout import DialogSurface, TouchActionRow
from .editing import EditingTextInput, is_complete_number
from .widget_helpers import bind_auto_select_to_text_input


class EditingSettingString(SettingString):
    def policy(self):
        return "filename" if any(part in self.key for part in ("path", "filename", "directory")) else "text"

    def _create_popup(self, _instance):
        content_cls = DialogSurface if App.get_running_app().android_touch else BoxLayout
        content = content_cls(orientation="vertical", spacing=dp(8), padding=dp(8))
        self.popup = Popup(title=self.title, content=content, size_hint=(None, None),
                           size=(min(Window.width * .95, dp(500)), dp(270)))
        policy = self.policy()
        self.textinput = EditingTextInput(text=str(self.value), input_policy=policy, multiline=False,
                                          size_hint_y=None, height=dp(48), font_size="20sp")
        if policy in ("integer", "decimal"):
            self.textinput.input_filter = "int" if policy == "integer" else "float"
        bind_auto_select_to_text_input(self.textinput)
        self.textinput.bind(on_text_validate=self._validate)
        content.add_widget(Widget())
        content.add_widget(self.textinput)
        content.add_widget(Widget())
        actions = TouchActionRow(spacing=dp(8))
        for title, callback in ((tr._("Cancel"), self._dismiss), (tr._("Ok"), self._validate)):
            button = Button(text=title)
            button.bind(on_release=callback)
            actions.add_widget(button)
        content.add_widget(actions)
        self.popup.open()


class EditingSettingNumeric(EditingSettingString):
    def policy(self):
        return "decimal" if "." in str(self.value) else "integer"

    def _validate(self, _instance):
        integer = self.policy() == "integer"
        text = self.textinput.text.strip()
        valid = is_complete_number(text, integer=integer)
        if valid and self.key == "android_ui_scale":
            valid = float(text) > 0
        if not valid:
            self.textinput.validation_error = True
            return
        self.value = str(int(text) if integer else float(text))
        self._dismiss()


class EditingSettingOptions(SettingOptions):
    def _create_popup(self, _instance):
        if not App.get_running_app().android_touch:
            return super()._create_popup(_instance)
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        self.popup = Popup(title=self.title, content=surface, size_hint=(.9, .85))
        options = TouchActionRow(stacked=True, spacing=dp(8))
        for value in self.options:
            button = Button(text=value)
            def choose(_button, selected=value):
                self.value = selected
                self.popup.dismiss()
            button.bind(on_release=choose)
            options.add_widget(button)
        surface.add_widget(options)
        actions = TouchActionRow()
        cancel = Button(text=tr._("Cancel"))
        cancel.bind(on_release=lambda *_: self.popup.dismiss())
        actions.add_widget(cancel)
        surface.add_widget(actions)
        self.popup.open()
