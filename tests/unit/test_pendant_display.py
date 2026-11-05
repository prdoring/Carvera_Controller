"""Tests for defensive pendant display updates."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from carveracontroller.addons.pendant import pendant as pendant_module
from carveracontroller.addons.pendant import whb04


@pytest.mark.parametrize(
    ("spindle_vars", "expected_speed"),
    [
        ({}, 0),
        ({"curspindle": None}, 0),
        ({"curspindle": "invalid"}, 0),
        ({"curspindle": -1}, 0),
        ({"curspindle": 70000}, 65535),
        ({"curspindle": "1234.5"}, 1234),
        ({"curspindle": float("nan")}, 0),
        ({"curspindle": float("inf")}, 0),
        ({"curspindle": float("-inf")}, 0),
        pytest.param({"curspindle": 10**10000}, 65535, id="huge-positive-integer"),
        pytest.param({"curspindle": -(10**10000)}, 0, id="huge-negative-integer"),
    ],
)
def test_whb04_display_sanitizes_spindle_speed(spindle_vars, expected_speed):
    pendant = pendant_module.WHB04.__new__(pendant_module.WHB04)
    pendant._cnc = SimpleNamespace(
        vars={
            "wx": 0.0,
            "wy": 0.0,
            "wz": 0.0,
            "wa": 0.0,
            "curfeed": 0.0,
            **spindle_vars,
        }
    )
    pendant._controller = SimpleNamespace(
        jog_mode=0,
        JOG_MODE_CONTINUOUS=1,
        JOG_MODE_STEP=0,
    )
    daemon = whb04.Daemon()
    daemon.set_display_spindle_speed(4321)

    pendant._handle_display_update(daemon)

    assert daemon._display_spindle_speed == expected_speed


def test_closing_whb04_stops_daemon_and_cancels_queued_callbacks():
    queued, actions = [], []
    daemon = whb04.Daemon(queued.append)
    daemon.on_button_press = lambda *_: actions.append("button")
    daemon._queue_event(lambda: daemon.on_button_press, whb04.Button.START_PAUSE)
    pendant = pendant_module.WHB04.__new__(pendant_module.WHB04)
    pendant._daemon = daemon
    pendant._controller = Mock(continuous_jog_active=True)
    pendant._update_ui_on_jog_stop = Mock()
    pendant._report_disconnection = Mock()

    pendant.close()
    for callback in queued:
        callback()

    assert actions == []
    pendant._controller.stopContinuousJog.assert_called_once()
    pendant._update_ui_on_jog_stop.assert_called_once()
    pendant._report_disconnection.assert_called_once()


@pytest.mark.parametrize("value", [None, "invalid", float("nan")])
def test_gamepad_does_not_toggle_spindle_with_unknown_speed(value):
    pendant = pendant_module.GamepadPendant.__new__(pendant_module.GamepadPendant)
    pendant._cnc = SimpleNamespace(vars={"curspindle": value})
    pendant._controller = Mock()
    pendant._do_spindle_toggle()
    pendant._controller.setSpindleSwitch.assert_not_called()
