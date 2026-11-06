"""Import application preferences without importing executables or G-code."""

import configparser
import bz2
import gzip
import io
import json
import lzma
import os
import sys
import tarfile
import zlib
from pathlib import Path, PurePosixPath

MAX_ARCHIVE = 32 * 1024 * 1024


def bounded_archive(source):
    """Bound all tar bytes, including skipped members and extended headers."""
    if hasattr(source, "read"):
        data = source.read(MAX_ARCHIVE + 1)
    else:
        with open(source, "rb") as incoming:
            data = incoming.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Settings archive exceeds 32 MiB")
    decoder = None
    if data.startswith(b"\x1f\x8b"):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif data.startswith(b"BZh"):
        decoder = bz2.BZ2Decompressor()
    elif data.startswith(b"\xfd7zXZ\0"):
        decoder = lzma.LZMADecompressor(memlimit=64 * 1024 * 1024)
    if decoder is not None:
        expanded = decoder.decompress(data, MAX_ARCHIVE + 1)
        if len(expanded) > MAX_ARCHIVE or not decoder.eof or decoder.unused_data:
            raise ValueError("Settings compression is truncated, concatenated or exceeds 32 MiB")
        data = expanded
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:")


def prepare_archive(source):
    """Normalize supported exports into deterministic, bounded setup preferences."""
    pending = {}
    incoming = bounded_archive(source)
    with incoming as archive:
        for index, member in enumerate(archive):
            if index >= 4096:
                raise ValueError("Too many entries in the settings archive")
            if member.name in {"system-bundle.json", "updater-bundle.json"}:
                raise ValueError("A system bundle is not a preferences backup")
            path = PurePosixPath(member.name)
            if (not member.isfile() or member.size > 1024 * 1024 or member.size < 0
                    or path.is_absolute() or ".." in path.parts or "\\" in member.name
                    or path.suffix not in (".ini", ".json")
                    or not (path.name == "makera.ini" or {".kivy", ".carveracontroller"}.intersection(path.parts))):
                continue
            name = "makera.ini" if path.name == "makera.ini" else (
                (".kivy/" if ".kivy" in path.parts else ".carveracontroller/") + path.name)
            if name in pending:
                raise ValueError("Duplicate preference files in settings archive")
            content = archive.extractfile(member).read()
            if path.suffix == ".json":
                if not isinstance(json.loads(content), dict):
                    raise ValueError("Expected a settings object")
            else:
                configparser.ConfigParser(interpolation=None).read_string(content.decode("utf-8"))
            pending[name] = content
            if sum(map(len, pending.values())) > 16 * 1024 * 1024:
                raise ValueError("Settings exceed 16 MiB")
    if not pending:
        raise ValueError("No supported preferences found in settings archive")
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, content in sorted(pending.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mode = len(content), 0o600
                archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def export_settings(directory, destination):
    directory = Path(directory)
    archive = tarfile.open(fileobj=destination, mode="w|gz") if hasattr(destination, "write") else tarfile.open(destination, "w:gz")
    with archive:
        for name in (".kivy", ".carveracontroller", "makera.ini", "settings-import.json"):
            path = directory / name
            if path.exists():
                archive.add(path, arcname=name, filter=lambda member: member if (
                    member.isfile() and Path(member.name).suffix in (".ini", ".json")
                ) or member.isdir() else None)


def import_settings(archive, destination):
    destination = Path(destination)
    report = {"imported": [], "skipped": [], "translated": []}
    pending = {}
    with bounded_archive(archive) as source:
        for index, member in enumerate(source):
            if index >= 4096:
                raise ValueError("Too many entries in the settings archive")
            if member.name in {"system-bundle.json", "updater-bundle.json"}:
                raise ValueError("A system bundle is not a preferences backup")
            path = PurePosixPath(member.name)
            if not member.isfile() or member.size > 1024 * 1024 or ".." in path.parts or path.is_absolute():
                report["skipped"].append(member.name)
                continue
            if path.suffix not in (".ini", ".json") or not (path.name == "makera.ini" or any(
                part in (".kivy", ".carveracontroller") for part in path.parts
            )):
                report["skipped"].append(member.name)
                continue
            content = source.extractfile(member).read()
            target = Path("makera.ini") if path.name == "makera.ini" else (
                Path(".kivy" if ".kivy" in path.parts else ".carveracontroller") / path.name
            )
            if target in pending:
                raise ValueError(f"Duplicate settings destination: {target}")
            if path.suffix == ".json":
                if not isinstance(json.loads(content), dict):
                    raise ValueError(f"Expected a settings object: {member.name}")
            else:
                config = configparser.ConfigParser(interpolation=None)
                config.read_string(content.decode("utf-8"))
                if config.has_section("carvera"):
                    for key, value in list(config.items("carvera")):
                        if value.startswith(("/data/", "/storage/", "/sdcard/")):
                            config.set("carvera", key, str(destination / "gcodes") if "folder" in key else "")
                            report["translated"].append(key)
                    config.set("carvera", "allow_manual_usb_device", "0")
                    config.set("carvera", "manual_usb_device", "")
                for section in ("input", "graphics"):
                    config.remove_section(section)
                output = io.StringIO()
                config.write(output)
                content = output.getvalue().encode("utf-8")
            pending[target] = content
            if sum(len(value) for value in pending.values()) > 16 * 1024 * 1024:
                raise ValueError("Settings archive exceeds 16 MiB")
    if not pending:
        raise ValueError("No supported settings were found in the archive")
    for target, content in pending.items():
        target = destination / target
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or target.parent.is_symlink():
            raise ValueError("Settings destinations must not be symbolic links")
        target.write_bytes(content)
        report["imported"].append(str(target.relative_to(destination)))
    (destination / "settings-import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def validated_snapshot(source):
    """Read and validate an exact preferences snapshot before changing files."""
    pending = {}
    archive = bounded_archive(source)
    with archive:
        for index, member in enumerate(archive):
            if index >= 4096:
                raise ValueError("Settings snapshot contains too many entries")
            path = PurePosixPath(member.name)
            if member.isdir():
                continue
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or path.suffix not in (".ini", ".json") or member.size > 1024 * 1024
                    or path.parts[0] not in (".kivy", ".carveracontroller", "makera.ini", "settings-import.json")):
                raise ValueError("Invalid settings snapshot")
            if path.parts[0] in ("makera.ini", "settings-import.json") and len(path.parts) != 1:
                raise ValueError("Invalid settings snapshot path")
            if path in pending:
                raise ValueError("Duplicate settings snapshot member")
            pending[path] = archive.extractfile(member).read()
            if sum(map(len, pending.values())) > 16 * 1024 * 1024:
                raise ValueError("Settings snapshot exceeds 16 MiB")
            if path.suffix == ".json":
                if not isinstance(json.loads(pending[path]), dict):
                    raise ValueError("Settings JSON must contain an object")
            else:
                config = configparser.ConfigParser(interpolation=None)
                config.read_string(pending[path].decode("utf-8"))
    if not pending:
        raise ValueError("No preferences were found in the snapshot")
    return pending


def restore_settings(source, destination):
    """Restore our own settings snapshot without translating preference values."""
    destination = Path(destination)
    pending = validated_snapshot(source)
    for path in pending:
        target = destination / path
        if (not target.resolve().is_relative_to(destination.resolve()) or target.is_symlink()
                or any(parent.is_symlink() for parent in target.parents if parent != destination.parent)):
            raise ValueError("Settings destinations must stay inside application data")
    retained = {str(path) for path in pending}
    for directory in (destination / ".kivy", destination / ".carveracontroller"):
        if directory.is_symlink():
            raise ValueError("Settings directories must not be symbolic links")
        for target in directory.rglob("*") if directory.exists() else ():
            if (target.is_file() and target.suffix in (".ini", ".json")
                    and target.relative_to(destination).as_posix() not in retained):
                target.unlink()
    for path, content in pending.items():
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("restore", "backup", "validate"):
        sys.exit("Use: settings.py restore|backup|validate DATA_DIRECTORY")
    if sys.argv[1] == "restore":
        restore_settings(sys.stdin.buffer, Path(sys.argv[2]))
    elif sys.argv[1] == "validate":
        validated_snapshot(sys.stdin.buffer)
    else:
        export_settings(Path(sys.argv[2]), sys.stdout.buffer)
