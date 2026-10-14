"""Android permission handling and serial buffering without an Android runtime."""

import sys
import threading
from types import SimpleNamespace

import pytest
from serial import SerialException

from carveracontroller import AndroidUSB, Utils
from carveracontroller.AndroidUSB import _ReadBuffer
from carveracontroller.USBStream import USBStream


def test_binary_reads_preserve_order_and_partial_packets():
    buffer = _ReadBuffer()
    payload = bytes(range(256))
    buffer.feed(payload[:99])
    buffer.feed(payload[99:])
    assert buffer.waiting == 256
    assert buffer.read(128, 0) == payload[:128]
    assert buffer.read(256, 0) == payload[128:]
    assert buffer.read(1, 0) == b""
    assert buffer.waiting == 0


def test_read_waits_for_more_bytes_and_unplug_wakes_reader():
    buffer = _ReadBuffer()
    started = threading.Event()
    errors = []

    def read():
        started.set()
        try:
            buffer.read(10, 30)
        except SerialException as error:
            errors.append(str(error))

    reader = threading.Thread(target=read)
    reader.start()
    assert started.wait(1)
    buffer.fail("device detached")
    reader.join(1)
    assert not reader.is_alive()
    assert errors == ["device detached"]
    with pytest.raises(SerialException, match="device detached"):
        _ = buffer.waiting


def test_receive_overflow_and_closed_port_are_errors():
    buffer = _ReadBuffer()
    buffer.feed(b"x" * (1024 * 1024 + 1))
    with pytest.raises(SerialException, match="overflow"):
        buffer.read(1, 0)
    buffer = _ReadBuffer()
    buffer.feed(b"old data")
    buffer.clear()
    assert buffer.waiting == 0
    buffer.close()
    buffer.feed(b"late callback")
    with pytest.raises(SerialException, match="closed"):
        buffer.read(1, 0)


@pytest.mark.parametrize("granted,notify", [(True, True), (False, True), (False, False)])
def test_permission_grant_denial_timeout_and_receiver_cleanup(monkeypatch, granted, notify):
    registrations = []
    cleanup = []

    class Intent:
        def __init__(self, action):
            self.action = action

        def setPackage(self, package):
            assert package == "test.controller"
            return self

    class Activity:
        def getPackageName(self):
            return "test.controller"

        def registerReceiver(self, receiver, intent_filter, flags):
            registrations.append(receiver)
            assert flags == 4

        def unregisterReceiver(self, receiver):
            assert receiver is registrations[0]
            cleanup.append("receiver")

    class Manager:
        allowed = False

        def hasPermission(self, device):
            return self.allowed

        def requestPermission(self, device, pending):
            self.allowed = granted
            if notify:
                registrations[0].set()

    pending = SimpleNamespace(cancel=lambda: cleanup.append("pending"))
    api = SimpleNamespace(
        activity=Activity(), manager=Manager(), sdk=36,
        permission_callback=lambda event: event, receiver=lambda callback: callback,
        intent=Intent, intent_filter=lambda action: action,
        pending_intent=SimpleNamespace(FLAG_IMMUTABLE=67108864, getBroadcast=lambda *args: pending),
    )
    monkeypatch.setattr(AndroidUSB, "_api", lambda: api)
    monkeypatch.setattr(AndroidUSB, "_on_ui_thread", lambda factory, *args: factory(*args))
    monkeypatch.setattr(AndroidUSB, "_find_port", lambda address: SimpleNamespace(getDevice=lambda: "device"))
    if granted:
        AndroidUSB.request_permission("androidusb:test#0", timeout=0)
    else:
        with pytest.raises(SerialException, match="denied" if notify else "timed out"):
            AndroidUSB.request_permission("androidusb:test#0", timeout=0)
    assert cleanup == ["receiver", "pending"]


def test_android_discovery_and_reconnect_use_usb_identity(monkeypatch):
    monkeypatch.setattr(AndroidUSB, "is_android", lambda: True)
    port = SimpleNamespace(
        device="androidusb:/dev/bus/usb/001/004#0", vid=0x0403, pid=0x6001,
        serial_number="A50285BI", product="FT232R USB UART",
    )
    monkeypatch.setattr(AndroidUSB, "comports", lambda: [port])
    entries = Utils.list_identifiable_usb_serial_ports()
    assert entries[0]["device_id"] == "0403:6001"
    assert entries[0]["label"] == "A50285BI"
    assert Utils.find_usb_device_path_by_id("0403:6001", "A50285BI") == port.device
    port.device = "androidusb:/dev/bus/usb/001/009#0"
    assert Utils.find_usb_device_path_by_id("0403:6001", "A50285BI") == port.device


def test_android_transport_is_selected_without_changing_desktop(monkeypatch):
    calls = []
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: True)
    monkeypatch.setattr("carveracontroller.USBStream.AndroidSerial", lambda *args, **kwargs: calls.append((args, kwargs)))
    USBStream._serial_for_address("androidusb:test#0", 115200, timeout=0.3, write_timeout=0.3, do_not_open=True)
    assert calls == [(("androidusb:test#0", 115200), {"timeout": 0.3, "write_timeout": 0.3, "do_not_open": True})]
    monkeypatch.setattr("carveracontroller.USBStream.is_android", lambda: False)
    monkeypatch.setattr("serial.serial_for_url", lambda *args, **kwargs: "desktop serial")
    assert USBStream._serial_for_address("COM3", 115200, timeout=0.3, write_timeout=0.3) == "desktop serial"


def test_serial_binary_writes_and_dtr_are_forwarded_to_driver(monkeypatch):
    calls = []

    class JavaError(Exception):
        pass

    monkeypatch.setitem(sys.modules, "jnius", SimpleNamespace(JavaException=JavaError))
    serial = AndroidUSB.AndroidSerial.__new__(AndroidUSB.AndroidSerial)
    serial.buffer = _ReadBuffer()
    serial.timeout = 0
    serial.write_timeout = 0.3
    serial._dtr = False
    serial.port = SimpleNamespace(
        isOpen=lambda: True,
        setDTR=lambda value: calls.append(("dtr", value)),
        write=lambda data, timeout: calls.append((bytes(data), timeout)),
    )
    payload = bytes(range(256))
    assert serial.write(payload) == 256
    serial.setDTR(True)
    assert calls == [(payload, 300), ("dtr", True)]
    serial.buffer.feed(payload)
    assert serial.in_waiting == 256
    assert serial.read(256) == payload

    def detached(data, timeout):
        raise JavaError("device detached")

    serial.port.write = detached
    with pytest.raises(SerialException, match="device detached"):
        serial.write(b"?")
