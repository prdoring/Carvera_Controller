"""USB replies are drained in bounded batches without waiting for a full batch."""

from types import SimpleNamespace

import pytest

from carveracontroller.USBStream import USBStream


class SerialBuffer:
    def __init__(self, data):
        self.data = data
        self.read_sizes = []

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, size=1):
        self.read_sizes.append(size)
        result, self.data = self.data[:size], self.data[size:]
        return result


def test_usb_receive_drains_large_reply_in_order():
    stream = USBStream()
    payload = bytes(range(256)) * 32
    stream.serial = SerialBuffer(payload)
    assert stream.recv() + stream.recv() == payload
    assert stream.serial.read_sizes == [4096, 4096]


def test_usb_receive_reads_only_available_bytes():
    stream = USBStream()
    stream.serial = SerialBuffer(b"short reply")
    assert stream.recv() == b"short reply"
    assert stream.serial.read_sizes == [11]
    assert stream.recv() == b""
    assert stream.serial.read_sizes[-1] == 1


def test_usb_receive_without_connection():
    stream = USBStream()
    assert stream.recv() == b""


def test_linux_serial_requests_low_latency(monkeypatch):
    monkeypatch.setattr("carveracontroller.USBStream.sys.platform", "linux")
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: False)
    calls = []
    USBStream._set_low_latency(SimpleNamespace(set_low_latency_mode=calls.append))
    assert calls == [True]


@pytest.mark.parametrize("platform,android", [("win32", False), ("darwin", False), ("linux", True)])
def test_other_platforms_do_not_request_linux_latency(monkeypatch, platform, android):
    monkeypatch.setattr("carveracontroller.USBStream.sys.platform", platform)
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: android)
    calls = []
    USBStream._set_low_latency(SimpleNamespace(set_low_latency_mode=calls.append))
    assert calls == []


@pytest.mark.parametrize("error", [OSError("unsupported ioctl"), ValueError("unsupported flag")])
def test_unsupported_low_latency_does_not_break_connection(monkeypatch, error):
    monkeypatch.setattr("carveracontroller.USBStream.sys.platform", "linux")
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: False)

    def unsupported(enabled):
        raise error

    USBStream._set_low_latency(SimpleNamespace(set_low_latency_mode=unsupported))
    USBStream._set_low_latency(SimpleNamespace())
