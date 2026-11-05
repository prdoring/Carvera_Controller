"""Build independent system and updater artifacts from the pinned image inputs."""

import hashlib
import json
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path


def archive_files(output, name, stage, manifest_name, manifest):
    files = sorted(path for path in stage.rglob("*") if path.is_file())
    manifest["sha256"] = {
        path.relative_to(stage).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files
    }
    (stage / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(stage / manifest_name, output / manifest_name)
    target = output / name
    with tarfile.open(target, "w:gz") as bundle:
        for path in [stage / manifest_name, *files]:
            info = bundle.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = 0o755 if path.suffix == ".sh" else 0o644
            with path.open("rb") as source:
                bundle.addfile(info, source)
    (output / (name + ".sha256")).write_text(hashlib.sha256(target.read_bytes()).hexdigest() + "  " + name + "\n")
    return target


def presentation(root, destination):
    package = destination / "carveracontroller"
    (package / "ui").mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "ui/__init__.py").touch()
    for name in ("translation.py", "ARIALUNI.ttf", "ui/theme.py", "ui/controls.kv"):
        shutil.copyfile(root / "carveracontroller" / name, package / name)
    for name in ("data/fonts", "data/theme", "locales"):
        shutil.copytree(
            root / "carveracontroller" / name,
            package / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pot", "*~"),
        )


def build(version, commit, output, root=None):
    root = Path(root or Path(__file__).resolve().parents[3])
    assets = root / "assets/packaging/kiosk"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # The same module is shipped in the privileged bundle and migration tools.
    sys.path.insert(0, str(assets / "runtime"))
    sys.path.insert(0, str(root / "carveracontroller"))
    import system_update

    system_update.version_name(version)
    with tempfile.TemporaryDirectory(prefix="kiosk-system-build-") as temporary:
        stage = Path(temporary)
        (stage / "runtime").mkdir()
        for name in sorted(system_update.RUNTIME_NAMES):
            source = assets / "runtime" / name
            if name in {"kiosk_state.py", "runtime_profile.py", "kiosk_touch.py"}:
                source = root / "carveracontroller" / name
            shutil.copyfile(source, stage / "runtime" / name)
        presentation(root, stage / "system-ui")
        (stage / "units").mkdir()
        for name in sorted(system_update.UNIT_NAMES):
            shutil.copyfile(assets / "overlay/etc/systemd/system" / name, stage / "units" / name)
        (stage / "config").mkdir()
        shutil.copyfile(assets / "overlay/etc/carvera/wayvnc.conf", stage / "config/wayvnc.conf")
        (stage / "wheels").mkdir()
        for wheel in (output / "wheels").glob("*.whl"):
            if not wheel.name.startswith("carvera_controller"):
                shutil.copyfile(wheel, stage / "wheels" / wheel.name)
        if not any(path.name.lower().startswith("kivy-") for path in (stage / "wheels").glob("*.whl")):
            raise ValueError("Build the pinned ARM64 recovery wheels before creating the system artifact")
        manifest = {
            "kind": "kiosk-system",
            "format": 1,
            "version": version,
            "commit": commit,
            "architecture": "aarch64",
            "python": "3.13",
            "os": "debian-13",
            "minimum_updater": 1,
            "maintenance_protocols": [1],
        }
        system = archive_files(output, f"carvera-kiosk-system-{version}.tar.gz", stage, "system-bundle.json", manifest)
        system_update.unpack(system)
    with tempfile.TemporaryDirectory(prefix="kiosk-updater-build-") as temporary:
        stage = Path(temporary)
        for name in ("system_update.py", "admin_accounts.py"):
            shutil.copyfile(assets / "runtime" / name, stage / name)
        shutil.copyfile(root / "carveracontroller/kiosk_state.py", stage / "kiosk_state.py")
        archive_files(
            output,
            f"carvera-kiosk-updater-{version}.tar.gz",
            stage,
            "updater-bundle.json",
            {"kind": "kiosk-updater", "format": 1, "version": version, "updater_version": 1, "commit": commit},
        )
    return system


if __name__ == "__main__":
    build(*sys.argv[1:])
