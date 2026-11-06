"""Inspect native executable identities without executing an elevated program."""

import ctypes
import struct


def windows_version(path):
    library = ctypes.WinDLL("version", use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    library.GetFileVersionInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    library.VerQueryValueW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p]
    size = library.GetFileVersionInfoSizeW(str(path), None)
    if not 0 < size <= 1024**2:
        raise ValueError("The writer has no bounded Windows version resource")
    buffer = ctypes.create_string_buffer(size)
    if not library.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise OSError("The writer's version resource could not be read")
    value, length = ctypes.c_void_p(), ctypes.c_uint()
    if not library.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(length)) or length.value < 52:
        raise ValueError("The writer has no fixed version identity")
    fields = ctypes.cast(value, ctypes.POINTER(ctypes.c_uint32 * 13)).contents
    if fields[0] != 0xFEEF04BD:
        raise ValueError("Invalid executable version identity")
    return fields[2] >> 16, fields[2] & 0xFFFF, fields[3] >> 16, fields[3] & 0xFFFF


def architecture(path):
    with path.open("rb") as source:
        header = source.read(64)
        if header[:2] == b"MZ" and len(header) == 64:
            source.seek(struct.unpack_from("<I", header, 60)[0])
            pe = source.read(6)
            if pe[:4] == b"PE\0\0" and len(pe) == 6:
                return {0x8664: "windows-x64", 0xAA64: "windows-arm64"}.get(struct.unpack_from("<H", pe, 4)[0])
        if len(header) >= 20 and header[:6] == b"\x7fELF\x02\x01":
            return {62: "linux-x64", 183: "linux-arm64"}.get(struct.unpack_from("<H", header, 18)[0])
    raise ValueError("The native executable has an unsupported architecture")
