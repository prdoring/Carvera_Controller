"""Package native frozen kiosk tools as user installers and portable downloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify(folder, kind, version, commit):
    name = "CarveraKioskSetup" if kind == "setup" else "CarveraKioskScreenShare"
    manifest = json.loads((folder / "files.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1:
        raise ValueError("Unsupported frozen file inventory")
    files, links = manifest["sha256"], manifest["links"]
    actual = {
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.is_file() and path != folder / "files.json"
    }
    if actual != set(files):
        raise ValueError("The frozen distribution changed after building")
    for relative, expected in files.items():
        path = folder / relative
        if not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("A desktop payload escapes its package")
        if path.is_symlink() and (path.readlink().is_absolute() or links.get(relative) != path.readlink().as_posix()):
            raise ValueError("Unexpected desktop runtime link")
        if (relative in links) != path.is_symlink():
            raise ValueError("A declared runtime link changed type")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise ValueError("A frozen payload checksum changed")
    metadata = json.loads((folder / "_internal/desktop-build.json").read_text(encoding="utf-8"))
    if (metadata.get("kind"), metadata.get("version"), metadata.get("commit")) != (
        kind,
        version,
        commit,
    ) or not metadata.get("python", "").startswith("3.12."):
        raise ValueError("Desktop embedded identities do not match the release")
    from kioskdesktop.native_version import architecture

    binary = folder / (name + (".exe" if os.name == "nt" else ""))
    if architecture(binary) != metadata.get("platform"):
        raise ValueError("The executable architecture does not match its embedded identity")
    return name


def nsis_text(value):
    return str(value).replace("$", "$$").replace('"', '$\\"').replace("\r", "").replace("\n", "")


def windows_installer(folder, output, stem, name, version):
    target = output / (stem + ".exe")
    title = "Carvera Kiosk Setup" if name.endswith("Setup") else "Carvera Kiosk Screen Share"
    files = sorted(path for path in folder.rglob("*") if path.is_file())
    parents = {parent.as_posix() for path in files for parent in path.relative_to(folder).parents}
    directories = sorted(parents, key=lambda value: (value.count("/"), value))
    uninstall_command = "'\"$INSTDIR\\Uninstall.exe\"'"
    lines = [
        "Unicode true",
        "RequestExecutionLevel user",
        'Name "' + title + '"',
        'OutFile "' + nsis_text(target.resolve()) + '"',
        'InstallDir "$LOCALAPPDATA\\Programs\\' + name + '"',
        "ShowInstDetails show",
        "ShowUninstDetails show",
    ]
    lines += [
        "Function .onInit",
        '  StrCpy $INSTDIR "$LOCALAPPDATA\\Programs\\' + name + '"',
        "FunctionEnd",
        'Section "Install"',
    ]
    for directory in directories:
        suffix = "" if directory == "." else "\\" + directory.replace("/", "\\")
        lines.append('  SetOutPath "$INSTDIR' + suffix + '"')
        for path in files:
            if path.parent.relative_to(folder).as_posix() == directory:
                lines.append('  File "' + nsis_text(path.resolve()) + '"')
    lines += [
        '  WriteUninstaller "$INSTDIR\\Uninstall.exe"',
        '  CreateShortcut "$SMPROGRAMS\\' + title + '.lnk" "$INSTDIR\\' + name + '.exe"',
        '  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'
        + name
        + '" "DisplayName" "'
        + title
        + '"',
        '  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'
        + name
        + '" "DisplayVersion" "'
        + version
        + '"',
        '  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'
        + name
        + '" "UninstallString" '
        + uninstall_command,
        "SectionEnd",
        'Section "Uninstall"',
        '  StrCmp $INSTDIR "$LOCALAPPDATA\\Programs\\' + name + '" +2',
        "  Abort",
    ]
    for path in files:
        lines.append('  Delete "$INSTDIR\\' + nsis_text(path.relative_to(folder)).replace("/", "\\") + '"')
    lines += ['  Delete "$INSTDIR\\Uninstall.exe"']
    for directory in reversed(directories):
        if directory != ".":
            lines.append('  RMDir "$INSTDIR\\' + directory.replace("/", "\\") + '"')
    lines += [
        '  RMDir "$INSTDIR"',
        '  Delete "$SMPROGRAMS\\' + title + '.lnk"',
        '  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + name + '"',
        "SectionEnd",
    ]
    with tempfile.TemporaryDirectory(prefix="kiosk-installer-", dir=output) as temporary:
        script = Path(temporary) / "installer.nsi"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        compiler = (
            os.environ.get("CARVERA_NSIS_COMPILER")
            or shutil.which("makensis")
            or str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "NSIS/makensis.exe")
        )
        subprocess.run([compiler, "/V2", str(script)], check=True)
    return target


def debian_package(folder, output, stem, name, version, kind, architecture):
    package = "carvera-kiosk-" + ("setup" if kind == "setup" else "screen-share")
    title = "Carvera Kiosk Setup" if kind == "setup" else "Carvera Kiosk Screen Share"
    with tempfile.TemporaryDirectory(prefix="kiosk-deb-", dir=output) as temporary:
        root = Path(temporary)
        destination = root / "usr/lib" / package
        shutil.copytree(folder, destination, symlinks=True)
        executable = destination / name
        executable.chmod(0o755)
        wrapper = root / "usr/bin" / package
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(f'#!/bin/sh\nexec /usr/lib/{package}/{name} "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        desktop = root / "usr/share/applications" / (package + ".desktop")
        desktop.parent.mkdir(parents=True)
        desktop.write_text(
            f"[Desktop Entry]\nType=Application\nName={title}\nExec={package}\nTerminal=false\nCategories=Utility;\n",
            encoding="utf-8",
        )
        control = root / "DEBIAN/control"
        control.parent.mkdir()
        dependencies = "libc6 (>= 2.36), libfontconfig1, libx11-6, libxft2, libxrender1, libxext6, ca-certificates"
        if kind == "setup":
            dependencies += ", pkexec, util-linux, udev"
        debian_version = version.replace(".dev", "~dev").replace("rc", "~rc")
        control.write_text(
            f"Package: {package}\nVersion: {debian_version}\nArchitecture: {architecture}\n"
            "Maintainer: Carvera Kiosk contributors\nSection: utils\nPriority: optional\n"
            f"Depends: {dependencies}\nRecommends: xwayland\nDescription: {title}\n"
            " Independent Slate Workshop desktop tools for Raspberry Pi kiosks.\n",
            encoding="utf-8",
        )
        target = output / (stem + ".deb")
        subprocess.run(
            ["dpkg-deb", "--threads-max=2", "--root-owner-group", "--build", str(root), str(target)], check=True
        )
    return target


def package(folder, output, *, kind, version, commit):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.dev\d+|rc\d+)?", version) or not re.fullmatch("[a-f0-9]{40}", commit):
        raise ValueError("Explicit release identities are required")
    folder, output = folder.resolve(), output.resolve()
    name = verify(folder, kind, version, commit)
    output.mkdir(parents=True, exist_ok=True)
    target = "windows-x64" if os.name == "nt" else "linux-arm64" if platform.machine() == "aarch64" else "linux-x64"
    stem = f"carvera-kiosk-{kind}-{version}-{target}"
    if os.name == "nt":
        portable = output / (stem + ".zip")
        with zipfile.ZipFile(portable, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(name) / path.relative_to(folder))
        installed = windows_installer(folder, output, stem, name, version)
    else:
        portable = output / (stem + ".tar.gz")
        with tarfile.open(portable, "w:gz") as archive:
            archive.add(folder, arcname=name)
        installed = debian_package(
            folder, output, stem, name, version, kind, "arm64" if target.endswith("arm64") else "amd64"
        )
    return installed, portable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=("setup", "viewer"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    package(args.folder, args.output, kind=args.kind, version=args.version, commit=args.commit)
