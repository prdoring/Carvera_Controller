"""Text-entry policy shared by Android fields and desktop editors."""

import math

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, OptionProperty
from kivy.uix.textinput import TextInput
from kivy.utils import platform


def is_complete_number(text, integer=False, allow_empty=False):
    text = str(text).strip()
    if not text:
        return allow_empty
    try:
        if integer:
            int(text)
            return True
        value = float(text)
        return math.isfinite(value)
    except (ValueError, TypeError, OverflowError):
        return False


def keyboard_flags(policy):
    if policy == "integer":
        return 2 | 0x1000  # TYPE_CLASS_NUMBER | TYPE_NUMBER_FLAG_SIGNED
    if policy == "decimal":
        return 2 | 0x1000 | 0x2000  # signed decimal
    if policy in ("gcode", "filename"):
        return 1 | 0x80000  # text without suggestions or capitalization flags
    return 1


class EditingTextInput(TextInput):
    input_policy = OptionProperty("auto", options=("auto", "text", "filename", "gcode", "integer", "decimal"))
    saves_immediately = BooleanProperty(False)
    draft_valid = BooleanProperty(True)
    validation_error = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._keyboard_event = None
        super().__init__(**kwargs)
        self.bind(text=self._validate_draft, input_filter=self._validate_draft, focus=self._editing_focus)
        self._validate_draft()

    def effective_policy(self):
        if self.input_policy != "auto":
            return self.input_policy
        if self.input_filter == "int":
            return "integer"
        if self.input_filter == "float":
            return "decimal"
        return "text"

    def _validate_draft(self, *_args):
        policy = self.effective_policy()
        self.draft_valid = policy not in ("integer", "decimal") or is_complete_number(
            self.text, integer=policy == "integer"
        )
        if self.draft_valid:
            self.validation_error = False

    def _bind_keyboard(self):
        if self._uses_number_pad():
            return
        if platform == "android":
            policy = self.effective_policy()
            self.input_type = "number" if policy in ("integer", "decimal") else "text"
            self.keyboard_suggestions = policy == "text"
        super()._bind_keyboard()

    def _uses_number_pad(self):
        app = App.get_running_app()
        return bool(app and app.android_touch and not self.readonly
                    and self.effective_policy() in ("integer", "decimal"))

    def _editing_focus(self, _widget, focused):
        if self._keyboard_event is not None:
            self._keyboard_event.cancel()
            self._keyboard_event = None
        self.validation_error = not focused and not self.draft_valid and bool(self.text.strip())
        if focused and self._uses_number_pad():
            self._keyboard_event = Clock.schedule_once(self._open_number_pad, 0)
            return
        if focused and getattr(App.get_running_app(), "touch_mode", False):
            layout = getattr(App.get_running_app(), "_touch_layout", None)
            if layout is not None:
                layout.focus_field(self)
            if platform == "android":
                self._keyboard_event = Clock.schedule_once(self._configure_android_keyboard, 0)

    def _open_number_pad(self, _dt):
        self._keyboard_event = None
        if not self.focus or self.disabled or self.get_root_window() is None:
            return
        from .number_pad import NumberPad

        if App.get_running_app().android_keyboard_height:
            from kivy.core.window import Window

            Window.release_all_keyboards()
        self.focus = False
        self._number_pad = NumberPad(self)
        self._number_pad.open(animation=False)

    def _configure_android_keyboard(self, _dt):
        self._keyboard_event = None
        app = App.get_running_app()
        bridge = getattr(app, "_android_input", None)
        if self.focus and bridge is not None:
            bridge.api.setKeyboardType(keyboard_flags(self.effective_policy()))

