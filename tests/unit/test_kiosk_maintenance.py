"""Exercise the image's maintenance tools without system services or hardware."""

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ASSETS = Path(__file__).resolve().parents[2] / "assets/packaging/kiosk"


def load(name):
    spec = importlib.util.spec_from_file_location("kiosk_" + name, ASSETS / "runtime" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def archive(path, files, symlink=None):
    with tarfile.open(path, "w:gz") as output:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            output.addfile(info, io.BytesIO(content))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            output.addfile(info)
    return path


@pytest.fixture
def control(monkeypatch, tmp_path):
    pytest.importorskip("fcntl")
    monkeypatch.syspath_prepend(str(ASSETS.parents[2] / "carveracontroller"))
    monkeypatch.syspath_prepend(str(ASSETS / "runtime"))
    module = load("control")
    for name in ("BASE", "DATA", "RUN", "ADMIN"):
        directory = tmp_path / name.lower()
        directory.mkdir()
        monkeypatch.setattr(module, name, directory)
    monkeypatch.setattr(module, "STATUS", tmp_path / "status.json")
    monkeypatch.setattr(module, "export_snapshot", lambda output: load("settings").export_settings(module.DATA, output))
    return module


def test_import_only_preferences_and_translate_android_paths(tmp_path):
    source = archive(tmp_path / "settings.tar.gz", {
        "files/.kivy/config.ini": b"[carvera]\nlocal_folder=/storage/emulated/0/jobs\nandroid_ui_scale=1.15\n[input]\nraw=evil\n",
        "files/.kivy/probe.json": b'{"diameter": 3.175}',
        "files/.carveracontroller/gcodes/job.nc": b"G0 X50",
        "../escape.json": b"{}",
        "files/.kivy/code.py": b"raise Exception()",
    }, symlink="files/.kivy/linked.json")
    destination = tmp_path / "data"
    result = load("settings").import_settings(source, destination)
    config = (destination / ".kivy/config.ini").read_text()
    assert str(destination / "gcodes") in config
    assert "android_ui_scale = 1.15" in config
    assert "[input]" not in config
    assert (destination / ".kivy/probe.json").is_file()
    assert len(result["skipped"]) == 4
    assert not (tmp_path / "escape.json").exists()


def test_import_rejects_conflicting_flattened_destinations(tmp_path):
    source = archive(tmp_path / "settings.tar.gz", {"one/.kivy/probe.json": b"{}", "two/.kivy/probe.json": b"{}"})
    with pytest.raises(ValueError, match="Duplicate"):
        load("settings").import_settings(source, tmp_path / "data")
    assert not (tmp_path / "data").exists()


def test_restore_preserves_exact_preferences_and_removes_new_settings(tmp_path):
    data = tmp_path / "data"
    (data / ".kivy").mkdir(parents=True)
    (data / ".kivy/new.json").write_text("{}")
    (data / ".kivy/job.nc").write_text("G0 X0")
    original = b"[carvera]\nmanual_usb_device=/dev/serial/by-id/mill\n"
    source = archive(tmp_path / "snapshot.tar.gz", {".kivy/config.ini": original})
    load("settings").restore_settings(source, data)
    assert (data / ".kivy/config.ini").read_bytes() == original
    assert not (data / ".kivy/new.json").exists()
    assert (data / ".kivy/job.nc").is_file()


def test_restore_rejects_archive_links(tmp_path):
    source = archive(tmp_path / "snapshot.tar.gz", {}, symlink=".kivy/config.ini")
    with pytest.raises(ValueError, match="Invalid"):
        load("settings").restore_settings(source, tmp_path / "data")


def test_backup_stages_privately_on_destination_filesystem(control, monkeypatch):
    destination = control.ADMIN / "preferences.tar.gz"
    original_replace = control.os.replace

    def replace(source, target):
        assert source.parent.parent == destination.parent
        assert source.parent.stat().st_mode & 0o777 == 0o700
        assert source.stat().st_mode & 0o777 == 0o600
        original_replace(source, target)

    monkeypatch.setattr(control.os, "replace", replace)
    (control.DATA / "makera.ini").write_text("[user]\nvalue=before\n")
    assert control.backup(destination) == str(destination)
    with tarfile.open(destination) as source:
        assert source.extractfile("makera.ini").read() == b"[user]\nvalue=before\n"
    assert list(control.ADMIN.iterdir()) == [destination]


def bundle(path, *, content=b"wheel", expected=None, extra=None):
    manifest = {"version": "1.0.0.dev1", "architecture": "aarch64", "python": "3.13",
                "sha256": {"wheels/application.whl": expected or hashlib.sha256(content).hexdigest()}}
    files = {"bundle.json": json.dumps(manifest).encode(), "wheels/application.whl": content}
    files.update(extra or {})
    return archive(path, files)


def test_bundle_requires_complete_checksums_and_cleans_failed_stage(control, tmp_path):
    source = bundle(tmp_path / "bundle.tar.gz", expected="0" * 64)
    staging = tmp_path / "staging"
    with pytest.raises(ValueError, match="Checksum"):
        control.unpack_bundle(source, staging)
    assert not staging.exists()
    source = bundle(tmp_path / "bundle.tar.gz", extra={"../../escape.whl": b"bad"})
    with pytest.raises(ValueError, match="Invalid bundle"):
        control.unpack_bundle(source, staging)
    assert not staging.exists()


def test_complete_bundle_stages_without_running_its_code(control, tmp_path):
    source = bundle(tmp_path / "bundle.tar.gz")
    result = control.unpack_bundle(source, tmp_path / "staging")
    assert result["architecture"] == "aarch64"
    assert (tmp_path / "staging/wheels/application.whl").read_bytes() == b"wheel"


def test_busy_controller_blocks_even_confirmed_recovery(control, monkeypatch):
    control.write_json(control.STATUS, {"busy": True, "updated": control.time.monotonic()})
    monkeypatch.setattr(control, "command", lambda *_a, **_k: pytest.fail("No service changes while busy"))
    with pytest.raises(ValueError, match="busy"):
        control.enter(confirmed=True)


def test_stopped_controller_requires_explicit_confirmation(control, monkeypatch):
    monkeypatch.setattr(control, "active", lambda: False)
    with pytest.raises(ValueError, match="Confirm"):
        control.enter()
    assert control.enter(confirmed=True)["maintenance"]
    assert control.require_maintenance()["token"]
    control.leave()
    with pytest.raises(ValueError, match="Enter maintenance"):
        control.require_maintenance()


def test_failed_activation_restores_release_and_unchanged_preferences(control, monkeypatch):
    old, new = control.BASE / "old", control.BASE / "new"
    old.mkdir()
    new.mkdir()
    control.point_current(old)
    (control.DATA / "makera.ini").write_text("[user]\nvalue=before\n")
    monkeypatch.setattr(control, "require_maintenance", lambda: {"token": "one"})
    monkeypatch.setattr(control, "command", lambda *_a, **_k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(control, "restore_snapshot", lambda source: load("settings").restore_settings(source, control.DATA))

    def fail(_token):
        (control.DATA / "makera.ini").write_text("[user]\nvalue=changed\n")
        raise RuntimeError("unhealthy startup")

    monkeypatch.setattr(control, "wait_ready", fail)
    with pytest.raises(RuntimeError, match="unhealthy"):
        control.activate(new)
    assert (control.BASE / "current").resolve() == old
    assert (control.DATA / "makera.ini").read_text() == "[user]\nvalue=before\n"


def test_rollback_saves_current_preferences_before_restoring_old_ones(control, monkeypatch):
    old, new = control.BASE / "old", control.BASE / "new"
    old.mkdir()
    new.mkdir()
    control.point_current(new)
    (control.BASE / "previous").symlink_to(old, target_is_directory=True)
    (control.DATA / "makera.ini").write_text("[user]\nvalue=new\n")
    archive(control.BASE / "previous-settings.tar.gz", {"makera.ini": b"[user]\nvalue=old\n"})
    monkeypatch.setattr(control, "require_maintenance", lambda: {"token": "one"})
    monkeypatch.setattr(control, "command", lambda *_a, **_k: SimpleNamespace(returncode=0))
    monkeypatch.setattr(control, "wait_ready", lambda _token: None)
    monkeypatch.setattr(control, "restore_snapshot", lambda source: load("settings").restore_settings(source, control.DATA))
    control.rollback()
    assert (control.BASE / "current").resolve() == old
    assert (control.BASE / "previous").resolve() == new
    assert (control.DATA / "makera.ini").read_text() == "[user]\nvalue=old\n"
    with tarfile.open(control.BASE / "previous-settings.tar.gz") as source:
        assert source.extractfile("makera.ini").read() == b"[user]\nvalue=new\n"


def test_screen_start_preserves_an_existing_service(control, monkeypatch):
    monkeypatch.setattr(control, "active", lambda _service: True)
    monkeypatch.setattr(control, "command", lambda *_a, **_k: pytest.fail("Existing screen service must be preserved"))
    assert control.screen_start() == {"owned": False}


def test_update_retains_current_previous_and_unmanaged_files(control):
    releases = control.BASE / "releases"
    releases.mkdir()
    for name in ("current-version", "previous-version", "old-version", "unmanaged", "staging-0123456789ab"):
        directory = releases / name
        directory.mkdir()
        if name != "unmanaged":
            control.write_json(directory / "bundle.json", {"version": name})
    control.point_current(releases / "current-version")
    (control.BASE / "previous").symlink_to(releases / "previous-version", target_is_directory=True)
    (control.DATA / "job.nc").write_text("G0 X10")
    control.prune_releases()
    assert {path.name for path in releases.iterdir()} == {"current-version", "previous-version", "unmanaged"}
    assert (control.DATA / "job.nc").read_text() == "G0 X10"


def test_failed_dependency_install_removes_staged_files(control, monkeypatch):
    (control.BASE / "releases").mkdir()
    (control.ADMIN / "uploads").mkdir()
    bundle(control.ADMIN / "uploads/app.tar.gz")
    monkeypatch.setattr(control, "require_maintenance", lambda: None)

    def command(*args, **_kwargs):
        if args[0] == "runuser":
            raise RuntimeError("dependency install failed")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(control, "command", command)
    with pytest.raises(RuntimeError, match="dependency install"):
        control.deploy("app.tar.gz")
    assert list((control.BASE / "releases").iterdir()) == []


def test_recovery_can_renew_expired_maintenance_with_idle_confirmation(control, monkeypatch):
    monkeypatch.setattr(control, "active", lambda: False)
    control.enter(confirmed=True)
    lease = control.read_json(control.RUN / "maintenance.json")
    lease["entered"] -= 1801
    control.write_json(control.RUN / "maintenance.json", lease)
    monkeypatch.setitem(sys.modules, "control", control)
    recovery = load("recovery_control")
    calls = []
    monkeypatch.setattr(control, "command", lambda *args, **_k: calls.append(args))
    assert recovery.dispatch({"action": "restart"}) == {"restarted": True}
    assert calls == [("systemctl", "--no-block", "restart", control.SERVICE)]
    assert not (control.RUN / "maintenance.request").exists()


def test_screen_stop_requires_ownership_and_same_service_process(control, monkeypatch):
    control.write_json(control.RUN / "screen.json", {"token": "one", "pid": "100"})
    monkeypatch.setattr(control, "command", lambda *_a, **_k: SimpleNamespace(stdout="200\n"))
    with pytest.raises(ValueError, match="another viewer"):
        control.screen_stop("two")
    with pytest.raises(ValueError, match="replaced"):
        control.screen_stop("one")
    assert (control.RUN / "screen.json").exists()


def test_touchscreen_account_cannot_use_laptop_helper(control, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["control.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"action":"deploy","value":"app.tar.gz"}'))
    monkeypatch.setenv("SUDO_USER", "carvera")
    with pytest.raises(ValueError, match="laptop maintenance"):
        control.main()


def test_recovery_helper_rejects_deploy_even_with_idle_confirmation(control, monkeypatch):
    monkeypatch.setitem(sys.modules, "control", control)
    recovery = load("recovery_control")
    monkeypatch.setattr(sys, "argv", ["recovery_control.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"action":"deploy","confirmed_idle":true}'))
    monkeypatch.setenv("SUDO_USER", "carvera")
    with pytest.raises(ValueError, match="Only Wi-Fi"):
        recovery.main()


def test_display_uses_advertised_refresh_and_actual_connector(monkeypatch):
    display = load("display")
    calls = []

    def command(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(stdout='HDMI-A-2 "EM101"\n  Enabled: yes\n  Modes:\n    1920x1200 px, 59.951000 Hz (preferred, current)\n')

    monkeypatch.setattr(display.subprocess, "run", command)
    display.apply("1920x1200")
    assert calls[-1] == ["wlr-randr", "--output", "HDMI-A-2", "--mode", "1920x1200@59.951000Hz"]
    with pytest.raises(ValueError, match="does not advertise"):
        display.apply("1920x1080")


def test_first_boot_applies_hostname_and_installs_login_key(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ASSETS / "runtime"))
    provision = load("provision")
    boot = tmp_path / "boot/firmware"
    boot.mkdir(parents=True)
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/hosts").write_text("127.0.0.1 localhost\n127.0.1.1 carvera-pi\n")
    (tmp_path / "home/carvera-admin").mkdir(parents=True)
    (tmp_path / "var/lib/carvera").mkdir(parents=True)
    key = "ssh-ed25519 AAAA laptop"
    (boot / "carvera-provision.json").write_text(json.dumps({"hostname": "workshop-panel", "authorized_keys": [key]}))
    monkeypatch.setattr(provision, "BOOT", boot)
    monkeypatch.setattr(provision, "Path", lambda path: tmp_path / str(path).lstrip("/"))
    calls = []
    monkeypatch.setattr(provision.subprocess, "run", lambda args, **_kwargs: calls.append(args))
    provision.main()
    assert ["hostname", "workshop-panel"] in calls
    assert (tmp_path / "etc/hostname").read_text() == "workshop-panel\n"
    assert (tmp_path / "home/carvera-admin/.ssh/authorized_keys").read_text() == key + "\n"
    assert not (boot / "carvera-provision.json").exists()
    assert (tmp_path / "var/lib/carvera/provisioned").exists()
