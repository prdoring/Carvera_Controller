"""USB reads are batched and high-speed Linux command writes are paced."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from carveracontroller.Controller import CONN_USB, CONN_WIFI, Controller
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


class SerialWriter:
    baudrate = 1500000

    def __init__(self):
        self.writes = []
        self.flushes = 0

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        self.flushes += 1


@pytest.fixture
def linux_writer(monkeypatch):
    monkeypatch.setattr("carveracontroller.USBStream.sys.platform", "linux")
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: False)
    stream = USBStream()
    stream.serial = SerialWriter()
    stream.uses_framed_transfer = True
    return stream


def test_high_speed_linux_commands_are_paced(linux_writer, monkeypatch):
    delays = []
    monkeypatch.setattr("carveracontroller.USBStream.time.sleep", delays.append)
    frame = bytes(range(37))
    linux_writer.send(frame)
    assert linux_writer.serial.writes == [frame[i : i + 8] for i in range(0, len(frame), 8)]
    assert linux_writer.serial.flushes == 4
    assert delays == [0.001] * 4


@pytest.mark.parametrize(
    "platform,android,framed,baud",
    [
        ("win32", False, True, 1500000),
        ("darwin", False, True, 1500000),
        ("linux", True, True, 1500000),
        ("linux", False, False, 1500000),
        ("linux", False, True, 460800),
        ("linux", False, True, 115200),
    ],
)
def test_other_command_writes_are_unchanged(linux_writer, monkeypatch, platform, android, framed, baud):
    monkeypatch.setattr("carveracontroller.USBStream.sys.platform", platform)
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: android)
    linux_writer.uses_framed_transfer = framed
    linux_writer.serial.baudrate = baud
    linux_writer.send("folder\n")
    assert linux_writer.serial.writes == [b"folder\n"]
    assert linux_writer.serial.flushes == 0


def test_file_transfer_writes_remain_bulk(linux_writer):
    payload = bytes(range(256)) * 4
    assert linux_writer.putc(payload) == len(payload)
    assert linux_writer.serial.writes == [payload]
    assert linux_writer.serial.flushes == 0


def test_bulk_write_cannot_split_a_paced_command(linux_writer):
    first_write = threading.Event()
    release_write = threading.Event()
    bulk_attempt = threading.Event()
    writer = linux_writer.serial
    write = writer.write

    def blocked_write(data):
        result = write(data)
        if len(writer.writes) == 1:
            first_write.set()
            assert release_write.wait(2)
        return result

    def bulk_write():
        bulk_attempt.set()
        return linux_writer.putc(b"bulk")

    writer.write = blocked_write
    frame = bytes(range(37))
    with ThreadPoolExecutor(max_workers=2) as executor:
        command = executor.submit(linux_writer.send, frame)
        try:
            assert first_write.wait(2)
            bulk = executor.submit(bulk_write)
            assert bulk_attempt.wait(2)
        finally:
            release_write.set()
        command.result(timeout=2)
        assert bulk.result(timeout=2) == 4
    assert writer.writes == [frame[i : i + 8] for i in range(0, len(frame), 8)] + [b"bulk"]


def test_closed_usb_writes_do_nothing():
    stream = USBStream()
    assert stream.send(b"command") is None
    assert stream.putc(b"bulk") is None


def test_linux_file_header_reads_share_a_serial_batch(linux_writer):
    linux_writer.serial = SerialBuffer(b"header and payload")
    assert linux_writer.getc(1) == b"h"
    assert linux_writer.getc(5) == b"eader"
    assert linux_writer.getc(12) == b" and payload"
    assert linux_writer.serial.read_sizes == [18]


def test_file_read_ahead_leaves_status_bytes_for_normal_receiver(linux_writer):
    linux_writer.serial = SerialBuffer(b"file frameSTATUS")
    assert linux_writer.getc(10) == b"file frame"
    assert linux_writer.waiting_for_recv() == 6
    assert linux_writer.recv() == b"STATUS"
    assert linux_writer.waiting_for_recv() == 0
    assert linux_writer.serial.read_sizes == [16]


def test_file_read_ahead_is_bounded(linux_writer):
    linux_writer.serial = SerialBuffer(b"x" * 9000)
    assert linux_writer.getc(1) == b"x"
    assert linux_writer.serial.read_sizes == [4096]
    assert len(linux_writer._read_buffer) == 4095


def test_large_file_read_can_span_serial_batches(linux_writer):
    payload = bytes(range(256)) * 32
    linux_writer.serial = SerialBuffer(payload)
    assert linux_writer.getc(1) + linux_writer.getc(8191) == payload
    assert linux_writer.serial.read_sizes == [4096, 4096]


def test_file_read_preserves_short_read_and_timeout_results(linux_writer):
    linux_writer.serial = SerialBuffer(b"short")
    assert linux_writer.getc(10) == b"short"
    assert linux_writer.getc(1) is None


@pytest.mark.parametrize(
    "platform,android,framed", [("win32", False, True), ("linux", True, True), ("linux", False, False)]
)
def test_other_file_read_paths_are_unchanged(linux_writer, monkeypatch, platform, android, framed):
    monkeypatch.setattr("carveracontroller.USBStream.sys.platform", platform)
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: android)
    linux_writer.uses_framed_transfer = framed
    linux_writer.serial = SerialBuffer(b"header")
    assert linux_writer.getc(1) == b"h"
    assert linux_writer.serial.read_sizes == [1]


@pytest.mark.parametrize("result", [128, 0, -1, None])
def test_only_successful_high_speed_download_checks_status(tmp_path, linux_writer, result):
    linux_writer.modem.recv = Mock(return_value=result)
    linux_writer.download_finished = Mock()
    assert linux_writer.download(str(tmp_path / "received"), "", None) == result
    assert linux_writer.download_finished.call_count == int(result is not None and result >= 0)


@pytest.fixture
def download_controller():
    controller = Controller.__new__(Controller)
    controller.connection_type = CONN_USB
    controller.usb_stream = SimpleNamespace(
        serial=SimpleNamespace(baudrate=1500000), initial_baud=115200, reopen_at_baud=Mock(return_value=True)
    )
    controller.stream = controller.usb_stream
    controller.usb_stream.reset_input_buffer = Mock()
    controller.comms = SimpleNamespace(reset_parser=Mock())
    controller.request_baud_upgrade = Mock()
    controller.close_manual = Mock()
    return controller


def test_download_keeps_a_responsive_usb_rate(download_controller):
    controller = download_controller
    controller._await_status_response = Mock(return_value=True)
    controller._finish_usb_download()
    controller.usb_stream.reopen_at_baud.assert_not_called()
    controller.request_baud_upgrade.assert_not_called()
    controller.close_manual.assert_not_called()
    assert not controller._baud_switch_in_progress


def test_download_recovers_firmware_baud_timeout(download_controller):
    controller = download_controller
    controller._await_status_response = Mock(side_effect=[False, True])
    controller._finish_usb_download()
    controller.usb_stream.reopen_at_baud.assert_called_once_with(115200)
    controller.request_baud_upgrade.assert_called_once_with(1500000)
    controller.close_manual.assert_not_called()
    assert not controller._baud_switch_in_progress


def test_unresponsive_usb_after_download_is_disconnected(download_controller):
    controller = download_controller
    controller._await_status_response = Mock(return_value=False)
    with pytest.raises(RuntimeError, match="No USB status after download"):
        controller._finish_usb_download()
    controller.request_baud_upgrade.assert_not_called()
    controller.close_manual.assert_called_once_with()
    assert not controller._baud_switch_in_progress


def test_network_download_does_not_reconfigure_usb(download_controller):
    controller = download_controller
    controller.connection_type = CONN_WIFI
    controller._finish_usb_download()
    controller.usb_stream.reopen_at_baud.assert_not_called()


def test_input_reset_discards_read_ahead_and_driver_bytes(linux_writer):
    linux_writer._read_buffer.extend(b"old status")
    linux_writer.serial.reset_input_buffer = Mock()
    linux_writer.reset_input_buffer()
    assert not linux_writer._read_buffer
    linux_writer.serial.reset_input_buffer.assert_called_once_with()
