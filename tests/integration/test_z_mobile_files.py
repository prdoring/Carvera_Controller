import pytest
from kivy.core.window import Window
from kivy.metrics import Metrics
from kivy.uix.button import Button
from kivy.uix.popup import Popup

from tests.integration.conftest import pump_frames, set_window_size


@pytest.mark.parametrize('state', ['files', 'error', 'selecting'])
def test_enlarged_file_browser_keeps_the_list_and_footer_reachable(mobile, state):
    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    popup = app.root.file_popup
    popup.open(animation=False)
    pump_frames(18)
    page = popup._mobile_file_pages['remote']
    rv = page['rv']
    original = rv.browser_state, rv.touch_selection_mode, list(rv.data)
    try:
        rv.data = [{'filename': 'A long fixture name in the third setup.cnc', 'filedate': '2026-10-22 12:00',
                    'filesize': '123 KB', 'is_dir': False, 'rv_key': 0}]
        rv.browser_state = ('An interrupted folder request needs another attempt. ' * 12) if state == 'error' else ''
        rv.touch_selection_mode = state == 'selecting'
        pump_frames(20)
        assert page['body'].height >= rv.layout_manager.default_size[1]
        for control in [page['source'], page['menu'], page['path'], *page['footer'].children]:
            x, y = control.to_window(*control.pos)
            assert x >= popup.x - 1 and x + control.width <= popup.right + 1
            assert y >= popup.y - 1 and y + control.height <= popup.top + 1
            assert control.height >= app.touch_target
        if state == 'error':
            assert page['info'].do_scroll_y
            assert rv.height == 0
        if state == 'selecting':
            assert page['counter'].opacity == 1
            assert page['mode'].text == 'Done'
        if state != 'error':
            for row in rv.view_adapter.views.values():
                if row.parent is not None:
                    assert row.height >= rv.layout_manager.default_size[1] - 1
                    for label in (row.ids.id_label1, row.ids.file_metadata):
                        assert label.texture_size[1] <= label.height
                        assert label.height >= label.font_size * 1.35
    finally:
        rv.browser_state, rv.touch_selection_mode, rv.data = original


def test_file_search_reopens_the_same_editor_above_the_keyboard(mobile):
    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    popup = app.root.file_popup
    app.root.open_upload_local_file_popup()
    popup.open(animation=False)
    pump_frames(20)
    field = popup.ti_local_search
    sheet = popup._mobile_search_sheets['local']
    attempts = list(app.simulation.attempts)
    try:
        for _ in range(2):
            popup._mobile_search_buttons['local'].dispatch('on_release')
            field.text = 'retained-file-name'
            app.android_keyboard_height = 240
            pump_frames(24, sleep=.02)
            assert field == popup.ti_local_search
            assert field.focus
            x, y = field.to_window(*field.pos)
            assert y >= 240 and y + field.height <= Window.height
            assert field.width >= app.touch_target * 3
            sheet.dismiss(animation=False)
            app.android_keyboard_height = 0
            pump_frames(15)
            assert field.text == 'retained-file-name'
        assert app.simulation.attempts == attempts
    finally:
        field.text = ''


def test_save_picker_browses_without_replacing_the_filename_editor(mobile):
    from carveracontroller.ui.LocalFilePicker import open_local_file_picker

    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    attempts = list(app.simulation.attempts)
    open_local_file_picker(title='Save session', default_name='session.json', on_confirm=lambda *_: None)
    pump_frames(20)
    modal = next(widget for widget in Window.children if isinstance(widget, Popup))
    sheet = modal.content
    field, chooser = sheet.ids.ti_filename, sheet.ids.fc
    assert not sheet._mobile_form.viewport.do_scroll_y
    _x, y = field.to_window(*field.pos)
    _vx, bottom = sheet._mobile_form.viewport.to_window(*sheet._mobile_form.viewport.pos)
    assert y >= bottom - 1
    assert y + field.height <= bottom + sheet._mobile_form.viewport.height + 1
    field.text = 'retained-session.json'
    for _ in range(2):
        sheet._mobile_browser.open(animation=False)
        pump_frames(15)
        assert sheet.ids.fc == chooser
        assert chooser.height >= app.touch_target
        sheet._mobile_browser.dismiss(animation=False)
        pump_frames(10)
        assert field.text == 'retained-session.json'
    assert app.simulation.attempts == attempts
    modal.dismiss(animation=False)


def test_unequal_action_widths_keep_short_footers_on_one_row(mobile):
    from carveracontroller.ui.android_layout import TouchActionRow, control_height

    _app, _layout = mobile
    Metrics.density, Metrics.fontscale = 1.5, 2
    row = TouchActionRow(width=752, spacing=9)
    for text in ('Generate', 'Close', 'More…'):
        row.add_widget(Button(text=text))
    pump_frames(5)
    assert row.cols == 3
    assert row.height <= max(control_height(), max(child.texture_size[1] for child in row.children) + 24) + 1
    for child in row.children:
        assert child.width >= 72
        assert child.texture_size[1] <= child.height


def test_enlarged_viewer_header_does_not_wrap_over_the_pane_controls(mobile):
    from carveracontroller.ui.mobile_main import MobileMainLayout

    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    main = MobileMainLayout(app)
    original = app.root.content.current
    try:
        app.root.content.current = 'File'
        pump_frames(20)
        for button in main._context_row.children:
            assert button.texture_size[1] <= button.height
    finally:
        main.stop()
        app.root.content.current = original
