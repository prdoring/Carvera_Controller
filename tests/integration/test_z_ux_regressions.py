import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from kivy.core.window import Window
from kivy.metrics import Metrics

from tests.integration.conftest import pump_frames, set_window_size


def test_file_navigation_and_clear_job_are_direct_actions(mobile):
    app, layout = mobile
    set_window_size((1280, 720))
    layout.update()
    popup = app.root.file_popup
    popup.open(animation=False)
    pump_frames(12)
    page = popup._mobile_file_pages['remote']
    rv = page['rv']
    previous = rv.curr_dir
    try:
        rv.curr_dir = rv.base_dir + '/setup/parts'
        with patch.object(type(rv), 'list_dir') as listing:
            page['up'].dispatch('on_release')
            assert listing.call_args.kwargs['new_dir'].replace('\\', '/').endswith('/setup')
            page['root'].dispatch('on_release')
            listing.assert_called_with(new_dir=rv.base_dir)
        assert any(button.text == 'Clear Job' for button in page['footer'].children)
        assert page['up'].parent == page['path_row']
        assert page['root'].parent == page['path_row']
        assert page['path'].text == rv.curr_dir
        clear = next(button for button in page['footer'].children if button.text == 'Clear Job')
        app.selected_remote_filename = '/sd/gcodes/fixture.cnc'
        app.selected_local_filename = 'fixture.cnc'
        clear.dispatch('on_release')
        assert app.selected_remote_filename == app.selected_local_filename == ''
    finally:
        rv.curr_dir = previous


def test_remote_navigation_serializes_requests_and_keeps_the_active_path(kivy_app):
    app = kivy_app
    rv = app.root.file_popup.remote_rv
    previous = rv.curr_dir
    try:
        rv._directory_loading = False
        rv._directory_error = ''
        app.state = 'Idle'
        with patch('carveracontroller.main.threading.Thread') as worker:
            with patch.object(app.root.controller, 'loadNUM', 1):
                rv.list_dir(new_dir=rv.base_dir + '/blocked')
                worker.assert_not_called()
                assert rv.curr_dir == previous
            rv.list_dir(new_dir=rv.base_dir + '/first')
            rv.list_dir(new_dir=rv.base_dir + '/second')
            assert worker.call_count == 1
            assert rv.curr_dir.endswith('/first')
            rv.directory_loaded()
            assert worker.call_count == 2
            assert rv.curr_dir.endswith('/second')
            rv.directory_failed('Disconnected')
            assert not rv._directory_loading
            assert rv._pending_dir is None
    finally:
        rv._directory_loading = False
        rv._directory_error = ''
        rv.curr_dir = previous


def test_device_root_navigation_uses_the_filesystem_root(mobile):
    app, _layout = mobile
    popup = app.root.file_popup
    popup.open(animation=False)
    pump_frames(8)
    page = popup._mobile_file_pages['local']
    rv = page['rv']
    previous = rv.curr_dir
    root = os.path.abspath(os.sep)
    try:
        rv.curr_dir = os.path.join(root, 'fixture', 'parts')
        with patch.object(type(rv), 'list_dir') as listing:
            page['root'].dispatch('on_release')
            listing.assert_called_with(new_dir=root)
        rv.curr_dir = root
        assert page['up'].disabled
        assert page['root'].disabled
    finally:
        rv.curr_dir = previous


@pytest.mark.parametrize('fontscale', [1, 2])
def test_spindle_controls_remain_reachable_by_scrolling(mobile, fontscale):
    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, fontscale
    app.touch_target = 72
    layout.update()
    dropdown = app.root.spindle_drop_down
    dropdown.open(app.root.spindle_laser_data_view)
    pump_frames(12)
    try:
        assert dropdown.do_scroll_y
        assert dropdown.bar_width >= 8
        for control in (dropdown.vacuum_switch, dropdown.extout_switch, dropdown.scale_slider):
            dropdown.scroll_to(control, animate=False, padding=0)
            pump_frames(4)
            _, y = control.to_window(*control.pos)
            assert y >= dropdown.y - 1
            assert y + control.height <= dropdown.top + 1
            assert control.height >= app.touch_target
    finally:
        dropdown.dismiss()


def test_directory_timeout_allows_startup_and_progress_but_is_bounded(kivy_app):
    root = kivy_app.root
    with patch.object(root, 'controller', SimpleNamespace(load_last_activity=100)), patch.object(root, 'short_load_time', 100, create=True):
        assert not root.directory_request_timed_out(104)
        assert root.directory_request_timed_out(111)
        root.controller.load_last_activity = 109
        assert not root.directory_request_timed_out(115)
        root.controller.load_last_activity = 129
        assert root.directory_request_timed_out(131)


@pytest.mark.parametrize('name', ['message_popup', 'file_popup', 'config_popup', 'diagnose_popup'])
def test_dialog_geometry_is_stable_from_first_painted_frame(mobile, name):
    app, layout = mobile
    set_window_size((1280, 720))
    Metrics.density = 1.5
    layout.update()
    popup = getattr(app.root, name)
    if name == 'message_popup':
        popup.lb_content.text = 'This message wraps over several lines on the tablet. ' * 8
    sizes = []

    def painted(*_args):
        if popup.parent is Window:
            sizes.append(tuple(round(value, 1) for value in popup.size))

    Window.bind(on_flip=painted)
    try:
        popup.open(animation=False)
        pump_frames(18, sleep=.02)
        assert sizes
        assert len(set(sizes)) == 1, sizes
        if name == 'file_popup':
            assert popup._mobile_files_ready
    finally:
        Window.unbind(on_flip=painted)
        popup.dismiss(force=True, animation=False)
