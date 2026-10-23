from tests.integration.conftest import pump_frames


def test_settings_content_survives_collection_while_reparented(mobile, monkeypatch):
    import gc
    import json

    from kivy.config import ConfigParser
    from kivy.uix.popup import Popup
    from kivy.uix.settings import SettingsWithSidebar

    from carveracontroller.ui.mobile_settings import MobileSettings

    config = ConfigParser()
    config.add_section('example')
    config.set('example', 'name', 'retained draft')
    settings = SettingsWithSidebar()
    settings.add_json_panel('Example', config, data=json.dumps([
        {'type': 'string', 'title': 'Name', 'desc': 'Saved name', 'section': 'example', 'key': 'name'}]))
    interface = settings.interface
    remove = interface.remove_widget
    def collect_after_removal(widget, *args, **kwargs):
        remove(widget, *args, **kwargs)
        gc.collect()
    monkeypatch.setattr(interface, 'remove_widget', collect_after_removal)
    manager = MobileSettings(settings, Popup())
    gc.collect()
    assert manager.content.parent is not None
    item = next(item for item in manager._rows if hasattr(item, 'value'))
    assert item.value == 'retained draft'


def test_settings_search_keeps_hidden_values_available_for_apply(mobile):
    from kivy.uix.settings import SettingItem

    app, _ = mobile
    popup = app.root.config_popup
    popup.open(animation=False)
    pump_frames(12)
    search = popup._mobile_settings
    original = list(popup._all_setting_items())
    assert original
    search.search.text = "no_such_setting_837426"
    search.filter()
    assert all(w.height == 0 for w in search._rows if w.parent in search.content.panels.values())
    assert list(popup._all_setting_items()) == original
    search.search.text = ""
    search.filter()
    assert all(w.height >= app.touch_target for w in search._rows if isinstance(w, SettingItem))
    from kivy.uix.label import Label

    panel = next(iter(search.content.panels.values()))
    late = Label(text="New capability row")
    panel.add_widget(late)
    search.filter()
    assert late in search._rows
    search.search.text = "no_such_setting_837426"
    search.filter()
    assert late.height == 0
    panel.remove_widget(late)
    search.search.text = ""
    search.filter()


def test_confirmation_and_diagnostics_open_without_sending_commands(mobile):
    app, _ = mobile
    before = list(app.simulation.commands)
    confirmation = app.root.confirm_popup
    confirmation.lb_title.text = "Discard edits?"
    confirmation.lb_content.text = "A long message " * 80
    confirmation.open(animation=False)
    pump_frames(5)
    assert confirmation.showing
    confirmation.dismiss(force=True, animation=False)
    diagnostics = app.root.diagnose_popup
    diagnostics.open(animation=False)
    pump_frames(10)
    assert diagnostics._diagnostics_prepared
    assert diagnostics.ids.sw_spindle.get_root_window() is not None
    assert app.simulation.commands == before


def test_wrapping_actions_reserve_padding_and_spacing(mobile):
    from kivy.uix.button import Button

    from carveracontroller.ui.android_layout import TouchActionRow

    app, _ = mobile
    row = TouchActionRow(width=app.touch_target * 3, size_hint_x=None, padding=8, spacing=8)
    for _ in range(3):
        row.add_widget(Button(text="OK"))
    pump_frames(4)
    assert row.cols < 3
    assert all(widget.width >= app.touch_target for widget in row.children)
    assert all(widget.right <= row.right - row.padding[2] + 1 for widget in row.children)


def test_android_picker_starts_in_writable_controller_files(mobile, monkeypatch):
    import os

    from carveracontroller.ui import LocalFilePicker

    app, _ = mobile
    monkeypatch.setattr(LocalFilePicker, "platform", "android")
    folder = LocalFilePicker.home_directory()
    assert folder == os.path.join(app.user_data_dir, "exports")
    assert os.path.isdir(folder)
    assert os.access(folder, os.W_OK)


def test_file_access_failure_survives_filtering_and_preserves_destination(mobile, tmp_path):
    import time

    app, _ = mobile
    view = app.root.file_popup.local_rv
    original = view.curr_dir
    view.list_dir(str(tmp_path / "missing"))
    deadline = time.monotonic() + 3
    while not view.browser_state.startswith("Cannot access"):
        assert time.monotonic() < deadline
        pump_frames(1, sleep=.01)
    view.fill_dir(keyword="no-match", switch_reverse=False)
    assert view.browser_state.startswith("Cannot access")
    assert view.curr_dir == original
    popup = app.root.file_popup
    popup.open(animation=False)
    app.state = "N/A"
    pump_frames(4)
    assert "disconnected" in popup.remote_rv.browser_state
