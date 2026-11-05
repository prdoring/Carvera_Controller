"""Tests for defensive WHB04 input packet handling."""

import struct

import pytest

from carveracontroller.addons.pendant import whb04


@pytest.mark.parametrize(
    ("valid_button", "unknown_first"),
    [
        (whb04.Button.STOP, False),
        (whb04.Button.STOP, True),
        (whb04.Button.RESET, False),
        (whb04.Button.RESET, True),
    ],
)
def test_unknown_button_does_not_drop_valid_button_from_same_packet(valid_button, unknown_first):
    daemon = whb04.Daemon()
    pressed = []
    daemon.on_button_press = lambda _daemon, button: pressed.append(button)
    button1, button2 = (0xFF, valid_button.value) if unknown_first else (valid_button.value, 0xFF)
    packet = struct.pack(
        "BBBBBBbB",
        0x04,
        0,
        button1,
        button2,
        whb04.StepSize.LEAD.value,
        whb04.Axis.OFF.value,
        0,
        0,
    )

    daemon._process_input_packet(packet)

    assert pressed == [valid_button]
    assert daemon.pressed_buttons == {valid_button}


def packet(axis=whb04.Axis.X, step=whb04.StepSize.STEP_0_01, delta=0, button=0):
    return struct.pack("BBBBBBbB", 0x04, 0, button, 0, step.value, axis.value, delta, 0)


@pytest.mark.parametrize(
    ("axis", "step"),
    [
        (whb04.Axis.Y, whb04.StepSize.STEP_0_01),
        (whb04.Axis.X, whb04.StepSize.STEP_0_1),
        (whb04.Axis.Y, whb04.StepSize.STEP_0_1),
    ],
)
def test_selector_change_stops_active_wheel_without_optional_observers(axis, step):
    daemon = whb04.Daemon()
    daemon._process_input_packet(packet())
    daemon._wheel_has_been_active = True
    stops = []
    daemon.on_stop_jog = lambda _: stops.append("stop")
    daemon._process_input_packet(packet(axis=axis, step=step))
    assert stops == ["stop"]
    assert not daemon.wheel_has_been_active


def test_selector_stop_is_delivered_before_new_step_jog():
    queued, events = [], []
    daemon = whb04.Daemon(queued.append)
    daemon.set_display_step_indicator(whb04.StepIndicator.STEP)
    daemon._process_input_packet(packet())
    daemon._wheel_has_been_active = True
    daemon.on_stop_jog = lambda _: events.append("stop")
    daemon.on_jog = lambda _, delta: events.append(delta)
    daemon._process_input_packet(packet(axis=whb04.Axis.Y, delta=2))
    for callback in queued:
        callback()
    assert events == ["stop", 2]


def test_queued_button_callback_rechecks_handler_and_preserves_arguments():
    queued, buttons = [], []
    daemon = whb04.Daemon(queued.append)
    daemon.on_button_press = lambda _, button: buttons.append(button)
    daemon._process_input_packet(packet(button=whb04.Button.STOP.value))
    queued.pop()()
    assert buttons == [whb04.Button.STOP]
    daemon._process_input_packet(packet(button=whb04.Button.RESET.value))
    daemon.on_button_press = None
    for callback in queued:
        callback()
    assert buttons == [whb04.Button.STOP]


def test_stop_cancels_queued_machine_callbacks_without_starting_hid():
    queued, jogs = [], []
    daemon = whb04.Daemon(queued.append)
    daemon.set_display_step_indicator(whb04.StepIndicator.STEP)
    daemon.on_jog = lambda _, delta: jogs.append(delta)
    daemon._process_input_packet(packet(delta=1))
    daemon.stop()
    for callback in queued:
        callback()
    assert jogs == []


@pytest.mark.parametrize("indicator", list(whb04.StepIndicator))
@pytest.mark.parametrize("step", list(whb04.StepSize))
def test_step_size_value_is_numeric_for_every_accepted_indicator(indicator, step):
    daemon = whb04.Daemon()
    daemon.set_display_step_indicator(indicator)
    daemon._step_size = step
    assert isinstance(daemon.step_size_value, (int, float))
    if indicator in (whb04.StepIndicator.MPG, whb04.StepIndicator.PERCENT):
        assert daemon.step_size_value == 0.0
