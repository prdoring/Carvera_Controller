"""Platform disk primitives used only after consent and independent worker selection."""

from __future__ import annotations

import contextlib
import ctypes
import os
import re
import stat
import subprocess
import tempfile
import uuid
from pathlib import Path

from kioskdesktop import devices
from kioskdesktop.releases import partition_layout


def run(arguments, *, check=True, timeout=30):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(arguments, check=False, capture_output=True, timeout=timeout, **options)
    if check and result.returncode:
        raise OSError("The selected card is busy or the storage operation failed")
    return result


def windows_kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = ctypes.c_void_p
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
    kernel.DeviceIoControl.argtypes = [
        handle,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel.DeviceIoControl.restype = ctypes.c_int
    kernel.CloseHandle.argtypes = [handle]
    kernel.FlushFileBuffers.argtypes = [handle]
    kernel.SetVolumeMountPointW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    kernel.DeleteVolumeMountPointW.argtypes = [ctypes.c_wchar_p]
    return kernel


def program_data():
    buffer = ctypes.create_unicode_buffer(32768)
    shell = ctypes.WinDLL("shell32")
    shell.SHGetFolderPathW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p]
    if shell.SHGetFolderPathW(None, 0x23, None, 0, buffer) != 0:
        raise OSError("The system data directory is unavailable")
    return Path(buffer.value)


def windows_private_folder(prefix):
    """Create with the final ACL atomically, including under Python 3.12."""

    class Attributes(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("descriptor", ctypes.c_void_p), ("inherit", ctypes.c_int)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    descriptor = ctypes.c_void_p()
    sddl = "O:BAG:BAD:P(A;OICI;FA;;;BA)(A;OICI;FA;;;SY)"
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError("Windows could not protect administrator staging")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        attributes = Attributes(ctypes.sizeof(Attributes), descriptor, 0)
        for _attempt in range(4):
            folder = program_data() / (prefix + uuid.uuid4().hex)
            if kernel.CreateDirectoryW(str(folder), ctypes.byref(attributes)):
                return folder
            if ctypes.get_last_error() != 183:
                raise OSError("Windows could not create private administrator staging")
        raise OSError("Windows could not allocate a private staging directory")
    finally:
        kernel.LocalFree(descriptor)


@contextlib.contextmanager
def private_stage():
    if os.name == "nt":
        import shutil

        path = windows_private_folder("CarveraKiosk-")
        try:
            yield path
        finally:
            shutil.rmtree(path)
        return
    with tempfile.TemporaryDirectory(prefix="CarveraKiosk-", dir="/var/tmp") as name:
        path = Path(name)
        os.chmod(path, 0o700)
        if path.stat().st_uid != 0:
            raise ValueError("The image staging directory must belong to root")
        yield path


class MediaProof:
    """Keep a read-only handle to the selected medium across writer handoff."""

    def __init__(self, device):
        self.device = device
        self.handle = None
        self.descriptor = None
        if os.name == "nt":
            kernel = windows_kernel()
            self.handle = kernel.CreateFileW(device.path, 0, 3, None, 3, 0, None)
            if self.handle == ctypes.c_void_p(-1).value:
                self.handle = None
                raise OSError("The selected medium could not be held for verification")
            try:
                self.generation = self._windows_generation()
            except BaseException:
                self.close()
                raise
        else:
            import fcntl

            self.descriptor = os.open(device.path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            try:
                info = os.fstat(self.descriptor)
                if not stat.S_ISBLK(info.st_mode):
                    raise ValueError("The selected target is not a physical block device")
                self.node = (info.st_dev, info.st_ino, info.st_rdev)
                self.generation = bytes(fcntl.ioctl(self.descriptor, 0x80081280, b"\0" * 8))
                self.sequence = (Path("/sys/class/block") / Path(device.path).name / "diskseq").read_text().strip()
            except BaseException:
                self.close()
                raise

    def _windows_generation(self):
        count, returned = ctypes.c_ulong(), ctypes.c_ulong()
        if (
            not windows_kernel().DeviceIoControl(
                self.handle,
                0x002D0800,
                None,
                0,
                ctypes.byref(count),
                ctypes.sizeof(count),
                ctypes.byref(returned),
                None,
            )
            or returned.value != 4
        ):
            raise OSError("This reader cannot report a stable media identity; use another reader")
        return count.value

    def check(self):
        if os.name == "nt":
            if self._windows_generation() != self.generation:
                raise ValueError("The selected card was removed or replaced; select it again")
        else:
            import fcntl

            current = os.stat(self.device.path, follow_symlinks=False)
            current_node = (current.st_dev, current.st_ino, current.st_rdev)
            sequence = (Path("/sys/class/block") / Path(self.device.path).name / "diskseq").read_text().strip()
            if (
                current_node != self.node
                or sequence != self.sequence
                or bytes(fcntl.ioctl(self.descriptor, 0x80081280, b"\0" * 8)) != self.generation
            ):
                raise ValueError("The selected card was removed or replaced; select it again")

    def close(self):
        if self.handle is not None:
            windows_kernel().CloseHandle(self.handle)
            self.handle = None
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


@contextlib.contextmanager
def disk_lock(device):
    if os.name == "nt":
        # A global mutex is only a concurrency guard; device protections are independently revalidated.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, "Global\\CarveraKiosk-" + device.identity)
        if not handle:
            raise OSError("Could not lock the selected card")
        owned = False
        try:
            result = kernel.WaitForSingleObject(handle, 0)
            if result not in {0, 128}:
                raise ValueError("Another card operation is in progress")
            owned = True
            yield
        finally:
            if owned:
                kernel.ReleaseMutex(handle)
            windows_kernel().CloseHandle(handle)
    else:
        import fcntl

        directory = Path("/run/lock/carvera-kiosk")
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
            raise ValueError("Unsafe card-lock directory")
        descriptor = os.open(directory / device.identity, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w") as lock:
            if os.fstat(lock.fileno()).st_uid != 0:
                raise ValueError("Unsafe card-operation lock")
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("Another card operation is in progress") from error
            yield


def read_layout(device):
    with open(device.path, "rb", buffering=0) as source:
        mbr = source.read(512)
    return partition_layout(mbr, device.capacity)


def refresh(device, proof, protected_paths):
    proof.check()
    if os.name == "nt":
        returned = ctypes.c_ulong()
        if not windows_kernel().DeviceIoControl(
            proof.handle, 0x00070140, None, 0, None, 0, ctypes.byref(returned), None
        ):
            raise OSError("Windows could not refresh the card's partition view")
    else:
        run(["/usr/sbin/blockdev", "--rereadpt", device.path], check=False)
        run(["/usr/bin/udevadm", "settle", "--timeout=15"], check=False)
    return devices.select(device.path, device.identity, protected_paths)


@contextlib.contextmanager
def mounted_boot(device, layout, proof):
    """Never recursively remove a mount point, including on cleanup failure."""
    proof.check()
    if os.name == "nt":
        partitions = [
            part
            for part in device.partitions
            if part.get("offset") == layout.boot_offset
            and part.get("size") == layout.boot_size
            and str(part.get("fstype")).upper() == "FAT32"
        ]
        if len(partitions) != 1 or not re.fullmatch(
            r"\\\\\?\\Volume\{[a-fA-F0-9-]{36}\}\\", str(partitions[0].get("volume", ""))
        ):
            raise ValueError("The selected disk has no uniquely identified kiosk boot volume")
        volume = partitions[0]["volume"]
        folder = windows_private_folder("CarveraKioskMount-")
        mount = str(folder) + "\\"
        if not windows_kernel().SetVolumeMountPointW(mount, volume):
            folder.rmdir()
            raise OSError("Windows could not mount the selected boot volume")
        try:
            yield folder
            handle = windows_kernel().CreateFileW(volume.rstrip("\\"), 0xC0000000, 3, None, 3, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                raise OSError("The configured card could not be flushed")
            try:
                if not windows_kernel().FlushFileBuffers(handle):
                    raise OSError("The configured card could not be flushed")
            finally:
                windows_kernel().CloseHandle(handle)
        finally:
            if not windows_kernel().DeleteVolumeMountPointW(mount):
                raise OSError("Configuration may be saved, but the private mount could not be removed")
            folder.rmdir()
    else:
        partitions = [
            part
            for part in device.partitions
            if int(part.get("start") or -1) * 512 == layout.boot_offset
            and int(part.get("size") or -1) == layout.boot_size
            and part.get("fstype") in {"vfat", "fat"}
            and part.get("partuuid") == layout.boot_partuuid
        ]
        if len(partitions) != 1 or not re.fullmatch(r"/dev/[a-zA-Z0-9_-]+", str(partitions[0].get("path", ""))):
            raise ValueError("The selected disk has no uniquely identified kiosk FAT partition")
        node = partitions[0]["path"]
        folder = Path(tempfile.mkdtemp(prefix="CarveraKioskMount-", dir="/var/tmp"))
        run(["/usr/bin/mount", "-t", "vfat", "-o", "nodev,nosuid,noexec,umask=0077", node, str(folder)])
        try:
            yield folder
            run(["/usr/bin/sync", "-f", str(folder)])
        finally:
            result = run(["/usr/bin/umount", str(folder)], check=False)
            if result.returncode or os.path.ismount(folder):
                raise OSError("Configuration may be saved, but the selected boot volume is still mounted")
            folder.rmdir()


def eject(device, proof):
    proof.check()
    if os.name == "nt":
        returned = ctypes.c_ulong()
        handle = windows_kernel().CreateFileW(device.path, 0x80000000, 3, None, 3, 0, None)
        if handle == ctypes.c_void_p(-1).value:
            raise OSError("Configuration is saved; close applications using the card before ejecting it")
        try:
            if not windows_kernel().DeviceIoControl(handle, 0x002D4808, None, 0, None, 0, ctypes.byref(returned), None):
                raise OSError(
                    "Configuration is saved; Windows could not eject the card. Close applications using it and retry"
                )
        finally:
            windows_kernel().CloseHandle(handle)
    else:
        for part in device.partitions:
            node = part.get("path")
            if part.get("mountpoints") and any(part["mountpoints"]):
                run(["/usr/bin/umount", "--all-targets", node])
        run(["/usr/bin/sync"])
        run(["/usr/sbin/blockdev", "--flushbufs", device.path])
