"""Installed distributions retain version ordering and remove only their own files."""

from pathlib import Path

from scripts import package_kiosk_desktop as packaging


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
