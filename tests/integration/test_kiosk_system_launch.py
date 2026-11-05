"""Select only the System protocol actually installed on a kiosk image."""

import sys
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from carveracontroller import kiosk_runtime


class ImmediateWorker:
    def submit(self, callback):
        future = Future()
        try:
            future.set_result(callback())
        except Exception as error:
            future.set_exception(error)
        return future


@pytest.mark.parametrize(
    "files, expected",
    [
        ([], False),
        (["maintenance/system_operations.py"], False),
        (["maintenance/system_operations.py", "system-ui/carveracontroller/ui/controls.kv"], True),
    ],
)
def test_private_tools_required_before_new_protocol(tmp_path, files, expected):
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert kiosk_runtime.independent_system_available(tmp_path) is expected


@pytest.mark.parametrize("installed, returncode", [(False, 0), (True, 0), (True, 1)])
def test_launch_never_sends_new_request_to_legacy_helper(monkeypatch, installed, returncode):
    runtime = kiosk_runtime.KioskRuntime.__new__(kiosk_runtime.KioskRuntime)
    runtime._system_request = None
    runtime._system_worker = ImmediateWorker()
    runtime.show_legacy_system = Mock()
    runtime.show_system_error = Mock()
    command = Mock(return_value=SimpleNamespace(returncode=returncode))
    monkeypatch.setattr(kiosk_runtime, "independent_system_available", lambda: installed)
    monkeypatch.setattr(kiosk_runtime.subprocess, "run", command)
    monkeypatch.setattr(kiosk_runtime.Clock, "schedule_once", lambda callback: callback(0))
    runtime.open_recovery()
    assert command.call_count == int(installed)
    assert runtime.show_legacy_system.call_count == int(not installed)
    assert runtime.show_system_error.call_count == int(installed and returncode != 0)


def test_stopped_runtime_ignores_queued_legacy_launch():
    runtime = kiosk_runtime.KioskRuntime.__new__(kiosk_runtime.KioskRuntime)
    runtime._stopped = True
    runtime.show_legacy_system(0)


def test_reopening_preserves_legacy_drafts_and_uncertain_request_state(monkeypatch):
    view = SimpleNamespace(parent=None, open=Mock(), backend=SimpleNamespace(uncertain=True))
    view.open.side_effect = lambda: setattr(view, "parent", object())
    constructor = Mock(return_value=view)
    monkeypatch.setitem(sys.modules, "carveracontroller.ui.kiosk_system", SimpleNamespace(KioskSystem=constructor))
    runtime = kiosk_runtime.KioskRuntime.__new__(kiosk_runtime.KioskRuntime)
    runtime.app = object()
    runtime._stopped = False
    runtime._legacy_system = None
    runtime.show_legacy_system(0)
    runtime.show_legacy_system(0)
    view.open.assert_called_once()
    view.parent = None
    runtime.show_legacy_system(0)
    constructor.assert_called_once_with(runtime.app)
    assert runtime._legacy_system.backend.uncertain
    assert view.open.call_count == 2


def test_legacy_network_confirmation_remains_above_maintenance_blocker(kivy_app, monkeypatch):
    from kivy.core.window import Window

    from carveracontroller.ui.kiosk_legacy import LegacySystem

    from .conftest import pump_frames

    monkeypatch.setattr(LegacySystem, "overview", lambda _self: {})
    runtime = kiosk_runtime.KioskRuntime.__new__(kiosk_runtime.KioskRuntime)
    runtime.app = kivy_app
    runtime._stopped = False
    runtime._legacy_system = None
    runtime.panel = None
    try:
        runtime.show_legacy_system(0)
        view = runtime._legacy_system
        pump_frames(5)
        view.backend.wifi_attempted = True
        runtime.show_maintenance()
        pump_frames(5)
        assert Window.children.index(view) < Window.children.index(runtime.panel)
        assert view.stop.opacity == 1 and not view.stop.disabled
    finally:
        if runtime._legacy_system is not None:
            runtime._legacy_system.dismiss(force=True, animation=False)
        if runtime.panel is not None:
            runtime.panel.dismiss(force=True, animation=False)
        pump_frames(3)
