"""Installed distributions retain version ordering and remove only their own files."""

from pathlib import Path
from xml.etree import ElementTree

from scripts import package_kiosk_desktop as packaging


def test_windows_gui_keeps_user_privileges_and_per_monitor_scaling():
    source = Path(__file__).resolve().parents[2] / "assets/packaging/kiosk/desktop.manifest"
    manifest = ElementTree.parse(source)
    privileges = manifest.find(".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel")
    assert privileges is not None
    assert privileges.attrib == {"level": "asInvoker", "uiAccess": "false"}
    awareness = manifest.find(".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}dpiAwareness")
    assert awareness is not None and awareness.text == "PerMonitorV2"


def test_uninstaller_includes_intermediate_directories_without_recursive_deletion(tmp_path, monkeypatch):
    folder, output = tmp_path / "frozen", tmp_path / "packages"
    payload = folder / "_internal/slate/data/fonts/font.ttf"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"fixture")
    output.mkdir()
    scripts = []
    monkeypatch.setenv("CARVERA_NSIS_COMPILER", "isolated-compiler")
    monkeypatch.setattr(
        packaging.subprocess,
        "run",
        lambda arguments, **_kwargs: scripts.append(Path(arguments[-1]).read_text(encoding="utf-8-sig")),
    )
    packaging.windows_installer(folder, output, "fixture", "CarveraKioskSetup", "1.1.0.dev5")
    script = scripts[0]
    assert "RequestExecutionLevel user" in script
    assert 'RMDir "$INSTDIR\\_internal\\slate\\data"' in script
    assert 'RMDir "$INSTDIR\\_internal\\slate"' in script
    assert "RMDir /r" not in script
    assert "Exec " not in script


def test_debian_prereleases_sort_before_stable_and_keep_canonical_embedded_version(tmp_path, monkeypatch):
    folder, output = tmp_path / "frozen", tmp_path / "packages"
    folder.mkdir()
    output.mkdir()
    (folder / "CarveraKioskSetup").write_bytes(b"fixture")
    controls = []

    def run(arguments, **_kwargs):
        controls.append((Path(arguments[-2]) / "DEBIAN/control").read_text())

    monkeypatch.setattr(packaging.subprocess, "run", run)
    for version in ("1.1.0.dev5", "1.1.0rc1", "1.1.0"):
        packaging.debian_package(folder, output, "fixture", "CarveraKioskSetup", version, "setup", "amd64")
    assert [next(line for line in text.splitlines() if line.startswith("Version:")) for text in controls] == [
        "Version: 1.1.0~dev5",
        "Version: 1.1.0~rc1",
        "Version: 1.1.0",
    ]
