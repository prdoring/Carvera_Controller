"""Freeze the independent kiosk desktop tools and their Slate presentation."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
IMAGER_VERSION = "2.0.12"
IMAGER_COMMIT = "84b03d96cd4c390ebe475a4b5db5735e5535e9a6"


def stage_theme(destination: Path, fallback: Path | None = None) -> None:
    source = ROOT / "carveracontroller"
    (destination / "ui").mkdir(parents=True)
    shutil.copyfile(source / "ui/theme.py", destination / "ui/theme.py")
    shutil.copytree(source / "data/fonts", destination / "data/fonts")
    shutil.copytree(source / "data/theme", destination / "data/theme")
    if fallback is not None:
        from scripts.kiosk_desktop_assets import FILES

        for name in ("NotoSansCJKsc-Regular.otf", "LICENSE"):
            if not (fallback / name).is_file():
                raise ValueError("A licensed Noto fallback font and its LICENSE are required")
            if hashlib.sha256((fallback / name).read_bytes()).hexdigest() != FILES[name][1]:
                raise ValueError("The fallback font or license differs from its pinned source")
        shutil.copyfile(fallback / "NotoSansCJKsc-Regular.otf", destination / "data/fonts/NotoSansCJKsc-Regular.otf")
        shutil.copyfile(fallback / "LICENSE", destination / "data/fonts/Noto-OFL.txt")


def notices(destination):
    destination.mkdir()
    shutil.copyfile(ROOT / "LICENSE", destination / "PROJECT-LICENSE.txt")
    python_license = next(
        (
            path
            for path in (Path(sys.base_prefix) / "LICENSE.txt", Path(sysconfig.get_path("stdlib")) / "LICENSE.txt")
            if path.is_file()
        ),
        None,
    )
    if python_license is None:
        raise ValueError("The Python runtime redistribution license is missing")
    shutil.copyfile(python_license, destination / "PYTHON-LICENSE.txt")
    packages = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "unknown")
        packages.append(name + " " + distribution.version)
        for entry in distribution.files or ():
            if any(part.lower().startswith(("license", "copying", "notice")) for part in Path(entry).parts):
                source = Path(distribution.locate_file(entry))
                if source.is_file() and source.stat().st_size <= 1024**2:
                    target = name + "-" + Path(entry).as_posix().replace("/", "_")
                    shutil.copyfile(source, destination / target[-200:])
    (destination / "PACKAGES.txt").write_text("\n".join(sorted(packages)) + "\n", encoding="utf-8")


def build(
    output: Path, *, design_slice=False, fallback=None, imager=None, novnc=None, kind="setup", version=None, commit=None
):
    output = output.resolve()
    fallback = fallback.resolve() if fallback is not None else None
    imager = imager.resolve() if imager is not None else None
    novnc = novnc.resolve() if novnc is not None else None
    if sys.platform not in {"win32", "linux"}:
        raise ValueError("Desktop packages currently support Windows and Linux only")
    if not design_slice and (fallback is None or (kind == "setup" and imager is None) or novnc is None):
        raise ValueError("Release builds require the pinned writer and licensed fallback font")
    if not design_slice and (sys.version_info[:2] != (3, 12) or not version or not commit):
        raise ValueError("Release desktop builds require Python 3.12 and explicit version/source identities")
    if kind not in {"setup", "viewer"}:
        raise ValueError("Unknown desktop application")
    if not design_slice and (
        not re.fullmatch("[a-f0-9]{40}", commit) or not re.fullmatch(r"\d+\.\d+\.\d+(?:\.dev\d+|rc\d+)?", version)
    ):
        raise ValueError("Use canonical release identities")
    machine = platform.machine().lower()
    target_platform = (
        "windows-x64"
        if os.name == "nt" and machine in {"amd64", "x86_64"}
        else ("linux-arm64" if machine in {"aarch64", "arm64"} else "linux-x64")
    )
    dirty = True
    if not design_slice:
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        if actual != commit:
            raise ValueError("The desktop build source does not match the requested commit")
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
    name = "CarveraKioskSetup" if kind == "setup" else "CarveraKioskScreenShare"
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kiosk-freeze-", dir=output) as temporary:
        stage = Path(temporary)
        stage_theme(stage / "slate", fallback)
        notices(stage / "notices")
        metadata = {
            "format": 1,
            "kind": kind,
            "version": version,
            "commit": commit,
            "dirty": dirty,
            "platform": target_platform,
            "python": sys.version.split()[0],
            "image_format": "carvera-kiosk-pi4-v3",
            "setup_protocol": 1,
            "screen_lease_protocol": 1,
            "writer_version": IMAGER_VERSION if kind == "setup" else None,
            "writer_commit": IMAGER_COMMIT if kind == "setup" else None,
        }
        (stage / "desktop-build.json").write_text(json.dumps(metadata), encoding="utf-8")
        args = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--noupx",
            "--windowed",
            "--name",
            name,
            "--paths",
            str(ROOT),
            "--distpath",
            str(output),
            "--workpath",
            str(stage / "work"),
            "--specpath",
            str(stage),
            "--add-data",
            f"{stage / 'slate'}{os.pathsep}slate",
            "--add-data",
            f"{stage / 'notices'}{os.pathsep}notices",
            "--add-data",
            f"{stage / 'desktop-build.json'}{os.pathsep}.",
            "--hidden-import",
            "PIL._tkinter_finder",
            "--hidden-import",
            "asyncssh",
            "--hidden-import",
            "bcrypt",
            "--exclude-module",
            "numpy",
            "--exclude-module",
            "kivy",
            "--exclude-module",
            "carveracontroller",
        ]
        for runtime_name in ("admin_accounts.py", "setup_protocol.py", "settings.py"):
            args.extend(["--add-data", f"{ROOT / 'assets/packaging/kiosk/runtime' / runtime_name}{os.pathsep}runtime"])
        if design_slice:
            args.extend(["--hidden-import", "PIL.ImageGrab"])
        if os.name == "nt":
            args.extend(["--manifest", str(ROOT / "assets/packaging/kiosk/desktop.manifest")])
        if imager is not None and kind == "setup":
            if not (imager / "writer-manifest.json").is_file():
                raise ValueError("Select the complete pinned writer directory")
            archive_path = stage / "writer.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(imager.rglob("*")):
                    if path.is_symlink():
                        raise ValueError("The pinned writer must contain regular files, without links")
                    if path.is_file():
                        archive.write(path, path.relative_to(imager).as_posix())
            args.extend(["--add-data", f"{archive_path}{os.pathsep}."])
        if novnc is not None:
            from scripts.kiosk_novnc import COMMIT as novnc_commit
            from scripts.kiosk_novnc import fetch

            fetch(novnc)
            for relative in ("vnc.html", "core/rfb.js", "app/ui.js"):
                if not (novnc / relative).is_file():
                    raise ValueError("The noVNC distribution is incomplete")
            shutil.copytree(
                novnc,
                stage / "novnc",
                ignore=shutil.ignore_patterns(
                    ".git", ".github", "node_modules", "__pycache__", "tests", "docs", "utils"
                ),
            )
            metadata["novnc_commit"] = novnc_commit
            (stage / "desktop-build.json").write_text(json.dumps(metadata), encoding="utf-8")
            args.extend(["--add-data", f"{stage / 'novnc'}{os.pathsep}novnc"])
        subprocess.run([*args, str(ROOT / "kioskdesktop/__main__.py")], cwd=ROOT, check=True)
    return output / name


def inventory(target):
    checksums, links = {}, {}
    for path in sorted(target.rglob("*")):
        if path == target / "files.json":
            continue
        if path.is_symlink():
            if (
                not path.is_file()
                or not path.resolve().is_relative_to(target.resolve())
                or path.readlink().is_absolute()
            ):
                raise ValueError("A frozen runtime link escapes the packaged files")
            links[path.relative_to(target).as_posix()] = path.readlink().as_posix()
        if path.is_file():
            checksums[path.relative_to(target).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (target / "files.json").write_text(
        json.dumps({"format": 1, "sha256": checksums, "links": links}, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/kiosk/desktop")
    parser.add_argument("--design-slice", action="store_true")
    parser.add_argument("--fallback", type=Path)
    parser.add_argument("--imager", type=Path)
    parser.add_argument("--novnc", type=Path)
    parser.add_argument("--kind", choices=("setup", "viewer"), default="setup")
    parser.add_argument("--version")
    parser.add_argument("--commit")
    args = parser.parse_args()
    target = build(
        args.output,
        design_slice=args.design_slice,
        fallback=args.fallback,
        imager=args.imager,
        novnc=args.novnc,
        kind=args.kind,
        version=args.version,
        commit=args.commit,
    )
    inventory(target)


if __name__ == "__main__":
    main()
