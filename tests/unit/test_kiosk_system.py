"""System actions remain bounded, explicit and recoverable without hardware."""

import json
import sys
from types import SimpleNamespace

import pytest

from .test_kiosk_maintenance import archive, load, make_control


@pytest.fixture
def control(monkeypatch, tmp_path):
    return make_control(monkeypatch, tmp_path)


@pytest.fixture
def operations(control, monkeypatch):
    monkeypatch.setitem(sys.modules, "control", control)
    value = load("system_operations")
    monkeypatch.setitem(sys.modules, "system_operations", value)
    return value


def request(action, **kwargs):
    return {"action": action, "id": "a" * 32, **kwargs}


@pytest.mark.parametrize(
    "action", ["wifi", "restart", "reboot", "shutdown", "update", "restore", "display", "rollback"]
)
def test_changes_require_idle_confirmation(operations, action):
    with pytest.raises(ValueError, match="Confirm"):
        operations.dispatch(request(action))


@pytest.mark.parametrize("value", [[], {"action": []}, request("shell"), request("restart", command="true")])
def test_invalid_requests_do_not_dispatch(operations, value):
    with pytest.raises(ValueError):
        operations.validate(value)


def test_laptop_maintenance_cannot_be_taken_over(operations, control, monkeypatch):
    control.write_json(control.RUN / "maintenance.json", {"owner": "laptop", "token": "one"})
    monkeypatch.setattr(control, "enter", lambda **_kw: pytest.fail("Do not replace laptop session"))
    with pytest.raises(ValueError, match="laptop"):
        operations.dispatch(request("restart", confirmed_idle=True))
    with pytest.raises(ValueError, match="laptop"):
        operations.dispatch(request("leave"))


def test_busy_controller_blocks_system_changes(operations, control):
    control.write_json(control.STATUS, {"busy": True, "updated": control.time.monotonic()})
    with pytest.raises(ValueError, match="busy"):
        operations.dispatch(request("shutdown", confirmed_idle=True))


def test_pending_network_blocks_restart_and_maintenance_exit(operations, control, monkeypatch):
    monkeypatch.setattr(operations, "maintenance", lambda: None)
    control.write_json(control.RUN / "network-checkpoint.json", {"expires": control.time.monotonic() + 100})
    with pytest.raises(ValueError, match="Wi-Fi"):
        operations.dispatch(request("restart", confirmed_idle=True))
    with pytest.raises(ValueError, match="120-second"):
        operations.finish()


def test_expired_network_cannot_be_kept(control, monkeypatch):
    monkeypatch.setattr(control, "require_maintenance", lambda: None)
    control.write_json(control.RUN / "network-checkpoint.json", {"expires": control.time.monotonic() - 1})
    with pytest.raises(ValueError, match="expired"):
        control.network_confirm()


def test_return_checks_current_controller_status(operations, control):
    import os

    assert operations.dispatch(request("leave"))["controller_available"] is False
    control.write_json(control.STATUS, {"pid": os.getpid(), "updated": control.time.monotonic()})
    assert operations.dispatch(request("leave"))["controller_available"] is True
    control.write_json(control.STATUS, {"pid": os.getpid(), "updated": 0})
    assert operations.dispatch(request("leave"))["controller_available"] is False


def test_display_preview_arms_independent_rollback_before_applying(operations, control, monkeypatch, tmp_path):
    config = tmp_path / "display-mode"
    config.write_text("1920x1200\n")
    original = operations.Path
    monkeypatch.setattr(operations, "Path", lambda p: config if str(p) == "/etc/carvera/display-mode" else original(p))
    calls = []
    monkeypatch.setattr(control, "command", lambda *args, **_kw: calls.append(args))
    operations.display_trial("1920x1080")
    assert calls[0][0] == "systemd-run"
    assert "--on-active=20s" in calls[0]
    assert calls[1][-1] == "1920x1080"
    assert config.read_text() == "1920x1200\n"
    checkpoint = control.read_json(control.RUN / "display-checkpoint.json")
    operations.revert_display("wrong-token")
    assert (control.RUN / "display-checkpoint.json").exists()
    operations.revert_display(checkpoint["token"])
    assert calls[-1][-1] == "1920x1200"
    assert not (control.RUN / "display-checkpoint.json").exists()


def test_failed_display_apply_restores_saved_mode(operations, control, monkeypatch, tmp_path):
    config = tmp_path / "display-mode"
    config.write_text("1920x1200\n")
    original = operations.Path
    monkeypatch.setattr(operations, "Path", lambda p: config if str(p) == "/etc/carvera/display-mode" else original(p))
    monkeypatch.setattr(control, "command", lambda *_a, **_kw: None)
    calls = []

    def apply(mode):
        calls.append(mode)
        if mode == "1920x1080":
            raise RuntimeError("Unsupported mode")

    monkeypatch.setattr(operations, "display_command", apply)
    with pytest.raises(RuntimeError, match="Unsupported"):
        operations.display_trial("1920x1080")
    assert calls == ["1920x1080", "1920x1200"]
    assert not (control.RUN / "display-checkpoint.json").exists()


def test_scan_preserves_escaped_names_and_marks_unsupported_security(operations, control, monkeypatch):
    text = "Shop\\:WiFi:85:WPA2:*\nShop\\:WiFi:50:WPA2:\nEnterprise:95:WPA2 802.1X:\nOpen:40::\n"
    monkeypatch.setattr(control, "command", lambda *_a, **_kw: SimpleNamespace(stdout=text))
    result = operations.scan()["networks"]
    assert [entry["ssid"] for entry in result] == ["Enterprise", "Shop:WiFi", "Open"]
    assert result[1]["supported"] and result[1]["active"]
    assert not result[0]["supported"] and not result[2]["supported"]


@pytest.mark.parametrize("security,supported", [("WPA2 WPA3", True), ("WPA3", False), ("WPA2 802.1X", False)])
def test_scan_distinguishes_transition_and_enterprise_networks(operations, control, monkeypatch, security, supported):
    monkeypatch.setattr(control, "command", lambda *_args, **_kw: SimpleNamespace(stdout=f"Shop:80:{security}:\n"))
    assert operations.scan()["networks"][0]["supported"] is supported


def test_listing_staged_files_does_not_hash_every_archive(operations, control, monkeypatch):
    (control.ADMIN / "uploads").mkdir()
    archive(control.ADMIN / "uploads/preferences.tar.gz", {"makera.ini": b"[user]\nvalue=1\n"})
    monkeypatch.setattr(operations, "inspect_file", lambda _path: pytest.fail("Hash only the file selected for review"))
    result = operations.files()["files"]
    assert len(result) == 1 and result[0]["name"] == "preferences.tar.gz"
    assert "sha256" not in result[0]


def test_staged_file_is_copied_privately_and_digest_checked(operations, control):
    (control.ADMIN / "uploads").mkdir()
    source = archive(control.ADMIN / "uploads/preferences.tar.gz", {"makera.ini": b"[user]\nvalue=1\n"})
    details = operations.inspect_file(source)
    directory, selected = operations.private_copy({"name": source.name, "sha256": details["sha256"]})
    try:
        assert selected.read_bytes() == source.read_bytes()
        assert selected.parent.stat().st_mode & 0o777 == 0o700
    finally:
        directory.cleanup()
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        operations.private_copy({"name": source.name, "sha256": details["sha256"]})


def test_staged_symlink_and_path_escape_rejected(operations, control, tmp_path):
    (control.ADMIN / "uploads").mkdir()
    source = tmp_path / "private.tar.gz"
    source.write_bytes(b"secret")
    (control.ADMIN / "uploads/link.tar.gz").symlink_to(source)
    for name in ("link.tar.gz", "../../private.tar.gz"):
        with pytest.raises(ValueError):
            operations.private_copy({"name": name, "sha256": "0" * 64})


@pytest.mark.parametrize("content", [b"invalid", b"[", b"[]"])
def test_restore_validates_all_contents_before_modifying_data(tmp_path, content):
    source = archive(tmp_path / "backup.tar.gz", {"makera.ini": b"[user]\nvalue=new\n", ".kivy/a.json": content})
    data = tmp_path / "data"
    data.mkdir()
    (data / "makera.ini").write_text("[user]\nvalue=old\n")
    with pytest.raises(ValueError):
        load("settings").restore_settings(source, data)
    assert "value=old" in (data / "makera.ini").read_text()


def test_failed_operation_records_no_request_secrets(operations, control, monkeypatch):
    monkeypatch.setattr(operations, "dispatch", lambda _request: (_ for _ in ()).throw(RuntimeError("Not connected")))
    with pytest.raises(RuntimeError):
        operations.run(
            request("wifi", confirmed_idle=True, wifi={"ssid": "secret-network", "password": "secret-password"})
        )
    stored = (control.RUN / "system-operation.json").read_text()
    assert "secret" not in stored
    assert json.loads(stored)["phase"] == "failed"


def test_status_reports_interrupted_operation(operations, control, monkeypatch):
    operations.remember({"id": "a" * 32, "pid": 9999999, "phase": "running"})
    monkeypatch.setattr(operations.os, "kill", lambda *_args: (_ for _ in ()).throw(ProcessLookupError()))
    assert operations.operation_status()["phase"] == "interrupted"


def test_recovery_never_stops_during_activation(control, monkeypatch):
    old, new = control.BASE / "old", control.BASE / "new"
    old.mkdir()
    new.mkdir()
    control.point_current(old)
    (control.DATA / "makera.ini").write_text("[user]\nvalue=1\n")
    monkeypatch.setattr(control, "require_maintenance", lambda: {"token": "one"})
    monkeypatch.setattr(control, "wait_ready", lambda _token: None)
    calls = []
    monkeypatch.setattr(control, "command", lambda *args, **_kw: calls.append(args))
    control.activate(new)
    assert all("carvera-recovery.service" not in args for args in calls)


def test_same_operation_identity_never_executes_twice(operations, monkeypatch):
    calls = []
    monkeypatch.setattr(operations, "dispatch", lambda value: calls.append(value) or {"saved": True})
    first = operations.run(request("backup"))
    assert operations.run(request("backup")) == first
    assert len(calls) == 1


def test_expired_display_preview_reverts_instead_of_persisting(operations, control, monkeypatch):
    control.write_json(
        control.RUN / "display-checkpoint.json", {"previous": "1920x1200", "mode": "1920x1080", "expires": 0}
    )
    restored = []
    monkeypatch.setattr(operations, "display_command", restored.append)
    with pytest.raises(ValueError, match="expired"):
        operations.confirm_display()
    assert restored == ["1920x1200"]
    assert not (control.RUN / "display-checkpoint.json").exists()


def test_preference_restore_failure_recovers_private_snapshot(control, monkeypatch, tmp_path):
    import os

    (control.ADMIN / "exports").mkdir()
    (control.DATA / "makera.ini").write_text("[user]\nvalue=old\n")
    selected = archive(tmp_path / "selected.tar.gz", {"makera.ini": b"[user]\nvalue=new\n"})
    monkeypatch.setattr(control, "require_maintenance", lambda: {"token": "one"})
    monkeypatch.setattr(control.subprocess, "run", lambda *_a, **_kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(control.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
    monkeypatch.setattr(control, "command", lambda *_a, **_kw: None)
    monkeypatch.setattr(
        control, "restore_snapshot", lambda source: load("settings").restore_settings(source, control.DATA)
    )

    def ready(_token):
        if "value=new" in (control.DATA / "makera.ini").read_text():
            raise RuntimeError("Startup failed")

    monkeypatch.setattr(control, "wait_ready", ready)
    with pytest.raises(RuntimeError, match="Startup failed"):
        control.restore_preferences(selected)
    assert "value=old" in (control.DATA / "makera.ini").read_text()
    exports = list((control.ADMIN / "exports").iterdir())
    assert len(exports) == 1 and exports[0].name.startswith("before-restore-")


def test_system_launch_uses_its_own_service_without_maintenance(operations, control, monkeypatch):
    calls = []
    monkeypatch.setattr(control, "command", lambda *args, **_kwargs: calls.append(args))
    assert operations.dispatch(request("open")) == {"opened": True}
    assert calls == [("systemctl", "--no-block", "start", "carvera-recovery.service")]
    assert not (control.RUN / "maintenance.request").exists()


def test_operations_run_in_a_separate_unit_without_credentials_in_arguments(operations, control, monkeypatch):
    import os

    helper = load("recovery_control")
    calls = []
    monkeypatch.setattr(operations, "dispatch", lambda _request: {"saved": True})

    def start(args, **kwargs):
        calls.append(args)
        path = control.RUN / ("system-request-" + "a" * 32 + ".json")
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_text())["wifi"]["password"] == "secret-password"

        def communicate(timeout):
            result = helper.execute_operation("a" * 32)
            return json.dumps({"ok": True, "result": result}), ""

        return SimpleNamespace(communicate=communicate, returncode=0)

    monkeypatch.setattr(helper.subprocess, "Popen", start)
    value = request("wifi", confirmed_idle=True, wifi={"ssid": "Shop", "password": "secret-password"})
    assert helper.launch_operation(value) == {"saved": True}
    assert helper.launch_operation(value) == {"saved": True}
    assert len(calls) == 1
    assert calls[0][0] == "systemd-run"
    assert "--collect" in calls[0] and "--property=RuntimeMaxSec=1800s" in calls[0]
    assert "secret-password" not in str(calls)
    assert "secret-password" not in (control.RUN / "system-operation.json").read_text()
    assert not list(control.RUN.glob("system-request-*.json"))


def test_an_active_worker_blocks_new_operations(operations, control, monkeypatch):
    import os

    helper = load("recovery_control")
    operations.remember({"id": "b" * 32, "phase": "running", "pid": os.getpid()})
    monkeypatch.setattr(helper.subprocess, "Popen", lambda *_args, **_kw: pytest.fail("Do not queue another worker"))
    with pytest.raises(ValueError, match="in progress"):
        helper.launch_operation(request("backup"))


def test_reused_process_id_does_not_leave_an_operation_running(operations, control):
    import os

    control.write_json(
        control.RUN / "system-operation.json", {"pid": os.getpid(), "phase": "running", "process_start": "old-process"}
    )
    assert operations.operation_status()["phase"] == "interrupted"
