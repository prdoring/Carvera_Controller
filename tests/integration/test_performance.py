import threading
import time

import pytest
from kivy.core.window import Window
from kivy.lang import Builder

from carveracontroller.addons.tooltips.Tooltips import (
    ToolTipButton,
    ToolTipDropDown,
    ToolTipLabel,
    ToolTipSwitch,
    ToolTipTextInput,
)
from carveracontroller.GcodeViewer import MeshManager
from tests.integration.conftest import load_gcode_file, pump_frames


def wait_for(predicate):
    deadline = time.monotonic() + 10
    while not predicate():
        assert time.monotonic() < deadline
        pump_frames(1, sleep=0.01)


def test_startup_defers_optional_dialogs_and_settings(kivy_app):
    root = kivy_app.root
    assert root.probing_popup is None
    assert root.facing_popup is None
    assert root.adv_calibrate_popup is None
    assert len(root._pending_settings_panels) == 3
    settings = root.config_popup.settings_panel
    assert not settings.interface.content.panels
    root.config_popup.open()
    pump_frames(5, sleep=0.05)
    assert not root._pending_settings_panels
    assert len(settings.interface.content.panels) == 3
    assert root.config_popup._widget_snapshot
    root.config_popup.dismiss()
    root.config_popup.open()
    pump_frames(5, sleep=0.05)
    assert len(settings.interface.content.panels) == 3
    root.config_popup.dismiss()
    pump_frames(5, sleep=0.05)


@pytest.mark.parametrize("widget_type", [ToolTipButton, ToolTipLabel, ToolTipSwitch, ToolTipTextInput, ToolTipDropDown])
def test_tooltips_are_lazy_and_disabling_cancels_pending_display(kivy_app, widget_type, monkeypatch):
    widget = widget_type(tooltip_txt="Initial", show_tooltips=False, size_hint=(None, None), size=(100, 50))
    widget.show_tooltips = False
    widget.pos = (100, 100)
    assert widget._tooltip is None
    assert not widget._tooltip_mouse_bound
    widget.tooltip_txt = "Changed before hover"
    widget.tooltip_image_size = (50, 50)
    Window.add_widget(widget)
    monkeypatch.setattr(widget, "_is_blocked_by_modal", lambda: False)
    try:
        widget.show_tooltips = True
        assert widget._tooltip_mouse_bound
        widget.on_mouse_pos(Window, (10, 10))
        assert widget._tooltip is None
        widget.on_mouse_pos(Window, (120, 120))
        assert widget._tooltip is not None
        assert widget._tooltip.ids.tooltip_label.text == "Changed before hover"
        widget.show_tooltips = False
        pump_frames(2, sleep=0.02)
        assert not widget._tooltip_mouse_bound
        assert widget._tooltip.parent is None
        widget.show_tooltips = True
        widget.display_tooltip()
        assert widget._tooltip.parent is Window
        widget.on_mouse_pos(Window, (10, 10))
        assert widget._tooltip.parent is None
    finally:
        widget.show_tooltips = False
        widget.close_tooltip()
        Window.remove_widget(widget)
        Builder.unbind_widget(widget.uid)


def test_wifi_waits_in_worker_and_prevents_overlapping_connections(kivy_app, monkeypatch):
    root = kivy_app.root
    entered = threading.Event()
    release = threading.Event()
    worker_ids = []

    def connect(*args):
        worker_ids.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return False

    monkeypatch.setattr(root.controller, "open", connect)
    try:
        assert root.openWIFI("192.0.2.1", quiet=True)
        assert entered.wait(1)
        assert len(worker_ids) == 1
        assert worker_ids[0] != threading.get_ident()
        assert root.openWIFI("192.0.2.2", quiet=True) is False
        assert root.openUSB("unused") is None
        pump_frames(5, sleep=0.01)
        assert root._wifi_connect_in_progress
    finally:
        release.set()
        wait_for(lambda: not root._wifi_connect_in_progress)


def test_geometry_is_prepared_in_worker_and_uploaded_on_ui_thread(kivy_app, tmp_path, monkeypatch):
    root = kivy_app.root
    parse_threads = set()
    property_threads = []
    legend_threads = []
    upload_threads = []
    original_parse = MeshManager.parse_line_data
    original_upload = root.gcode_viewer.load_prepared
    original_legend = root.gcode_viewer._legend_durations_for_path

    def parse(manager, line):
        parse_threads.add(threading.get_ident())
        return original_parse(manager, line)

    def upload(prepared):
        upload_threads.append(threading.get_ident())
        return original_upload(prepared)

    def legend(*args):
        legend_threads.append(threading.get_ident())
        return original_legend(*args)

    monkeypatch.setattr(MeshManager, "parse_line_data", parse)
    monkeypatch.setattr(root.gcode_viewer, "load_prepared", upload)
    monkeypatch.setattr(root.gcode_viewer, "_legend_durations_for_path", legend)

    def line_count_changed(*args):
        property_threads.append(threading.get_ident())

    root.bind(selected_file_line_count=line_count_changed)
    path = tmp_path / "preview.cnc"
    path.write_text("G21 G90\nG0 X0 Y0 Z0\nG1 X10 F300\nG1 Y10\nG0 Z5\n")
    load_gcode_file(kivy_app, str(path))
    assert parse_threads
    assert threading.get_ident() not in parse_threads
    assert upload_threads == [threading.get_ident()]
    assert root.gcode_viewer.raw_linenumbers
    assert max(root.gcode_viewer.raw_linenumbers) == 5
    assert root.gcode_viewer.total_distance > 0
    assert legend_threads
    assert threading.get_ident() not in legend_threads
    assert root.gcode_viewer.legend_durations_cache is not None
    path.write_text("")
    load_gcode_file(kivy_app, str(path))
    assert root.gcode_viewer.total_distance == 0
    assert root.gcode_viewer.raw_linenumbers == []
    root.unbind(selected_file_line_count=line_count_changed)
    assert property_threads
    assert set(property_threads) == {threading.get_ident()}


def test_gcode_page_updates_once_and_ignores_stale_results(kivy_app):
    root = kivy_app.root
    root.lines = ["G1 X1 (brackets [and] &)\n"] * 10000
    kivy_app.total_pages = 1
    updates = []

    def changed(widget, data):
        updates.append(len(data))

    root.gcode_rv.bind(data=changed)
    try:
        root.load_page(1)
        wait_for(lambda: not kivy_app.loading_page)
        assert updates == [10000]
        assert root.gcode_rv.data[0]["line_no"] == 1
        assert root.gcode_rv.data[-1]["line_no"] == 10000
        rows = root.gcode_rv.data
        root._finish_load_page(root._page_generation - 1, 2, [{"text": "obsolete"}])
        assert root.gcode_rv.data == rows
        assert kivy_app.curr_page == 1
    finally:
        root.gcode_rv.unbind(data=changed)


def test_clearing_preview_discards_old_time_estimate(kivy_app, monkeypatch):
    import carveracontroller.GcodeViewer as viewer_module

    viewer = kivy_app.root.gcode_viewer
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    reports = []

    def compute(*args):
        entered.set()
        assert release.wait(5)
        finished.set()
        return [0.0, 123.0]

    monkeypatch.setattr(viewer_module, "_compute_line_times_worker", compute)
    monkeypatch.setattr(viewer, "_report_time_estimate_progress", lambda *args: reports.append(args))
    viewer.raw_positions = [0, 0, 0, 10, 0, 0]
    viewer.raw_linenumbers = [1, 2]
    viewer.raw_feed_rates = [300, 300]
    try:
        viewer._compute_line_times_async()
        assert entered.wait(1)
        viewer.clearDisplay()
    finally:
        release.set()
        assert finished.wait(1)
    pump_frames(5, sleep=0.02)
    assert viewer.total_time == 0
    assert viewer.line_times == []
    assert reports == []


def test_optional_dialogs_open_and_reuse_their_widgets(kivy_app, monkeypatch):
    from carveracontroller.CNC import CNC
    from carveracontroller.main import ZPROBE_TOOL_NUMBER

    root = kivy_app.root
    monkeypatch.setattr(kivy_app, "is_community_firmware", True)
    monkeypatch.setitem(CNC.vars, "tool", ZPROBE_TOOL_NUMBER)
    for open_dialog, attribute in [
        (root.open_probing_popup, "probing_popup"),
        (root.open_facing_popup, "facing_popup"),
        (root.open_adv_calibrate_popup, "adv_calibrate_popup"),
    ]:
        open_dialog()
        pump_frames(10, sleep=0.02)
        popup = getattr(root, attribute)
        assert popup._is_open
        if attribute == "probing_popup":
            assert popup._settings_panels
        popup.dismiss()
        pump_frames(10, sleep=0.02)
        open_dialog()
        assert getattr(root, attribute) is popup
        popup.dismiss()
        pump_frames(10, sleep=0.02)
