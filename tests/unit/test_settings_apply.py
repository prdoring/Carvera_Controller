from types import SimpleNamespace
from unittest.mock import Mock

from kivy.clock import Clock

from carveracontroller.ui.settings_apply import SettingsApply


def test_apply_yields_between_commands_and_rejects_duplicate_start():
    controller = SimpleNamespace(stream=object(), protocol_ready=True, setConfigValue=Mock())
    pending = {"a": "1", "b": "2"}
    progress, finished = Mock(), Mock()
    sender = SettingsApply(controller, pending, progress, finished)
    try:
        assert sender.start()
        assert not sender.start()
        Clock.tick()
        controller.setConfigValue.assert_called_once_with("a", "1")
        assert pending == {"b": "2"}
        assert sender._event.timeout == 0.1
        # A newer edit must remain pending when the original snapshot is sent.
        pending["b"] = "3"
        sender._event.cancel()
        sender._send_next(0)
        assert pending == {"b": "3"}
        progress.assert_called_with(2, 2)
        sender._event.cancel()
        sender._send_next(0)
        finished.assert_called_once_with(None)
    finally:
        sender.cancel(notify=False)


def test_disconnect_retains_unsent_settings_and_cancel_removes_callback():
    controller = SimpleNamespace(stream=object(), protocol_ready=True, setConfigValue=Mock())
    pending = {"a": "1", "b": "2"}
    finished = Mock()
    sender = SettingsApply(controller, pending, Mock(), finished)
    sender.start()
    Clock.tick()
    controller.stream = None
    sender._event.cancel()
    sender._send_next(0)
    assert pending == {"b": "2"}
    finished.assert_called_once_with("connection")
    controller.stream = object()
    assert sender.start()
    sender.cancel()
    Clock.tick()
    controller.setConfigValue.assert_called_once_with("a", "1")
    assert pending == {"b": "2"}


def test_send_failure_keeps_current_and_later_settings():
    controller = SimpleNamespace(stream=object(), protocol_ready=True,
                                 setConfigValue=Mock(side_effect=OSError("disconnected")))
    pending = {"a": "1", "b": "2"}
    finished = Mock()
    sender = SettingsApply(controller, pending, Mock(), finished)
    sender.start()
    Clock.tick()
    assert pending == {"a": "1", "b": "2"}
    assert not sender.active
    finished.assert_called_once_with("send")


def test_reported_transport_failure_keeps_current_setting():
    controller = SimpleNamespace(stream=object(), protocol_ready=True, setConfigValue=Mock(return_value=False))
    pending = {"a": "1"}
    sender = SettingsApply(controller, pending, Mock(), Mock())
    sender.start()
    Clock.tick()
    assert pending == {"a": "1"}
    assert not sender.active
