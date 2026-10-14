"""Android USB host serial access, without Linux serial device nodes.

Java classes are loaded only on Android. Serial reads are buffered by the
driver's reader thread so polling ``in_waiting`` never blocks the UI.
"""

import os
import sys
import threading
import time
import uuid
from functools import lru_cache
from types import SimpleNamespace

from serial import SerialException


def is_android():
    return sys.platform == "android" or "ANDROID_ARGUMENT" in os.environ


@lru_cache(maxsize=1)
def _api():
    from android.config import JAVA_NAMESPACE, JNI_NAMESPACE
    from jnius import PythonJavaClass, autoclass, java_method

    class PermissionCallback(PythonJavaClass):
        __javainterfaces__ = [JNI_NAMESPACE + "/GenericBroadcastReceiverCallback"]
        __javacontext__ = "app"

        def __init__(self, event):
            super().__init__()
            self.event = event

        @java_method("(Landroid/content/Context;Landroid/content/Intent;)V")
        def onReceive(self, context, intent):
            self.event.set()

    class ReaderCallback(PythonJavaClass):
        __javainterfaces__ = ["com/hoho/android/usbserial/util/SerialInputOutputManager$Listener"]
        __javacontext__ = "app"

        def __init__(self, buffer):
            super().__init__()
            self.buffer = buffer

        @java_method("([B)V")
        def onNewData(self, data):
            self.buffer.feed(bytes(value & 0xFF for value in data))

        @java_method("(Ljava/lang/Exception;)V")
        def onRunError(self, error):
            self.buffer.fail(error.toString())

    activity = autoclass("org.kivy.android.PythonActivity").mActivity
    return SimpleNamespace(
        activity=activity,
        manager=activity.getSystemService("usb"),
        prober=autoclass("com.hoho.android.usbserial.driver.UsbSerialProber").getDefaultProber(),
        io_manager=autoclass("com.hoho.android.usbserial.util.SerialInputOutputManager"),
        receiver=autoclass(JAVA_NAMESPACE + ".GenericBroadcastReceiver"),
        intent=autoclass("android.content.Intent"),
        intent_filter=autoclass("android.content.IntentFilter"),
        pending_intent=autoclass("android.app.PendingIntent"),
        sdk=autoclass("android.os.Build$VERSION").SDK_INT,
        permission_callback=PermissionCallback,
        reader_callback=ReaderCallback,
    )


def _ports():
    api = _api()
    drivers = api.prober.findAllDrivers(api.manager)
    for driver in drivers.toArray():
        yield from driver.getPorts().toArray()


def _address(port):
    return f"androidusb:{port.getDevice().getDeviceName()}#{port.getPortNumber()}"


def comports():
    """Return the same identity fields used by desktop port discovery."""
    api = _api()
    for port in _ports():
        device = port.getDevice()
        serial = device.getSerialNumber() if api.manager.hasPermission(device) else ""
        yield SimpleNamespace(
            device=_address(port),
            vid=device.getVendorId(),
            pid=device.getProductId(),
            serial_number=serial or "",
            product=device.getProductName() or "USB serial",
        )


def _find_port(address):
    for port in _ports():
        if _address(port) == address:
            return port
    raise SerialException("USB device is no longer attached")


def _on_ui_thread(factory, *args):
    # JNI FindClass on a Python-created thread cannot resolve APK interfaces.
    # Construct proxies and objects accepting them in the activity's JNI context.
    from android.runnable import run_on_ui_thread

    completed = threading.Event()
    result = []
    errors = []

    @run_on_ui_thread
    def create():
        try:
            result.append(factory(*args))
        except Exception as error:
            errors.append(error)
        finally:
            completed.set()

    create()
    if not completed.wait(10):
        raise SerialException("Android USB callback initialization timed out")
    if errors:
        raise SerialException(str(errors[0])) from errors[0]
    return result[0]


def request_permission(address, timeout=60):
    """Ask Android for access; call from the connection worker, before switching links."""
    api = _api()
    device = _find_port(address).getDevice()
    if api.manager.hasPermission(device):
        return
    event = threading.Event()
    callback = _on_ui_thread(api.permission_callback, event)
    receiver = _on_ui_thread(api.receiver, callback)
    action = api.activity.getPackageName() + ".USB_PERMISSION." + uuid.uuid4().hex
    intent = api.intent(action).setPackage(api.activity.getPackageName())
    pending = api.pending_intent.getBroadcast(api.activity, 0, intent, api.pending_intent.FLAG_IMMUTABLE)
    intent_filter = api.intent_filter(action)
    if api.sdk >= 33:
        api.activity.registerReceiver(receiver, intent_filter, 4)  # Context.RECEIVER_NOT_EXPORTED
    else:
        api.activity.registerReceiver(receiver, intent_filter)
    try:
        api.manager.requestPermission(device, pending)
        if not event.wait(timeout):
            raise SerialException("USB permission request timed out")
        # Check the OS grant rather than trusting broadcast extras.
        if not api.manager.hasPermission(device):
            raise SerialException("USB permission was denied")
    finally:
        api.activity.unregisterReceiver(receiver)
        pending.cancel()


class _ReadBuffer:
    def __init__(self):
        self.condition = threading.Condition()
        self.data = bytearray()
        self.error = None
        self.closed = False

    def _check(self):
        if self.error is not None:
            raise SerialException(self.error)
        if self.closed:
            raise SerialException("USB serial port is closed")

    def feed(self, data):
        with self.condition:
            if self.closed or self.error is not None:
                return
            if len(self.data) + len(data) > 1024 * 1024:
                self.error = "USB receive buffer overflow"
            else:
                self.data.extend(data)
            self.condition.notify_all()

    def fail(self, error):
        with self.condition:
            self.error = error
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()

    def clear(self):
        with self.condition:
            self.data.clear()

    @property
    def waiting(self):
        with self.condition:
            self._check()
            return len(self.data)

    def read(self, size, timeout):
        deadline = time.monotonic() + timeout
        with self.condition:
            self._check()
            while len(self.data) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
                self._check()
            result = bytes(self.data[:size])
            del self.data[:size]
            return result


class AndroidSerial:
    """The pySerial subset used by USBStream, including binary file transfers."""

    def __init__(self, address, baudrate, timeout, write_timeout, do_not_open=False):
        self.port = _find_port(address)
        self.timeout = timeout
        self.write_timeout = write_timeout
        self.baudrate = baudrate
        self._dtr = False
        self._rts = False
        self.buffer = _ReadBuffer()
        self.reader = None
        self.callback = None
        if not do_not_open:
            self.open()

    @staticmethod
    def _call(method, *args):
        from jnius import JavaException

        try:
            return method(*args)
        except JavaException as error:
            raise SerialException(str(error)) from error

    def open(self):
        api = _api()
        if not api.manager.hasPermission(self.port.getDevice()):
            raise SerialException("USB permission is required before opening the port")
        connection = api.manager.openDevice(self.port.getDevice())
        if connection is None:
            raise SerialException("Android could not open the USB device")
        try:
            self._call(self.port.open, connection)
            self._call(self.port.setParameters, self.baudrate, 8, 1, 0)
            self._call(self.port.setDTR, self._dtr)
            self._call(self.port.setRTS, self._rts)
            self.callback = _on_ui_thread(api.reader_callback, self.buffer)
            self.reader = _on_ui_thread(api.io_manager, self.port, self.callback)
            self.reader.setReadBufferSize(16384)
            self.reader.start()
        except Exception:
            self.close()
            connection.close()
            raise

    @property
    def is_open(self):
        return bool(self.port.isOpen())

    @property
    def in_waiting(self):
        return self.buffer.waiting

    @property
    def out_waiting(self):
        # Writes are synchronous: no application output queue remains afterward.
        _ = self.buffer.waiting
        return 0

    def read(self, size=1):
        return self.buffer.read(size, self.timeout)

    def write(self, data):
        _ = self.buffer.waiting
        self._call(self.port.write, bytearray(data), max(1, int(self.write_timeout * 1000)))
        return len(data)

    def close(self):
        self.buffer.close()
        if self.reader is not None:
            self.reader.stop()
        if self.is_open:
            self._call(self.port.close)

    def setDTR(self, value=True):
        self.dtr = value

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = bool(value)
        if self.is_open:
            self._call(self.port.setDTR, self._dtr)

    @property
    def rts(self):
        return self._rts

    @rts.setter
    def rts(self, value):
        self._rts = bool(value)
        if self.is_open:
            self._call(self.port.setRTS, self._rts)

    def reset_input_buffer(self):
        self._call(self.port.purgeHwBuffers, False, True)
        self.buffer.clear()

    flushInput = reset_input_buffer

    def reset_output_buffer(self):
        self._call(self.port.purgeHwBuffers, True, False)
