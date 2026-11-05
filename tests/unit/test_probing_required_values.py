"""Required probe inputs must survive the same blank filtering as generation."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from carveracontroller.addons.probing.operations.Calibration.CalibrationOperationType import CalibrationOperationType
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerOperation import InsideCornerOperation
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperation import OutsideCornerOperation
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeOperationType import (
    SingleAxisProbeOperationType,
)

OPERATIONS = [
    (SingleAxisProbeOperationType.Left.value, "X", {}),
    (SingleAxisProbeOperationType.Bottom.value, "Y", {}),
    (SingleAxisProbeOperationType.WorkpieceTop.value, "Z", {}),
    (InsideCornerOperation("Inside", False, False, ""), "X", {"Y": "10"}),
    (OutsideCornerOperation("Outside", False, False, ""), "Y", {"X": "10"}),
    (CalibrationOperationType.FourthZ.value, "X", {}),
]


@pytest.mark.parametrize(("operation", "axis", "other"), OPERATIONS)
@pytest.mark.parametrize("blank", [None, "", " \t "])
def test_required_axis_rejects_missing_or_blank(operation, axis, other, blank):
    config = dict(other)
    if blank is not None:
        config[axis] = blank
    before = dict(config)
    assert operation.get_missing_config(config).code == axis
    assert config == before


@pytest.mark.parametrize(("operation", "axis", "other"), OPERATIONS)
@pytest.mark.parametrize("value", ["0", "12.5"])
def test_required_axis_accepts_numeric_text_without_mutating_input(operation, axis, other, value):
    config = {**other, axis: value}
    before = dict(config)
    assert operation.get_missing_config(config) is None
    expected = str(-float(value)) if axis == "Z" else value
    assert axis + expected in operation.generate(config)
    assert config == before


def test_preview_has_no_executable_gcode_for_blank_required_axis():
    from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

    preview = SimpleNamespace(gcode="old command", probe_preview_label="", open=Mock())
    popup = SimpleNamespace(preview_popup=preview, controller=Mock())
    with patch("carveracontroller.addons.probing.ProbingPopup.Clock.schedule_once"):
        ProbingPopup.show_preview(popup, SingleAxisProbeOperationType.Left.value, {"X": "   "})
    assert preview.gcode == ""
    assert "Missing required parameter" in preview.probe_preview_label
    popup.controller.executeCommand.assert_not_called()
