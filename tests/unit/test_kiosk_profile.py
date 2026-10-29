import configparser
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from carveracontroller.kiosk_state import activity, maintenance_ack, require_idle, write_json
from carveracontroller.runtime_profile import configure, is_kiosk, may_connect, uses_touch


def test_kiosk_keeps_actual_os_and_uses_one_input_provider(monkeypatch):
    monkeypatch.setenv("CARVERA_PROFILE", "kiosk")
    config = configparser.ConfigParser(interpolation=None)
    config.read_dict({"graphics": {}, "kivy": {}, "input": {"raw": "probesysfs,provider=mtdev"}})
    configure(config)
    assert is_kiosk() and uses_touch("linux")
    assert config.get("graphics", "fullscreen") == "auto"
    assert list(config["input"]) == ["mouse"]
    assert config.get("kivy", "keyboard_mode") == "dock"


def test_desktop_configuration_is_unchanged(monkeypatch):
    monkeypatch.delenv("CARVERA_PROFILE", raising=False)
    assert not uses_touch("linux")
    assert uses_touch("android")
    config = configparser.ConfigParser()
    configure(config)
    assert config.sections() == []


@pytest.mark.parametrize("state", ["Run", "Hold", "Pause", "Home", "Tool", "Wait", "Alarm"])
def test_machine_states_block_maintenance(state):
    controller = SimpleNamespace(stream=object(), continuous_jog_active=False, _connecting=False, sendNUM=0, loadNUM=0)
    app = SimpleNamespace(root=SimpleNamespace(controller=controller), playing=False, state=state)
    with pytest.raises(ValueError, match="busy"):
        require_idle(activity(app), confirmed=True)


def test_maintenance_requires_fresh_status_and_matching_ack():
    with pytest.raises(ValueError, match="stale"):
        require_idle({"updated": 0}, now=10)
    status = {"updated": 10, "busy": False, "connected": False, "maintenance": True, "token": "one"}
    with pytest.raises(ValueError, match="disconnected"):
        require_idle(status, now=10)
    require_idle(status, now=10, confirmed=True)
    status["updated"] = time.monotonic()
    maintenance_ack(status, "one")
    with pytest.raises(ValueError, match="acknowledged"):
        maintenance_ack(status, "two")


def test_restart_blocks_automatic_but_allows_deliberate_reconnection(monkeypatch, tmp_path):
    monkeypatch.setenv("CARVERA_PROFILE", "kiosk")
    monkeypatch.setenv("CARVERA_MAINT_DIR", str(tmp_path))
    assert not may_connect(automatic=True)
    assert may_connect()
    (tmp_path / "maintenance.request").touch()
    assert not may_connect()


def test_maintenance_blocks_motion_and_connection_but_preserves_stop(monkeypatch):
    from carveracontroller import runtime_profile
    from carveracontroller.Controller import Controller

    controller = Controller.__new__(Controller)
    monkeypatch.setenv("CARVERA_PROFILE", "kiosk")
    controller.stream = Mock()
    controller.comms = SimpleNamespace(encode_realtime=lambda value: bytes([value]))
    monkeypatch.setattr(runtime_profile, "maintenance_active", True)
    assert controller.executeCommand("G0 X100") is False
    assert controller.executeFileCommand("upload job.nc") is False
    assert controller.open(1, "unused") is False
    controller.cyclestartCommand()
    controller.stream.send.assert_not_called()
    controller.estopCommand()
    controller.stream.send.assert_called_once_with(b"\x18")


def test_atomic_status_write(tmp_path):
    path = tmp_path / "status.json"
    write_json(path, {"busy": True})
    assert json.loads(path.read_text()) == {"busy": True}
    assert not path.with_suffix(".tmp").exists()
