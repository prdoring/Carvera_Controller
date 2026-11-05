from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from carveracontroller.addons.cmm_workbench.core.features import mcs_xyz_to_wcs_xyz
from carveracontroller.CNC import CNC


def test_rotated_machine_coordinates_use_numeric_offsets(monkeypatch):
    monkeypatch.setattr(CNC, "vars", {"rotation_angle": "90", "wcox": 10, "wcoy": 20.0, "wcoz": 3})
    assert mcs_xyz_to_wcs_xyz(12, 25, 7) == pytest.approx((5, -2, 4))


@pytest.mark.parametrize("bad", [None, "invalid", float("nan"), float("inf"), object()])
def test_invalid_coordinate_offset_does_not_produce_geometry(monkeypatch, bad):
    monkeypatch.setattr(CNC, "vars", {"rotation_angle": 0, "wcox": bad, "wcoy": 0, "wcoz": 0})
    with pytest.raises(ValueError, match="numeric machine status"):
        mcs_xyz_to_wcs_xyz(1, 2, 3)


def test_missing_coordinate_offset_is_rejected(monkeypatch):
    monkeypatch.setattr(CNC, "vars", {"rotation_angle": 0, "wcoy": 0, "wcoz": 0})
    with pytest.raises(ValueError):
        mcs_xyz_to_wcs_xyz(1, 2, 3)


def test_invalid_probe_result_cancels_without_appending_geometry(monkeypatch):
    from carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup import CMMWorkbenchPopup

    monkeypatch.setattr(CNC, "vars", {"mx": "invalid", "my": 0, "mz": 0})
    popup = SimpleNamespace(
        _runner=Mock(), session=SimpleNamespace(features=[]), _refresh_feature_ui=Mock(), _toast=Mock()
    )
    popup._append_probe_result = lambda *args: CMMWorkbenchPopup._append_probe_result(popup, *args)
    queued = []
    with patch(
        "carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup.Clock.schedule_once",
        side_effect=lambda callback, _delay: queued.append(callback),
    ):
        CMMWorkbenchPopup._on_probe_values(popup, "M466", {}, [])
    queued.pop()(0)
    popup._runner.cancel.assert_called_once()
    popup._runner.complete.assert_not_called()
    popup._toast.assert_called_once()
    assert popup.session.features == []


def test_unknown_machine_state_is_not_stringified_as_valid_status(monkeypatch):
    from carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup import _machine_state

    monkeypatch.setattr(CNC, "vars", {"state": object()})
    assert _machine_state() == "N/A"
    CNC.vars["state"] = "Idle"
    assert _machine_state() == "Idle"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_probe_value_cancels_without_appending(monkeypatch, value):
    from carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup import CMMWorkbenchPopup

    monkeypatch.setattr(CNC, "vars", {"mx": 0, "my": 0, "mz": 0, "rotation_angle": 0, "wcox": 0, "wcoy": 0, "wcoz": 0})
    popup = SimpleNamespace(
        _runner=Mock(), session=SimpleNamespace(features=[]), _refresh_feature_ui=Mock(), _toast=Mock()
    )
    popup._append_probe_result = lambda *args: CMMWorkbenchPopup._append_probe_result(popup, *args)
    queued = []
    with patch(
        "carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup.Clock.schedule_once",
        side_effect=lambda callback, _delay: queued.append(callback),
    ):
        CMMWorkbenchPopup._on_probe_values(popup, "M466", {"154": value}, ["154"])
    queued.pop()(0)
    popup._runner.cancel.assert_called_once()
    popup._runner.complete.assert_not_called()
    assert popup.session.features == []


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e9999"])
def test_circle_classification_tolerance_must_be_finite(value):
    from carveracontroller.addons.cmm_workbench.ui.CMMWorkbenchPopup import CMMWorkbenchPopup

    popup = SimpleNamespace(ids=SimpleNamespace(t461_circle_tol=SimpleNamespace(text=value)), _toast=Mock())
    assert CMMWorkbenchPopup._read_circle_classify_tolerance_mm(popup, "M461") is None
    popup._toast.assert_called_once()
