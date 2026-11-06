"""Restore inherited pipes for Windows GUI-subsystem worker processes."""

import ctypes
import io
import os
import sys


def inherited_pipes():
    if os.name != "nt":
        return
    import msvcrt

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [ctypes.c_ulong]
    kernel.GetStdHandle.restype = ctypes.c_void_p
    for name, identifier, flag, mode in (
        ("stdin", -10, os.O_RDONLY, "rb"),
        ("stdout", -11, os.O_WRONLY, "wb"),
        ("stderr", -12, os.O_WRONLY, "wb"),
    ):
        if getattr(sys, name) is not None:
            continue
        handle = kernel.GetStdHandle(identifier & 0xFFFFFFFF)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise RuntimeError("This worker requires inherited local pipes")
        descriptor = msvcrt.open_osfhandle(handle, flag | os.O_BINARY)
        stream = os.fdopen(descriptor, mode, buffering=0)
        setattr(sys, name, io.TextIOWrapper(stream, encoding="utf-8", line_buffering=True))
