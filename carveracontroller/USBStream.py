from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable

import serial

from .AndroidUSB import AndroidSerial, is_android
from .XMODEM import XMODEM

logger = logging.getLogger(__name__)

SERIAL_TIMEOUT = 0.3  # s


# ==============================================================================
# USB stream class
# ==============================================================================
class USBStream:
    serial = None

    # ----------------------------------------------------------------------
    def __init__(self, log_sent_receive=False):
        self.modem = XMODEM(self.getc, self.putc, "xmodem")
        # Rely on the app/Kivy root logger; do not attach extra StreamHandlers to
        # the shared "xmodem.XMODEM" logger (USB+WiFi would duplicate every line).
        self.log_sent_receive = log_sent_receive
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        self._read_buffer = bytearray()
        self._write_lock = threading.Lock()
        self.initial_baud = 115200
        self.download_finished: Callable[[], None] | None = None
        # Set by Controller when the communication protocol is selected.
        self.uses_framed_transfer = False

    # ----------------------------------------------------------------------
    def send(self, data):
        if isinstance(data, str):
            data = data.encode("utf-8", errors="replace")
        with self._write_lock:
            port = self.serial
            if port is None:
                return
            if (
                sys.platform.startswith("linux")
                and not is_android()
                and self.uses_framed_transfer
                and port.baudrate > 460800
            ):
                # Allow the mill to receive control frames between USB bursts.
                for offset in range(0, len(data), 8):
                    port.write(data[offset : offset + 8])
                    if offset + 8 < len(data):
                        port.flush()
                        time.sleep(0.001)
            else:
                port.write(data)
        if not self.log_sent_receive:
            return
        if data == b"?":
            logger.debug("SENT: ?")
            return
        self._send_log_buffer += data
        while b"\n" in self._send_log_buffer:
            idx = self._send_log_buffer.index(b"\n") + 1
            line = self._send_log_buffer[:idx]
            self._send_log_buffer = self._send_log_buffer[idx:]
            line_str = line.decode("utf-8", errors="replace").rstrip("\r\n")
            logger.debug("SENT: %s", line_str)
        if len(self._send_log_buffer) > 4096:
            logger.debug("SENT: <%d bytes (no newline)>", len(self._send_log_buffer))
            self._send_log_buffer = b""

    # ----------------------------------------------------------------------
    def recv(self):
        if self.serial is None:
            return b""
        if self._read_buffer:
            data = bytes(self._read_buffer[:4096])
            del self._read_buffer[:4096]
        else:
            data = self.serial.read(max(1, min(self.serial.in_waiting, 4096)))
        if self.log_sent_receive and data:
            self._recv_log_buffer += data
            while b"\n" in self._recv_log_buffer:
                idx = self._recv_log_buffer.index(b"\n") + 1
                line = self._recv_log_buffer[:idx]
                self._recv_log_buffer = self._recv_log_buffer[idx:]
                logger.debug("RECV: %s", line.decode("utf-8", errors="replace").rstrip("\r\n"))
            if len(self._recv_log_buffer) > 4096:
                logger.debug("RECV: <%d bytes (no newline)>", len(self._recv_log_buffer))
                self._recv_log_buffer = b""
        return data

    # ----------------------------------------------------------------------
    def open(self, address, baud=115200):
        self._read_buffer.clear()
        self.initial_baud = int(baud)
        self._address = address.replace("\\", "\\\\")
        self.serial = self._serial_for_address(
            self._address,
            baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
            xonxoff=False,
            rtscts=False,
        )
        self._set_low_latency(self.serial)
        # Toggle DTR to reset Arduino
        try:
            self.serial.setDTR(0)
        except OSError:
            pass
        time.sleep(0.5)

        self.serial.flushInput()
        try:
            self.serial.setDTR(1)
        except OSError:
            pass
        time.sleep(0.5)

        # Try to clear machine receive buffer from a previous controller session
        self.serial.write(b"\n;\n")

        return True

    @staticmethod
    def _set_low_latency(port):
        if not sys.platform.startswith("linux") or is_android():
            return
        try:
            port.set_low_latency_mode(True)
        except (AttributeError, OSError, ValueError):
            logger.debug("USB serial driver does not support low-latency mode", exc_info=True)

    @staticmethod
    def _serial_for_address(address, baud, **kwargs):
        if is_android():
            return AndroidSerial(
                address,
                baud,
                timeout=kwargs["timeout"],
                write_timeout=kwargs["write_timeout"],
                do_not_open=kwargs.get("do_not_open", False),
            )
        return serial.serial_for_url(address, baud, **kwargs)

    # ----------------------------------------------------------------------
    def reopen_at_baud(self, baud):
        """
        Close and reopen the serial port at a new baud rate.
        """
        if not self._address:
            return False
        baud = int(baud)
        old = self.serial
        self.serial = None
        self._read_buffer.clear()
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        if old is not None:
            try:
                old.dtr = False
                old.rts = False
            except Exception:
                pass
            try:
                old.close()
            except Exception:
                pass
        time.sleep(0.1)
        try:
            ser = self._serial_for_address(
                self._address,
                baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=SERIAL_TIMEOUT,
                write_timeout=SERIAL_TIMEOUT,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
                do_not_open=True,
            )
            try:
                ser.dtr = False
                ser.rts = False
            except Exception:
                pass
            ser.open()
            self._set_low_latency(ser)
            try:
                ser.dtr = False
            except Exception:
                pass
            try:
                ser.reset_input_buffer()
                ser.reset_output_buffer()
            except Exception:
                pass
            self.serial = ser
            return True
        except Exception:
            logger.exception("Failed to reopen serial at %s baud", baud)
            return False

    # ----------------------------------------------------------------------
    def close(self):
        if self.serial is None:
            return None
        time.sleep(0.5)
        try:
            self.modem.clear_mode_set()
            self.serial.close()
        except:
            pass
        self.serial = None
        self._read_buffer.clear()
        self._send_log_buffer = b""
        self._recv_log_buffer = b""
        return True

    # ----------------------------------------------------------------------
    def waiting_for_send(self):
        if self.serial is None:
            return False
        return self.serial.out_waiting < 1

    # ----------------------------------------------------------------------
    def waiting_for_recv(self):
        if self.serial is None:
            return 0
        return len(self._read_buffer) + self.serial.in_waiting

    def reset_input_buffer(self):
        self._read_buffer.clear()
        if self.serial is not None:
            self.serial.reset_input_buffer()

    # ----------------------------------------------------------------------
    def is_link_up(self):
        """Return True if the serial port is still open and present.

        ``serial.is_open`` is only an internal flag (tracks whether .close()
        was called) and stays True after a physical USB unplug.  Probing
        ``in_waiting`` forces an ioctl on the fd and raises OSError (e.g.
        errno 6 "Device not configured" on macOS) when the device is gone.
        """
        if self.serial is None:
            return False
        try:
            if not self.serial.is_open:
                return False
            _ = self.serial.in_waiting  # ioctl probe — raises on dead device
            return True
        except OSError:
            # SerialException subclasses OSError. Other errors propagate so a
            # bug in the probe is not reported as a dead cable.
            return False

    # ----------------------------------------------------------------------
    def getc(self, size, timeout=1):
        if self.serial is None:
            return None
        if sys.platform.startswith("linux") and not is_android() and self.uses_framed_transfer:
            # File frames request header bytes individually. Keep available bytes
            # here so each header byte does not need another serial read.
            if len(self._read_buffer) < size:
                needed = size - len(self._read_buffer)
                self._read_buffer.extend(self.serial.read(max(needed, min(self.serial.in_waiting, 4096))))
            data = bytes(self._read_buffer[:size])
            del self._read_buffer[:size]
            return data or None
        return self.serial.read(size) or None

    def putc(self, data, timeout=1):
        with self._write_lock:
            if self.serial is None:
                return None
            return self.serial.write(data) or None

    def upload(self, filename, local_md5, callback):
        stream = open(filename, "rb")
        if self.uses_framed_transfer:
            result = self.modem.send(stream, md5=local_md5, retry=50, callback=callback)
        else:
            result = self.modem.send_legacy(stream, md5=local_md5, retry=10, callback=callback)
        stream.close()
        return result

    def download(self, filename, local_md5, callback):
        stream = open(filename, "wb")
        if self.uses_framed_transfer:
            result = self.modem.recv(stream, md5=local_md5, retry=50, callback=callback)
        else:
            result = self.modem.recv_legacy(stream, md5=local_md5, retry=10, callback=callback)
        stream.close()
        if (
            result is not None
            and result >= 0
            and sys.platform.startswith("linux")
            and not is_android()
            and self.uses_framed_transfer
            and self.serial is not None
            and self.serial.baudrate != self.initial_baud
            and self.download_finished is not None
        ):
            self.download_finished()
        return result

    def cancel_process(self):
        self.modem.canceled = True
