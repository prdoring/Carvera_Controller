"""Authenticated local worker channels; configuration never appears in arguments."""

from __future__ import annotations

import ctypes
import json
import os
import secrets
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

MAX_MESSAGE = 65536


class Channel:
    def __init__(self, connection, *, windows=False):
        self.connection = connection
        self.windows = windows
        self.closed = False

    def read(self, size):
        if not self.windows:
            return self.connection.recv(size)
        kernel = windows_kernel()
        buffer = ctypes.create_string_buffer(min(size, 1024**2))
        count = ctypes.c_ulong()
        if not kernel.ReadFile(self.connection, buffer, len(buffer), ctypes.byref(count), None):
            if ctypes.get_last_error() in {109, 232, 233, 995}:
                return b""
            raise OSError("The local worker pipe could not be read")
        return buffer.raw[: count.value]

    def exact(self, size):
        output = bytearray()
        while len(output) < size:
            chunk = self.read(min(size - len(output), 1024**2))
            if not chunk:
                raise InterruptedError("The local worker connection closed")
            output.extend(chunk)
        return bytes(output)

    def write(self, data):
        if not self.windows:
            self.connection.sendall(data)
            return
        kernel = windows_kernel()
        view = memoryview(data)
        while view:
            part = bytes(view[: 1024**2])
            count = ctypes.c_ulong()
            if not kernel.WriteFile(self.connection, part, len(part), ctypes.byref(count), None) or not count.value:
                raise InterruptedError("The local worker connection closed")
            view = view[count.value :]

    def send(self, value):
        data = json.dumps(value, ensure_ascii=True).encode("utf-8")
        if len(data) > MAX_MESSAGE:
            raise ValueError("Worker message exceeds its limit")
        self.write(struct.pack("!I", len(data)) + data)

    def receive(self):
        length = struct.unpack("!I", self.exact(4))[0]
        if length > MAX_MESSAGE:
            raise ValueError("Worker message exceeds its limit")
        value = json.loads(self.exact(length))
        if not isinstance(value, dict):
            raise ValueError("Expected a worker object")
        return value

    def alive(self):
        if self.closed:
            return False
        if self.windows:
            available = ctypes.c_ulong()
            return bool(windows_kernel().PeekNamedPipe(self.connection, None, 0, None, ctypes.byref(available), None))
        readable, _, _ = select.select([self.connection], [], [], 0)
        return not readable or bool(self.connection.recv(1, socket.MSG_PEEK))

    def readable(self):
        if self.closed:
            return False
        if self.windows:
            available = ctypes.c_ulong()
            if not windows_kernel().PeekNamedPipe(self.connection, None, 0, None, ctypes.byref(available), None):
                raise InterruptedError("The setup application disconnected")
            return available.value >= 4
        return bool(select.select([self.connection], [], [], 0)[0])

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.windows:
            kernel = windows_kernel()
            kernel.CancelIoEx(self.connection, None)
            kernel.CloseHandle(self.connection)
        else:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()


def windows_kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
    kernel.CreateNamedPipeW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    kernel.CreateNamedPipeW.restype = handle
    kernel.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        handle,
    ]
    kernel.CreateFileW.restype = handle
    for name in (
        "CloseHandle",
        "ConnectNamedPipe",
        "PeekNamedPipe",
        "ReadFile",
        "WriteFile",
        "CancelIoEx",
        "GetNamedPipeClientProcessId",
        "GetNamedPipeServerProcessId",
    ):
        function = getattr(kernel, name)
        # Declaring the leading handle avoids pointer truncation on Windows x64.
        if name == "CloseHandle":
            function.argtypes = [handle]
        elif name in {"ConnectNamedPipe", "CancelIoEx", "GetNamedPipeClientProcessId", "GetNamedPipeServerProcessId"}:
            function.argtypes = [handle, ctypes.c_void_p]
        elif name in {"ReadFile", "WriteFile"}:
            function.argtypes = [handle, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
        else:
            function.argtypes = [
                handle,
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
        function.restype = ctypes.c_int
    return kernel


def windows_sid():
    import csv

    from kioskdesktop.devices import windows_system_directory

    result = subprocess.run(
        [str(windows_system_directory() / "whoami.exe"), "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sid = next(csv.reader(result.stdout.splitlines()))[-1]
    if not sid.startswith("S-1-") or any(character not in "S-0123456789" for character in sid):
        raise ValueError("Could not identify the local pipe owner")
    return sid


class Endpoint:
    def __init__(self):
        self.nonce = secrets.token_hex(32)
        self.channel = None
        self.directory = None
        self.listener = None
        self.handle = None
        if os.name == "nt":
            self.address = r"\\.\pipe\CarveraKiosk-" + self.nonce
            self.handle = self.create_pipe()
        else:
            self.directory = tempfile.TemporaryDirectory(prefix="carvera-kiosk-")
            os.chmod(self.directory.name, 0o700)
            self.address = str(Path(self.directory.name) / "worker.sock")
            self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.listener.bind(self.address)
            self.listener.listen(1)
            self.listener.settimeout(120)

    def create_pipe(self):
        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("descriptor", ctypes.c_void_p), ("inherit", ctypes.c_int)]

        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        descriptor = ctypes.c_void_p()
        sddl = f"D:P(A;;GA;;;{windows_sid()})(A;;GA;;;BA)(A;;GA;;;SY)"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise OSError("Could not protect the local worker pipe")
        try:
            attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, 0)
            handle = windows_kernel().CreateNamedPipeW(
                self.address, 0x00080003, 0x8, 1, 65536, 65536, 30000, ctypes.byref(attributes)
            )
            if handle == ctypes.c_void_p(-1).value:
                raise OSError("Could not create the local worker pipe")
            return handle
        finally:
            kernel = ctypes.WinDLL("kernel32")
            kernel.LocalFree.argtypes = [ctypes.c_void_p]
            kernel.LocalFree(descriptor)

    def accept(self, expected_pid, process=None):
        if os.name == "nt":
            kernel = windows_kernel()
            completed = threading.Event()
            outcome = []
            handle = self.handle

            def wait_connection():
                success = kernel.ConnectNamedPipe(handle, None)
                outcome.append(bool(success or ctypes.get_last_error() == 535))
                completed.set()

            waiter = threading.Thread(target=wait_connection, name="owned-pipe-connect", daemon=True)
            waiter.start()
            deadline = time.monotonic() + 120
            while not completed.wait(0.1):
                if time.monotonic() > deadline or self.handle is None or (process and process.poll() is not None):
                    kernel.OpenThread.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
                    kernel.OpenThread.restype = ctypes.c_void_p
                    thread = kernel.OpenThread(1, False, waiter.native_id)
                    if thread:
                        kernel.CancelSynchronousIo.argtypes = [ctypes.c_void_p]
                        kernel.CancelSynchronousIo(thread)
                        kernel.CloseHandle(thread)
                    self.close()
                    waiter.join(5)
                    raise PermissionError("The card worker did not obtain permission or the operation was cancelled")
            if not outcome[0]:
                raise OSError("Worker connection failed")
            pid = ctypes.c_ulong()
            if not kernel.GetNamedPipeClientProcessId(self.handle, ctypes.byref(pid)) or pid.value != expected_pid:
                raise ValueError("Unexpected local worker process")
            self.channel = Channel(self.handle, windows=True)
            self.handle = None
        else:
            deadline = time.monotonic() + 120
            self.listener.settimeout(0.25)
            while True:
                try:
                    connection, _address = self.listener.accept()
                    break
                except TimeoutError:
                    if time.monotonic() > deadline or (process and process.poll() is not None):
                        raise PermissionError("The card worker did not obtain permission") from None
            pid, uid, _gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            if uid != 0:
                connection.close()
                raise ValueError("The disk worker did not obtain administrator permission")
            # pkexec may replace its launcher; root peer credentials and the nonce bind the session.
            self.channel = Channel(connection)
        hello = self.channel.receive()
        if hello != {"protocol": 1, "nonce": self.nonce}:
            self.close()
            raise ValueError("Invalid worker handshake")
        return self.channel

    def close(self):
        if self.channel:
            self.channel.close()
        if self.listener:
            self.listener.close()
        if self.handle:
            windows_kernel().CloseHandle(self.handle)
            self.handle = None
        if self.directory:
            self.directory.cleanup()


def worker_connection(address, nonce, owner_pid):
    if len(nonce) != 64 or any(character not in "0123456789abcdef" for character in nonce):
        raise ValueError("Invalid worker session")
    if os.name == "nt":
        if address != r"\\.\pipe\CarveraKiosk-" + nonce:
            raise ValueError("Invalid local worker pipe")
        kernel = windows_kernel()
        handle = kernel.CreateFileW(address, 0xC0000000, 0, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError("The setup application is no longer waiting")
        pid = ctypes.c_ulong()
        if not kernel.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)) or pid.value != owner_pid:
            kernel.CloseHandle(handle)
            raise ValueError("Unexpected setup application")
        channel = Channel(handle, windows=True)
    else:
        path = Path(address)
        owner = os.environ.get("PKEXEC_UID")
        if not owner or not owner.isdigit() or path.parent.is_symlink() or path.is_symlink():
            raise ValueError("Launch the worker through the setup application's permission prompt")
        info = path.parent.stat()
        if info.st_uid != int(owner) or info.st_mode & 0o077:
            raise ValueError("Unsafe local worker endpoint")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(address)
        pid, uid, _gid = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != int(owner) or pid != owner_pid:
            connection.close()
            raise ValueError("Unexpected setup application")
        channel = Channel(connection)
    channel.send({"protocol": 1, "nonce": nonce})
    return channel
