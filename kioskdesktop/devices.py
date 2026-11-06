"""Read-only physical-media inventory and immutable selection identities."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Device:
    path: str
    identity: str
    capacity: int
    description: str
    transport: str
    protected: bool
    read_only: bool
    virtual: bool
    partitions: tuple = ()

    @property
    def eligible(self):
        return bool(self.identity and self.capacity > 0 and not (self.protected or self.read_only or self.virtual))

    def public(self):
        return {key: value for key, value in asdict(self).items() if key != "partitions"}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def command(arguments, *, timeout=20):
    creation = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(arguments, check=True, capture_output=True, timeout=timeout, **creation)
    if len(result.stdout) > 1024**2 or len(result.stderr) > 65536:
        raise ValueError("Storage inventory exceeded its limit")
    return result.stdout.decode("utf-8-sig")


def descendants(node):
    yield node
    for child in node.get("children", []):
        yield from descendants(child)


def linux_devices(value, protected_numbers, generations):
    if not isinstance(value, dict) or not isinstance(value.get("blockdevices"), list):
        raise ValueError("The system did not provide a valid storage inventory")
    devices = []
    for disk in value["blockdevices"]:
        if disk.get("type") not in {"disk", "loop"}:
            continue
        name = Path(disk.get("kname", "")).name
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            continue
        nodes = list(descendants(disk))
        protected = any(node.get("maj:min") in protected_numbers for node in nodes)
        virtual = disk.get("type") == "loop" or name.startswith(("loop", "vd", "ram", "dm-"))
        transport = str(disk.get("tran") or "").lower()
        generation = generations.get(name)
        removable = transport == "usb" or (name.startswith("mmcblk") and generation and generation.get("media") == "SD")
        stable = {
            "path": disk.get("path"),
            "device": disk.get("maj:min"),
            "generation": generation,
            "size": disk.get("size"),
            "serial": disk.get("serial"),
            "wwn": disk.get("wwn"),
        }
        identity = fingerprint(stable) if generation and disk.get("path") == "/dev/" + name else ""
        partitions = tuple(
            {
                key: node.get(key)
                for key in ("path", "type", "size", "start", "fstype", "partuuid", "maj:min", "mountpoints")
            }
            for node in nodes[1:]
            if node.get("type") == "part"
        )
        devices.append(
            Device(
                "/dev/" + name,
                identity,
                int(disk.get("size") or 0),
                str(disk.get("model") or name).strip(),
                transport,
                protected or not removable,
                bool(disk.get("ro")),
                virtual,
                partitions,
            )
        )
    return devices


def linux_inventory(protected_paths):
    fields = "NAME,KNAME,PATH,MAJ:MIN,SIZE,RO,RM,HOTPLUG,TYPE,TRAN,SERIAL,WWN,MODEL,MOUNTPOINTS,FSTYPE,PARTUUID,START"
    value = json.loads(command(["/usr/bin/lsblk", "--json", "--bytes", "--paths", "--output", fields]))
    protected = set()
    for path in protected_paths:
        path = Path(path)
        while not path.exists() and path != path.parent:
            path = path.parent
        info = path.stat()
        protected.add(f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}")
    generations = {}
    for disk in value.get("blockdevices", []):
        name = Path(disk.get("kname", "")).name
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
            continue
        folder = Path("/sys/class/block") / name
        try:
            sequence = (folder / "diskseq").read_text().strip()
            if not sequence.isdigit():
                continue
            media = (folder / "device/type").read_text().strip() if name.startswith("mmcblk") else ""
            generations[name] = {"sequence": sequence, "media": media}
        except OSError:
            continue
    return linux_devices(value, protected, generations)


def windows_system_directory():
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise OSError("The Windows system directory is unavailable")
    return Path(buffer.value)


def powershell(script):
    executable = windows_system_directory() / "WindowsPowerShell/v1.0/powershell.exe"
    return command([str(executable), "-NoProfile", "-NonInteractive", "-Command", script])


def windows_volume(path):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetVolumePathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetVolumeNameForVolumeMountPointW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    mount, volume = ctypes.create_unicode_buffer(32768), ctypes.create_unicode_buffer(32768)
    if not kernel.GetVolumePathNameW(str(Path(path).resolve()), mount, len(mount)):
        raise OSError("A protected file's storage volume could not be identified")
    if not kernel.GetVolumeNameForVolumeMountPointW(mount, volume, len(volume)):
        raise OSError("A protected storage volume could not be identified")
    return volume.value


def windows_inventory(protected_paths):
    # Import the system Storage module by its absolute, trusted path.
    script = r"""
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSHOME 'Modules\Storage\Storage.psd1')
$items=@(Get-Disk | ForEach-Object {
 $disk=$_
 $known=$true
 try { $partitions=@(Get-Partition -DiskNumber $disk.Number -ErrorAction Stop) }
 catch { $partitions=@(); if ([string]$disk.PartitionStyle -ne 'RAW') { $known=$false } }
 $parts=@($partitions | ForEach-Object {
  $part=$_
  $volume=Get-Volume -Partition $part -ErrorAction SilentlyContinue
  [pscustomobject]@{number=$part.PartitionNumber;offset=$part.Offset;size=$part.Size;
   volume=$volume.UniqueId;fstype=[string]$volume.FileSystemType;letter=[string]$volume.DriveLetter}
 })
 [pscustomobject]@{number=$disk.Number;path=$disk.Path;serial=$disk.SerialNumber;
  location=$disk.Location;size=$disk.Size;bus=[string]$disk.BusType;
  model=[string]$disk.FriendlyName;readonly=$disk.IsReadOnly;system=($disk.IsBoot -or $disk.IsSystem -or -not $known);parts=$parts}
})
ConvertTo-Json -InputObject $items -Depth 6 -Compress
"""
    value = json.loads(powershell(script))
    if not isinstance(value, list):
        raise ValueError("Windows did not provide a valid disk inventory")
    volumes = set()
    for original in protected_paths:
        path = Path(original)
        while not path.exists() and path != path.parent:
            path = path.parent
        volumes.add(windows_volume(path).lower())
    result = []
    for disk in value:
        number = disk.get("number")
        if type(number) is not int or not 0 <= number <= 4096:
            continue
        bus = str(disk.get("bus", ""))
        virtual = bus.lower() in {"virtual", "file backed virtual", "filebackedvirtual", "spaces"}
        protected = (
            disk.get("system")
            or bus.lower() not in {"usb", "sd", "mmc"}
            or any(str(part.get("volume", "")).lower() in volumes for part in disk.get("parts", []))
        )
        stable = {key: disk.get(key) for key in ("path", "serial", "location", "size", "bus")}
        identity = fingerprint(stable) if stable["path"] and (stable["serial"] or stable["location"]) else ""
        result.append(
            Device(
                r"\\.\PhysicalDrive" + str(number),
                identity,
                int(disk.get("size") or 0),
                str(disk.get("model") or disk.get("serial") or bus + " disk").strip(),
                bus,
                bool(protected),
                bool(disk.get("readonly")),
                virtual,
                tuple(disk.get("parts", [])),
            )
        )
    return result


def inventory(protected_paths=()):
    protected_paths = [Path("/"), Path.home(), Path(__file__).resolve(), *protected_paths]
    return windows_inventory(protected_paths) if os.name == "nt" else linux_inventory(protected_paths)


def select(path: str, identity: str, protected_paths=()):
    matches = [device for device in inventory(protected_paths) if device.path == path and device.identity == identity]
    if len(matches) != 1 or not matches[0].eligible:
        raise ValueError("The selected card changed, is protected, or cannot be identified safely; select it again")
    return matches[0]
