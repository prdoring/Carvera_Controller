"""Native permission prompts for a short-lived, fixed disk worker."""

import ctypes
import os
import subprocess
import sys
from pathlib import Path


def elevated():
    return bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else os.geteuid() == 0


def origin_home(owner_pid):
    """Protect the authenticated GUI owner's home, including alternate-admin UAC."""
    if os.name != "nt":
        import pwd

        owner = os.environ.get("PKEXEC_UID", "")
        if not owner.isdigit():
            raise ValueError("The permission prompt did not identify the original desktop user")
        return Path(pwd.getpwuid(int(owner)).pw_dir).resolve(strict=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    process = kernel.OpenProcess(0x1000, False, owner_pid)
    if not process:
        raise OSError("The original desktop user could not be identified")
    token = ctypes.c_void_p()
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p]
        if not advapi.OpenProcessToken(process, 0x8, ctypes.byref(token)):
            raise OSError("The original desktop user's identity could not be read")
        userenv = ctypes.WinDLL("userenv", use_last_error=True)
        userenv.GetUserProfileDirectoryW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p]
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not userenv.GetUserProfileDirectoryW(token, buffer, ctypes.byref(size)):
            raise OSError("The original desktop user's home could not be located")
        return Path(buffer.value).resolve(strict=True)
    finally:
        if token.value:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)


class WindowsProcess:
    def __init__(self, handle):
        self.handle = handle
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetProcessId.argtypes = [ctypes.c_void_p]
        kernel.GetProcessId.restype = ctypes.c_ulong
        self.pid = kernel.GetProcessId(handle)
        if not self.pid:
            raise OSError("The administrator worker has no process identity")

    def poll(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        code = ctypes.c_ulong()
        if not kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError("The administrator worker could not be inspected")
        return None if code.value == 259 else code.value

    def close(self):
        if self.handle:
            kernel = ctypes.WinDLL("kernel32")
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.handle)
            self.handle = None


def launch(endpoint, window=None):
    if not getattr(sys, "frozen", False):
        raise ValueError("Use the packaged Setup app for card writing; source previews cannot elevate")
    if elevated():
        raise ValueError("Open Setup as your normal user; grant administrator permission only for the card operation")
    arguments = ["--disk-worker", endpoint.address, endpoint.nonce, str(os.getpid())]
    if os.name != "nt":
        return subprocess.Popen(
            ["/usr/bin/pkexec", sys.executable, *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("size", ctypes.c_ulong),
            ("mask", ctypes.c_ulong),
            ("window", ctypes.c_void_p),
            ("verb", ctypes.c_wchar_p),
            ("file", ctypes.c_wchar_p),
            ("parameters", ctypes.c_wchar_p),
            ("directory", ctypes.c_wchar_p),
            ("show", ctypes.c_int),
            ("instance", ctypes.c_void_p),
            ("id_list", ctypes.c_void_p),
            ("class_name", ctypes.c_wchar_p),
            ("class_key", ctypes.c_void_p),
            ("hotkey", ctypes.c_ulong),
            ("icon", ctypes.c_void_p),
            ("process", ctypes.c_void_p),
        ]

    info = ShellExecuteInfo()
    info.size = ctypes.sizeof(info)
    info.mask = 0x40 | 0x100 | 0x400
    info.window = window
    info.verb = "runas"
    info.file = sys.executable
    info.parameters = subprocess.list2cmdline(arguments)
    info.show = 0
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = ctypes.c_int
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        if ctypes.get_last_error() == 1223:
            raise PermissionError("Administrator permission was cancelled")
        raise OSError("Windows could not start the card worker")
    return WindowsProcess(info.process)
