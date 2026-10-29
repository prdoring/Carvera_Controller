import json
from pathlib import Path

import pytest

from tests.integration.conftest import pump_frames


@pytest.mark.parametrize("model", ["C1", "CA1"])
def test_vacuum_power_shortcut_edits_without_sending(kivy_app, connected_idle_state, model):
    app = kivy_app
    root = app.root
    app.model = model
    app.state = "Idle"
    schema = Path(__file__).resolve().parents[2] / "carveracontroller" / f"config_{model.lower()}.json"
    root.setting_list = {
        item["key"]: item.get("default", "0")
        for item in json.loads(schema.read_text(encoding="utf-8"))
        if "key" in item
    }
    root.config_loading = True
    try:
        assert root.load_machine_config()
    finally:
        root.config_loading = False
    root.config_loaded = True
    root.setting_change_list.clear()
    popup = root.config_popup
    button = root.spindle_drop_down.ids.vacuum_power_button
    commands_before = list(app.simulation.commands)
    app.state = "Run"
    assert button.disabled
    app.state = "Idle"
    assert not button.disabled
    button.dispatch("on_release")
    pump_frames(12)
    setting = next(item for item in popup._all_setting_items() if item.key == "switch.vacuum.default_on_value")
    try:
        assert setting.popup.parent is not None
        assert popup.settings_panel.interface.content.current_uid == setting.panel.uid
        setting.textinput.text = "100"
        setting._validate(None)
        assert float(root.setting_change_list[setting.key]) == 100
        assert not popup.btn_apply.disabled
        assert app.simulation.commands == commands_before
        popup._discard_and_close()
        assert setting.key not in root.setting_change_list
        assert float(setting.value) == 80
    finally:
        setting._dismiss()
        popup.dismiss(force=True, animation=False)
