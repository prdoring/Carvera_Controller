"""Import application preferences without importing executables or G-code."""

import configparser
import io
import json
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath


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
    with tarfile.open(archive, "r:*") as source:
        for member in source:
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


def restore_settings(source, destination):
    """Restore our own settings snapshot without translating preference values."""
    destination = Path(destination)
    pending = {}
    archive = tarfile.open(fileobj=source, mode="r:*") if hasattr(source, "read") else tarfile.open(source, "r:*")
    with archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if member.isdir():
                continue
            if (not member.isfile() or path.is_absolute() or ".." in path.parts
                    or path.suffix not in (".ini", ".json") or member.size > 1024 * 1024
                    or path.parts[0] not in (".kivy", ".carveracontroller", "makera.ini", "settings-import.json")):
                raise ValueError("Invalid settings snapshot")
            if path in pending:
                raise ValueError("Duplicate settings snapshot member")
            pending[path] = archive.extractfile(member).read()
            if sum(map(len, pending.values())) > 16 * 1024 * 1024:
                raise ValueError("Settings snapshot exceeds 16 MiB")
    for path in pending:
        target = destination / path
        if not target.resolve().is_relative_to(destination.resolve()) or target.is_symlink():
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
    if len(sys.argv) != 3 or sys.argv[1] not in ("restore", "backup"):
        sys.exit("Use: settings.py restore|backup DATA_DIRECTORY")
    if sys.argv[1] == "restore":
        restore_settings(sys.stdin.buffer, Path(sys.argv[2]))
    else:
        export_settings(Path(sys.argv[2]), sys.stdout.buffer)
