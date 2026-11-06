"""Build and exercise native desktop packages without opening a physical card."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import select
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_kiosk_desktop import build, inventory
from scripts.package_kiosk_desktop import package


@contextlib.contextmanager
def display_environment():
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("PYTHON") and key != "VIRTUAL_ENV"
    }
    if os.name == "nt":
        from kioskdesktop.devices import windows_system_directory

        environment["PATH"] = str(windows_system_directory())
        yield environment
        return
    read, write = os.pipe()
    process = subprocess.Popen(
        ["Xvfb", "-displayfd", str(write), "-screen", "0", "1920x1200x24", "-nolisten", "tcp"], pass_fds=(write,)
    )
    os.close(write)
    try:
        if not select.select([read], [], [], 15)[0]:
            raise RuntimeError("The owned display did not start")
        number = os.read(read, 32).decode().strip()
        if not number.isdecimal():
            raise ValueError("The owned display returned an invalid identity")
        environment.update(DISPLAY=":" + number, PATH="/usr/bin:/bin")
        yield environment
    finally:
        os.close(read)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def run_owned(arguments, *, environment, timeout=60):
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [str(value) for value in arguments],
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        if process.returncode:
            raise RuntimeError("The packaged check failed: " + stderr[:2000].decode(errors="replace"))
        return stdout
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def runtime_check(executable, report, environment):
    run_owned([executable, "--self-check", report], environment=environment)
    value = json.loads(report.read_text())
    if value.get("ok") is not True:
        raise ValueError("Packaged runtime validation did not pass")
    return value


def installed_windows(installer, name, reports, environment):
    destination = Path(os.environ["LOCALAPPDATA"]) / "Programs" / name
    if destination.exists():
        raise ValueError("An existing desktop installation was left alone; use a clean test account")
    try:
        run_owned([installer, "/S"], environment=environment, timeout=120)
        runtime_check(destination / (name + ".exe"), reports / (name + "-installed.json"), environment)
    finally:
        uninstaller = destination / "Uninstall.exe"
        if uninstaller.is_file():
            run_owned([uninstaller, "/S", "_?=" + str(destination)], environment=environment, timeout=60)
            # NSIS cannot remove its running executable when _?= avoids its detached copy.
            uninstaller.unlink(missing_ok=True)
            try:
                destination.rmdir()
            except OSError:
                raise RuntimeError("The owned test installation did not clean up") from None


def check(output, writer, version, commit, skip_installed=False):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new output folder; existing packages and validation reports are preserved")
    output.mkdir(parents=True, exist_ok=True)
    reports, packages = output / "reports", output / "packages"
    reports.mkdir(exist_ok=True)
    packages.mkdir(exist_ok=True)
    fallback, novnc = ROOT / "dist/kiosk/desktop-assets/noto", ROOT / "dist/kiosk/novnc-desktop"
    with display_environment() as environment:
        for kind in ("setup", "viewer"):
            print("Building and checking " + kind, flush=True)
            folder = build(
                output / "frozen",
                fallback=fallback,
                imager=writer,
                novnc=novnc,
                kind=kind,
                version=version,
                commit=commit,
            )
            inventory(folder)
            name = folder.name
            executable = folder / (name + (".exe" if os.name == "nt" else ""))
            runtime_check(executable, reports / (kind + "-runtime.json"), environment)
            for page in ("setup", "erase") if kind == "setup" else ("viewer",):
                run_owned(
                    [executable, "--design-slice", page, "--capture", reports / (page + ".png")],
                    environment=environment,
                )
            tests = sorted(ROOT.glob("tests/unit/test_kiosk_desktop*.py"))
            test_environment = dict(os.environ, CARVERA_DESKTOP_EXE=str(executable))
            test_environment.update(
                TCL_LIBRARY=str(folder / "_internal/_tcl_data"), TK_LIBRARY=str(folder / "_internal/_tk_data")
            )
            if "DISPLAY" in environment:
                test_environment["DISPLAY"] = environment["DISPLAY"]
            subprocess.run(
                [sys.executable, "-m", "pytest", *map(str, tests), "-q", "-p", "no:cacheprovider"],
                env=test_environment,
                check=True,
            )
            installed, portable = package(folder, packages, kind=kind, version=version, commit=commit)
            with tempfile.TemporaryDirectory(prefix="kiosk portable 工作室 ", dir=output) as temporary:
                stage = Path(temporary)
                if os.name == "nt":
                    import zipfile

                    with zipfile.ZipFile(portable) as archive:
                        archive.extractall(stage)
                else:
                    import tarfile

                    with tarfile.open(portable, "r:gz") as archive:
                        archive.extractall(stage, filter="data")
                runtime_check(stage / name / executable.name, reports / (kind + "-portable.json"), environment)
            if os.name == "nt" and not skip_installed:
                installed_windows(installed, name, reports, environment)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--writer", type=Path, required=True)
    parser.add_argument(
        "--skip-installed", action="store_true", help="Development only; release jobs must test installers"
    )
    args = parser.parse_args()
    check(
        args.output.resolve(),
        args.writer.resolve(),
        os.environ["RELEASE_VERSION"],
        os.environ["RELEASE_COMMIT"],
        args.skip_installed,
    )
