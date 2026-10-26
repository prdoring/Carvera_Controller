from unittest.mock import patch

from kivy.metrics import Metrics, dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from tests.integration.conftest import pump_frames, set_window_size


def test_keyboard_keeps_the_main_screen_and_preview_geometry(mobile):
    from carveracontroller.ui.mobile_main import MobileMainLayout

    app, layout = mobile
    set_window_size((1280, 720))
    Metrics.density = 1
    layout.update()
    main = MobileMainLayout(app)
    previous = app.root.content.current, app.show_preview
    try:
        app.root.content.current = 'File'
        app.show_preview = True
        pump_frames(12)
        root = tuple(app.root.pos), tuple(app.root.size), app.compact_layout
        preview = tuple(app.root.ids.float_layout.size)
        with patch.object(layout, 'size_controls', wraps=layout.size_controls) as sizing:
            app.android_keyboard_height = 300
            pump_frames(12)
            assert (tuple(app.root.pos), tuple(app.root.size), app.compact_layout) == root
            assert tuple(app.root.ids.float_layout.size) == preview
            assert sizing.call_count == 0
        app.android_keyboard_height = 0
        pump_frames(8)
        assert (tuple(app.root.pos), tuple(app.root.size), app.compact_layout) == root
    finally:
        app.android_keyboard_height = 0
        app.root.content.current, app.show_preview = previous
        main.stop()


def test_keyboard_does_not_remeasure_underlying_settings(mobile):
    app, layout = mobile
    popup = app.root.config_popup
    popup.open(animation=False)
    pump_frames(12)
    settings = popup._mobile_settings
    previous = settings.search_open
    try:
        if not settings.search_open:
            settings.toggle_search()
        settings.search.focus = True
        pump_frames(12)
        original_geometry = tuple(popup.pos), tuple(popup.size)
        with patch.object(layout, 'size_controls', wraps=layout.size_controls) as sizing, patch.object(settings, 'reflow') as reflow:
            app.android_keyboard_height = 240
            pump_frames(16)
            assert sizing.call_count == 0
            reflow.assert_not_called()
            assert (tuple(popup.pos), tuple(popup.size)) == original_geometry
    finally:
        settings.search.focus = False
        app.android_keyboard_height = 0
        if settings.search_open != previous:
            settings.toggle_search()


def test_keyboard_only_adapts_the_top_editor(mobile):
    app, _layout = mobile
    background = app.root.config_popup
    background.open(animation=False)
    pump_frames(12)
    field = TextInput(multiline=False)
    editor = Popup(title='Edit value', content=field, size_hint=(.6, .4))
    editor.open(animation=False)
    pump_frames(12)
    original = tuple(background.pos), tuple(background.size)
    try:
        field.focus = True
        _, bottom = field.to_window(*field.pos)
        app.android_keyboard_height = bottom + dp(40)
        pump_frames(12)
        assert (tuple(background.pos), tuple(background.size)) == original
        assert field.to_window(*field.pos)[1] >= app.android_keyboard_height
    finally:
        field.focus = False
        editor.dismiss(animation=False)


def test_mdi_input_moves_above_the_keyboard_without_changing_the_preview(mobile):
    app, layout = mobile
    set_window_size((1280, 720))
    layout.update()
    previous = app.root.content.current, app.root.cmd_manager.current, app.show_lines, app.show_preview
    app.root.content.current = 'File'
    app.root.cmd_manager.current = 'manual_cmd_page'
    app.show_lines = app.show_preview = True
    pump_frames(12)
    field = app.root.manual_cmd
    preview = tuple(app.root.ids.float_layout.size)
    commands = list(app.simulation.commands)
    try:
        field.focus = True
        app.android_keyboard_height = 240
        pump_frames(12)
        _, y = field.to_window(*field.pos)
        assert abs(y - 240 - dp(8)) < 1
        assert field.focus
        assert tuple(app.root.ids.float_layout.size) == preview
        assert app.simulation.commands == commands
    finally:
        field.focus = False
        app.android_keyboard_height = 0
        app.root.content.current, app.root.cmd_manager.current, app.show_lines, app.show_preview = previous


def test_switching_fields_checks_visibility_with_the_keyboard_already_open(mobile):
    from carveracontroller.ui.android_layout import DialogSurface, control_height

    app, _layout = mobile
    first = TextInput(multiline=False, size_hint_y=None, height=control_height())
    second = TextInput(multiline=False, size_hint_y=None, height=control_height())
    surface = DialogSurface()
    surface.add_widget(first)
    surface.add_widget(Widget(size_hint_y=None, height=dp(400)))
    surface.add_widget(second)
    popup = Popup(title='Edit fields', content=surface, size_hint=(.7, .8))
    popup.open(animation=False)
    pump_frames(16)
    original = tuple(popup.pos), tuple(popup.size)
    try:
        first.focus = True
        pump_frames(8)
        first_y = first.to_window(*first.pos)[1]
        second_y = second.to_window(*second.pos)[1]
        app.android_keyboard_height = (first_y + second_y) / 2
        pump_frames(12)
        assert (tuple(popup.pos), tuple(popup.size)) == original
        second.focus = True
        pump_frames(20)
        assert second.focus
        assert second.to_window(*second.pos)[1] >= app.android_keyboard_height
    finally:
        first.focus = second.focus = False
        app.android_keyboard_height = 0
        popup.dismiss(animation=False)
