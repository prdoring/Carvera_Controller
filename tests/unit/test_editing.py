from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from kivy.clock import Clock

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.addons.probing.operations.drafts import ProbeSettingsDraft
from carveracontroller.ui.editing import EditingTextInput, is_complete_number, keyboard_flags
from carveracontroller.ui.widget_helpers import bind_auto_select_to_text_input


@pytest.mark.parametrize("text,valid", [("-", False), ("-.", False), ("", False), ("-12.5", True),
    ("0", True), ("nan", False), ("inf", False), ("1e9999", False), ("12x", False)])
def test_numeric_drafts(text, valid):
    widget = EditingTextInput(input_filter="float", text=text)
    assert widget.draft_valid is valid
    assert is_complete_number(text) is valid


def test_numeric_keyboard_includes_sign_and_decimal_flags():
    assert keyboard_flags("decimal") & 0x1000
    assert keyboard_flags("decimal") & 0x2000
    assert not keyboard_flags("integer") & 0x2000
    assert keyboard_flags("gcode") & 0x80000
    assert keyboard_flags("filename") & 0x80000


def test_integer_validation_does_not_round_or_accept_fractional_notation():
    assert is_complete_number("9007199254740993", integer=True)
    assert not is_complete_number("1.0", integer=True)
    assert not is_complete_number("1e2", integer=True)


def test_select_all_is_bound_once_and_blur_cancels_it():
    widget = EditingTextInput(text="123")
    widget.select_all = Mock()
    for _ in range(3):
        bind_auto_select_to_text_input(widget)
    widget.focus = True
    Clock.tick()
    widget.select_all.assert_called_once()
    widget.focus = False
    widget.select_all.reset_mock()
    widget.focus = True
    widget.focus = False
    Clock.tick()
    widget.select_all.assert_not_called()


def test_text_edit_cancels_pending_select_all():
    widget = EditingTextInput(text="123")
    widget.select_all = Mock()
    bind_auto_select_to_text_input(widget)
    widget.focus = True
    widget.text = "1234"
    Clock.tick()
    widget.select_all.assert_not_called()
    widget.focus = False


def test_invalid_probe_draft_is_visible_to_validation_without_being_saved():
    class Settings(ProbeSettingsDraft):
        parameter_definitions = SimpleNamespace(distance=SimpleNamespace(code="X"))
        config = {"X": "10"}

        def setting_changed(self, key, value):
            self.config[self.parameter_definitions.distance.code] = value

    settings = Settings()
    settings.draft_changed("distance", "-")
    assert not settings.commit_draft("distance")
    assert settings.config == {"X": "10"}
    assert settings.draft_config() == {"X": "-"}
    settings.draft_changed("distance", "-2.5")
    assert settings.draft_config() == {"X": "-2.5"}
    assert settings.config == {"X": "-2.5"}


def test_probe_saves_are_coalesced_and_snapshot_the_committed_values():
    with patch.object(ConfigUtils, "_pending", {}), patch.object(ConfigUtils, "_writer") as writer:
        values = {"X": "1"}
        ConfigUtils.schedule_save(values, "test.json")
        values["X"] = "2"
        ConfigUtils.schedule_save(values, "test.json")
        values["X"] = "3"
        ConfigUtils.flush_saves()
        writer.submit.assert_called_once_with(ConfigUtils.save_config, {"X": "2"}, "test.json")
