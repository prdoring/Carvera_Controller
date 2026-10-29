import time
from unittest.mock import patch

import pytest

from carveracontroller.CNC import CNC
from tests.integration.conftest import pump_frames


@pytest.mark.parametrize("model", ["C1", "CA1"])
@pytest.mark.parametrize("state", ["Idle", "Run"])
def test_vacuum_power_updates_live_without_opening_settings(kivy_app, connected_idle_state, model, state):
    app = kivy_app
    root = app.root
    app.model = model
    root.config_loaded = True
    CNC.vars["state"] = app.state = state
    dropdown = root.spindle_drop_down
    control = dropdown.ids.vacuum_power
    commands_before = len(app.simulation.commands)
    saved_changes = dict(root.setting_change_list)
    dropdown.open(root.spindle_laser_data_view)
    try:
        assert not control.enabled
        root.controller.parseBigParentheses("{G:0,0,0,1,50}")
        control.refresh()
        assert control.value == 50
        assert control.enabled
        assert len(app.simulation.commands) == commands_before
        with patch.object(root.config_popup, "open") as settings:
            control.ids.power_slider.value = 100
            control.ids.power_slider.value = 80
            pump_frames(12, sleep=.02)
            settings.assert_not_called()
        assert app.simulation.commands[commands_before:] == ["M851 S80\n"]
        control.ids.increase.dispatch("on_release")
        pump_frames(12, sleep=.02)
        assert app.simulation.commands[-1] == "M851 S85\n"
        control.ids.decrease.dispatch("on_release")
        pump_frames(12, sleep=.02)
        assert app.simulation.commands[-1] == "M851 S80\n"
        assert root.setting_change_list == saved_changes
    finally:
        dropdown.dismiss()
        pump_frames(10, sleep=.02)


@pytest.mark.parametrize("reason", ["off", "stale", "alarm", "dismiss"])
def test_vacuum_power_cancels_pending_changes(kivy_app, connected_idle_state, reason):
    app = kivy_app
    app.model = "CA1"
    app.state = "Idle"
    app.root.config_loaded = True
    dropdown = app.root.spindle_drop_down
    dropdown.open(app.root.spindle_laser_data_view)
    control = dropdown.ids.vacuum_power
    try:
        app.root.controller.parseBigParentheses("{G:0,0,0,1,60}")
        control._last_send = 0
        control.refresh()
        commands_before = len(app.simulation.commands)
        control.change_power(90)
        if reason == "off":
            app.root.controller.parseBigParentheses("{G:0,0,0,0,0}")
        elif reason == "stale":
            CNC.vars["extout_report_time"] = time.monotonic() - 3
        elif reason == "alarm":
            CNC.vars["state"] = app.state = "Alarm"
        else:
            dropdown.dismiss()
        control.refresh()
        pump_frames(12, sleep=.02)
        assert len(app.simulation.commands) == commands_before
        assert not control.enabled
    finally:
        dropdown.dismiss()
        pump_frames(10, sleep=.02)


def test_mobile_vacuum_power_controls_are_reachable(mobile, connected_idle_state):
    app, _layout = mobile
    app.model = "CA1"
    app.state = "Idle"
    dropdown = app.root.spindle_drop_down
    dropdown.open(app.root.spindle_laser_data_view)
    try:
        pump_frames(8)
        control = dropdown.ids.vacuum_power
        for widget in (control.ids.power_slider, control.ids.increase, control.ids.decrease):
            dropdown.scroll_to(widget, animate=False, padding=0)
            pump_frames(3)
            assert widget.height >= app.touch_target
            assert widget.to_window(*widget.pos)[1] >= dropdown.y - 1
    finally:
        dropdown.dismiss()
        pump_frames(10, sleep=.02)
