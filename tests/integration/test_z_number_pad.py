from unittest.mock import Mock, patch

import pytest
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup

from carveracontroller.ui.editing import EditingTextInput
from tests.integration.conftest import pump_frames, set_window_size


@pytest.mark.parametrize('window_size', [(1280, 720), (800, 480)])
def test_probing_number_pad_preserves_the_workspace(mobile, window_size):
    from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

    app, layout = mobile
    set_window_size(window_size)
    layout.update()
    popup = ProbingPopup(app.root.controller)
    popup.open(animation=False)
    pump_frames(20)
    field = next(widget for widget in popup.ids.tabbedpanelid.current_tab.content.walk()
                 if isinstance(widget, EditingTextInput))
    panel = popup.ids.jog_panel
    original = tuple(popup.pos), tuple(popup.size), tuple(field.to_window(*field.pos)), panel.height
    commands = list(app.simulation.commands)
    try:
        with patch.object(Window, 'request_keyboard') as native, patch.object(layout, 'size_controls') as sizing:
            field.focus = True
            pump_frames(16)
            pad = field._number_pad
            assert pad._is_open
            assert not isinstance(pad, ModalView)
            x, _y = field.to_window(*field.pos)
            right, _top = field.to_window(field.right, field.top)
            if window_size[0] == 1280:
                assert pad.right <= x or pad.x >= right
            native.assert_not_called()
            sizing.assert_not_called()
            assert app.android_keyboard_height == 0
            assert (tuple(popup.pos), tuple(popup.size), tuple(field.to_window(*field.pos)), panel.height) == original
            pad.press('cancel')
            pump_frames(12)
            sizing.assert_not_called()
        assert app.simulation.commands == commands
    finally:
        popup.dismiss(animation=False)


@pytest.mark.parametrize('policy', ['integer', 'decimal'])
def test_number_pad_applies_only_a_complete_draft(mobile, policy):
    app, _layout = mobile
    field = EditingTextInput(text='12', input_policy=policy, multiline=False)
    popup = Popup(content=field)
    popup.open(animation=False)
    pump_frames(12)
    validated = Mock()
    field.bind(on_text_validate=validated)
    commands = list(app.simulation.commands)
    field.focus = True
    pump_frames(8)
    pad = field._number_pad
    try:
        pad.press('3')
        assert pad.display.text == '3'
        assert field.text == '12'
        pad.press('back')
        pad.press('sign')
        assert pad.keys['apply'].disabled
        pad.press('apply')
        assert pad._is_open
        pad.press('4')
        pad.press('.')
        assert pad.display.text == ('-4' if policy == 'integer' else '-4.')
        pad.press('5')
        pad.press('apply')
        assert field.text == ('-45' if policy == 'integer' else '-4.5')
        assert not pad._is_open
        assert field._number_pad is None
        validated.assert_not_called()
        assert app.simulation.commands == commands
    finally:
        pad.dismiss(animation=False)
        popup.dismiss(animation=False)


def test_number_pad_cancel_and_back_leave_the_original_value(mobile):
    app, layout = mobile
    field = EditingTextInput(text='2.5', input_filter='float')
    popup = Popup(content=field)
    popup.open(animation=False)
    pump_frames(12)
    try:
        for action in ('cancel', 'back'):
            field.focus = True
            pump_frames(8)
            pad = field._number_pad
            pad.press('clear')
            pad.press('7')
            if action == 'cancel':
                pad.press('cancel')
            else:
                assert layout.back()
            pump_frames(8)
            assert field.text == '2.5'
            assert not pad._is_open
        field.focus = True
        pump_frames(8)
        field._number_pad.press('clear')
        field._number_pad.press('apply')
        assert field.text == ''
    finally:
        popup.dismiss(animation=False)


@pytest.mark.parametrize('fontscale', [1, 2])
def test_number_pad_fits_compact_landscape(mobile, fontscale):
    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, fontscale
    app.touch_target = dp(48)
    layout.update()
    field = EditingTextInput(input_filter='float')
    popup = Popup(content=field)
    popup.open(animation=False)
    pump_frames(16)
    field.focus = True
    pump_frames(16)
    pad = field._number_pad
    try:
        assert pad.x >= 0 and pad.y >= 0
        assert pad.right <= Window.width and pad.top <= Window.height
        for button in pad.keys.values():
            assert button.height >= app.touch_target
            assert button.width >= app.touch_target
            assert button.x >= pad.x and button.y >= pad.y
            assert button.right <= pad.right and button.top <= pad.top
    finally:
        pad.dismiss(animation=False)
        popup.dismiss(animation=False)


def test_text_fields_and_desktop_numbers_keep_keyboard_entry(mobile):
    app, _layout = mobile
    text = EditingTextInput(input_policy='gcode')
    number = EditingTextInput(input_policy='decimal')
    with patch('kivy.uix.textinput.TextInput._bind_keyboard') as native:
        text._bind_keyboard()
        native.assert_called_once()
        native.reset_mock()
        number._bind_keyboard()
        native.assert_not_called()
        app.android_touch = False
        number._bind_keyboard()
        native.assert_called_once()


def test_closing_the_owner_also_closes_the_number_pad(mobile):
    field = EditingTextInput(text='12', input_filter='float')
    popup = Popup(content=field)
    popup.open(animation=False)
    pump_frames(12)
    field.focus = True
    pump_frames(8)
    pad = field._number_pad
    pad.press('7')
    popup.dismiss(animation=False)
    pump_frames(8)
    assert not pad._is_open
    assert field._number_pad is None
    assert field.text == '12'


def test_number_pad_dismisses_on_outside_touch_without_consuming_it(mobile):
    from tests.unit.test_touch import finger

    field = EditingTextInput(text='12', input_filter='float')
    popup = Popup(content=field)
    popup.open(animation=False)
    pump_frames(12)
    field.focus = True
    pump_frames(8)
    pad = field._number_pad
    try:
        pad.press('7')
        assert not pad.on_touch_down(finger(pad.x - 1, pad.y - 1))
        assert not pad._is_open
        assert field.text == '12'
    finally:
        popup.dismiss(animation=False)


def test_switching_from_text_entry_closes_the_system_keyboard(mobile):
    app, _layout = mobile
    field = EditingTextInput(text='12', input_filter='float')
    popup = Popup(content=field)
    popup.open(animation=False)
    pump_frames(12)
    app.android_keyboard_height = 200
    try:
        with patch.object(Window, 'release_all_keyboards') as release, patch.object(Window, 'request_keyboard') as request:
            field.focus = True
            pump_frames(12)
            release.assert_called_once()
            request.assert_not_called()
            assert field._number_pad._is_open
        field._number_pad.press('cancel')
    finally:
        app.android_keyboard_height = 0
        popup.dismiss(animation=False)
