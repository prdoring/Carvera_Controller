"""System archives and interrupted activation must preserve the working kiosk."""

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from .test_kiosk_maintenance import ASSETS, load


@pytest.fixture
def updater(monkeypatch, tmp_path):
    pytest.importorskip("fcntl")
    monkeypatch.syspath_prepend(str(ASSETS.parents[2] / "carveracontroller"))
    monkeypatch.syspath_prepend(str(ASSETS / "runtime"))
    value = load("system_update")
    for name in ("BASE", "STATE", "RUN", "UNITS", "RUNTIME_UNITS", "UPLOADS"):
        directory = tmp_path / name.lower()
        directory.mkdir()
        monkeypatch.setattr(value, name, directory)
    monkeypatch.setattr(value, "STATUS", tmp_path / "status.json")
    monkeypatch.setattr(value, "SCREEN_CONFIG", tmp_path / "wayvnc.conf")
    return value


def bundle(path, *, extra=None, mutation=None, symbolic=None):
    files = {
        "runtime/control.py": b"# helper\n",
        "runtime/recovery.py": b"# UI\n",
        "runtime/recovery_control.py": b"# recovery\n",
        "config/wayvnc.conf": b"address=127.0.0.1\nport=5901\nenable_auth=false\n",
    }
    files.update(extra or {})
    manifest = {
        "kind": "kiosk-system",
        "format": 1,
        "version": "1.1.0.dev1",
        "architecture": "aarch64",
        "os": "debian-13",
        "python": "3.13",
        "minimum_updater": 1,
        "maintenance_protocols": [1],
        "sha256": {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
    }
    if mutation:
        mutation(manifest)
    files = {"system-bundle.json": json.dumps(manifest).encode(), **files}
    with tarfile.open(path, "w:gz") as output:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(content), 0o644
            output.addfile(info, io.BytesIO(content))
        if symbolic:
            info = tarfile.TarInfo(symbolic)
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            output.addfile(info)
    return path


@pytest.mark.parametrize(
    "name",
    [
        "../../etc/shadow",
        "/etc/passwd",
        "runtime/../../etc/ssh/x",
        "runtime/./control.py",
        "runtime//control.py",
        "runtime/system_update.py",
        "config/sshd_config",
        "units/carvera-provision.service",
        "home/kiosk-admin/key",
    ],
)
def test_root_payload_allow_list(updater, tmp_path, name):
    archive = bundle(tmp_path / "bad.tar.gz", extra={name: b"bad"})
    destination = tmp_path / "stage"
    with pytest.raises(ValueError, match="Invalid system bundle"):
        updater.unpack(archive, destination)
    assert not destination.exists()


def test_checksum_and_platform_validation_precede_extraction(updater, tmp_path):
    for change in (lambda m: m.update(python="3.12"), lambda m: m["sha256"].update({"runtime/control.py": "0" * 64})):
        archive = bundle(tmp_path / "bad.tar.gz", mutation=change)
        with pytest.raises(ValueError):
            updater.unpack(archive, tmp_path / "stage")
        assert not (tmp_path / "stage").exists()
    with pytest.raises(ValueError, match="Invalid"):
        updater.unpack(bundle(tmp_path / "links.tar.gz", symbolic="runtime/link.py"))


def test_screen_configuration_cannot_expose_vnc_to_lan(updater, tmp_path):
    archive = bundle(
        tmp_path / "bad.tar.gz", extra={"config/wayvnc.conf": b"address=0.0.0.0\nport=5901\nenable_auth=false\n"}
    )
    with pytest.raises(ValueError, match="localhost"):
        updater.unpack(archive)


def test_valid_bundle_extracts_only_after_all_checks(updater, tmp_path):
    destination = tmp_path / "stage"
    manifest, expanded = updater.unpack(bundle(tmp_path / "valid.tar.gz"), destination)
    assert manifest["version"] == "1.1.0.dev1" and expanded > 0
    assert (destination / "runtime/control.py").read_bytes() == b"# helper\n"


def test_oversized_header_is_rejected_before_scanning_its_body(updater, tmp_path):
    header = tarfile.TarInfo("system-bundle.json")
    header.size = updater.LIMIT + 1
    archive = tmp_path / "oversized.tar"
    archive.write_bytes(header.tobuf() + b"\0" * 1024)
    with pytest.raises(ValueError, match="supported limits"):
        updater.unpack(archive)


def test_normal_mode_requires_real_fresh_ack(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=3))
    updater.write_json(updater.RUN / "maintenance.json", {"token": "one", "entered": time.monotonic()})
    updater.write_json(updater.RUN / "maintenance.request", {"token": "one"})
    status = {"updated": time.monotonic(), "busy": False, "connected": False, "maintenance": False, "token": "one"}
    updater.write_json(updater.STATUS, status)
    with pytest.raises(ValueError, match="acknowledged"):
        updater.preflight()
    updater.write_json(updater.STATUS, {**status, "maintenance": True})
    assert updater.preflight()["mode"] == "normal"
    updater.write_json(updater.STATUS, {**status, "maintenance": True, "updated": 0})
    with pytest.raises(ValueError, match="stale"):
        updater.preflight()


def test_recovery_does_not_fabricate_controller_status(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=3))
    with pytest.raises(ValueError, match="physically disconnected"):
        updater.preflight(recovery=True)
    assert updater.preflight(recovery=True, confirmed=True)["mode"] == "recovery"
    assert not updater.STATUS.exists()


@pytest.mark.parametrize("field", ["connected", "busy"])
def test_recovery_confirmation_does_not_override_fresh_activity(updater, monkeypatch, field):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=3))
    updater.write_json(updater.STATUS, {"updated": time.monotonic(), field: True})
    with pytest.raises(ValueError, match="cannot be overridden"):
        updater.preflight(recovery=True, confirmed=True)


@pytest.mark.parametrize("name", ["network-checkpoint.json", "display-checkpoint.json", "system-operation.json"])
def test_pending_trials_and_jobs_block_activation(updater, monkeypatch, name):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=3))
    updater.write_json(updater.RUN / name, {"phase": "running", "expires": time.monotonic() + 100})
    with pytest.raises(ValueError, match="trial|operation"):
        updater.preflight(recovery=True, confirmed=True)


def test_live_screen_requires_named_interruption_approval(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=0))
    with pytest.raises(ValueError, match="screen session"):
        updater.preflight(recovery=True, confirmed=True)
    assert updater.preflight(recovery=True, confirmed=True, allow_screen_interruption=True)


def test_shared_lock_rejects_overlapping_mutations(updater):
    with updater.locked(), pytest.raises(ValueError, match="Another maintenance"), updater.locked():
        pytest.fail("Second mutation acquired the same lock")


def test_legacy_conversion_and_failed_first_link_recover_original(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="static"))
    for name in ("maintenance", "recovery-venv"):
        (updater.BASE / name).mkdir()
        (updater.BASE / name / "original").write_text(name)
    tx = {"id": "a" * 32, "mode": "recovery"}
    updater.snapshot_units(tx)
    original_point = updater.point
    monkeypatch.setattr(updater, "point", lambda *_a: (_ for _ in ()).throw(RuntimeError("power loss")))
    with pytest.raises(RuntimeError, match="power loss"):
        updater.import_legacy(tx)
    monkeypatch.setattr(updater, "point", original_point)
    updater.undo(tx, boot=True)
    for name in ("maintenance", "recovery-venv"):
        assert not (updater.BASE / name).is_symlink()
        assert (updater.BASE / name / "original").read_text() == name
    assert not (updater.BASE / "system-ui").exists()


def test_legacy_baseline_records_original_service_files(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_k: SimpleNamespace(returncode=0, stdout="static"))
    for name in ("maintenance", "recovery-venv"):
        (updater.BASE / name).mkdir()
    unit = updater.UNITS / "carvera-screen.service"
    unit.write_text("old screen service")
    tx = {"id": "b" * 32, "mode": "recovery"}
    updater.snapshot_units(tx)
    baseline = updater.import_legacy(tx)
    unit.write_text("new screen service")
    updater.install_units(baseline)
    assert unit.read_text() == "old screen service"
    assert (updater.BASE / "maintenance").is_symlink()


@pytest.mark.parametrize("alias", ["maintenance", "recovery-venv", "system-ui"])
@pytest.mark.parametrize("operation", ["rename", "symlink_to"])
def test_every_legacy_conversion_boundary_restores_original(updater, monkeypatch, alias, operation):
    monkeypatch.setattr(updater, "command", lambda *_a, **_kw: SimpleNamespace(stdout="static", returncode=0))
    for name in updater.ALIASES:
        path = updater.BASE / name
        path.mkdir()
        (path / "original").write_text(name)
    original = getattr(Path, operation)

    def interrupted(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == updater.BASE / alias:
            raise RuntimeError("power loss after conversion")
        return result

    monkeypatch.setattr(Path, operation, interrupted)
    transaction = {"id": "9" * 32, "mode": "recovery"}
    updater.snapshot_units(transaction)
    with pytest.raises(RuntimeError, match="power loss"):
        updater.import_legacy(transaction)
    updater.undo(transaction, boot=True)
    for name in updater.ALIASES:
        path = updater.BASE / name
        assert not path.is_symlink()
        assert (path / "original").read_text() == name


def test_failed_health_rolls_back_without_touching_account_state(updater, monkeypatch):
    previous, release = updater.BASE / "system-releases/previous", updater.BASE / "system-releases/new"
    previous.mkdir(parents=True)
    release.mkdir()
    updater.point("system-current", previous)
    credential = updater.STATE / "access-complete.json"
    credential.write_text('{"key":"retained"}')
    monkeypatch.setattr(updater, "preflight", lambda **_kw: {"mode": "recovery", "controller_active": False})
    monkeypatch.setattr(updater, "command", lambda *_a, **_kw: SimpleNamespace(stdout="static", returncode=0))
    monkeypatch.setattr(updater, "session_hook_override", lambda *_a: None)
    monkeypatch.setattr(updater, "install_units", lambda *_a: None)
    calls = []

    def check(_transaction, target):
        calls.append(target)
        if target == release:
            raise RuntimeError("UI did not render")

    monkeypatch.setattr(updater, "start_and_check", check)
    with pytest.raises(RuntimeError, match="UI did not render"):
        updater.apply_release(release, {})
    assert (updater.BASE / "system-current").resolve() == previous
    assert calls == [release, previous]
    assert credential.read_text() == '{"key":"retained"}'


def test_unfinished_rollback_cannot_be_overwritten(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_kw: SimpleNamespace(stdout="starting", returncode=3))
    transaction = {"id": "c" * 32, "phase": "activating", "unit_snapshot": {"saved": True}}
    updater.save_transaction(transaction)
    with pytest.raises(ValueError, match="interrupted system transaction"):
        updater.submit({"action": "rollback", "options": {"recovery": True, "confirmed": True}})
    assert updater.read_json(updater.STATE / "transaction.json") == transaction


def test_live_boot_recovery_refuses_without_mutation(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_kw: SimpleNamespace(stdout="running", returncode=0))
    transaction = {"phase": "activating"}
    updater.save_transaction(transaction)
    with pytest.raises(ValueError, match="only during startup"):
        updater.recover(boot=True)
    assert updater.read_json(updater.STATE / "transaction.json") == transaction


def test_preparation_cleanup_preserves_unfinished_transaction(updater):
    stage = updater.BASE / "system-releases/staging-test"
    stage.mkdir(parents=True)
    job = updater.STATE / "jobs" / ("d" * 32)
    updater.write_json(job / "preparation.json", {"stage": str(stage)})
    updater.save_transaction({"phase": "activating"})
    updater.clean_preparation(job)
    assert stage.exists() and (job / "preparation.json").exists()
    updater.save_transaction({"phase": "rolled-back"})
    updater.clean_preparation(job)
    assert not stage.exists() and not (job / "preparation.json").exists()


def test_boot_recovery_cleans_interrupted_preparation(updater, monkeypatch):
    monkeypatch.setattr(updater, "command", lambda *_a, **_kw: SimpleNamespace(stdout="starting", returncode=0))
    stage = updater.BASE / "system-releases/staging-test"
    stage.mkdir(parents=True)
    job = updater.STATE / "jobs" / ("e" * 32)
    updater.write_json(job / "preparation.json", {"stage": str(stage)})
    updater.write_json(job / "result.json", {"phase": "running", "boot_id": "previous-boot"})
    updater.recover(boot=True)
    assert not stage.exists()
    assert updater.read_json(job / "result.json")["phase"] == "failed"


def test_hook_install_failure_is_rolled_back(updater, monkeypatch):
    previous = updater.BASE / "system-releases/working"
    previous.mkdir(parents=True)
    updater.point("system-current", previous)
    monkeypatch.setattr(updater, "preflight", lambda **_kw: {"mode": "recovery"})
    monkeypatch.setattr(updater, "command", lambda *_a, **_kw: SimpleNamespace(stdout="static", returncode=0))
    calls = []

    def hook(enabled):
        calls.append(enabled)
        if len(calls) == 1:
            raise RuntimeError("daemon reload failed")

    monkeypatch.setattr(updater, "session_hook_override", hook)
    monkeypatch.setattr(updater, "start_and_check", lambda *_a: None)
    with pytest.raises(RuntimeError, match="daemon reload"):
        updater.apply_release(updater.BASE / "unused", {})
    assert updater.read_json(updater.STATE / "transaction.json")["phase"] == "rolled-back"
    assert calls[-1] is False
    assert (updater.BASE / "system-current").resolve() == previous


def test_finalization_holds_lock_and_publishes_completion_last(updater, monkeypatch):
    identity = "f" * 32
    job = updater.STATE / "jobs" / identity
    updater.write_json(job / "request.json", {"action": "apply"})
    monkeypatch.setattr(updater, "prepare_release", lambda *_a: updater.BASE / "candidate")
    monkeypatch.setattr(updater, "apply_release", lambda *_a: {"current": "candidate"})

    def prune():
        assert updater.read_json(job / "result.json")["phase"] == "running"
        with pytest.raises(ValueError, match="Another maintenance"), updater.locked():
            pytest.fail("An overlapping app mutation entered during finalization")

    monkeypatch.setattr(updater, "prune_releases", prune)
    updater.worker(identity)
    assert updater.read_json(job / "result.json")["phase"] == "complete"


def test_low_storage_never_removes_working_release(updater, monkeypatch, tmp_path):
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=debian\nVERSION_ID="13"\n')
    path_type = updater.Path
    monkeypatch.setattr(
        updater, "Path", lambda *parts: os_release if parts == ("/etc/os-release",) else path_type(*parts)
    )
    monkeypatch.setattr(updater.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(updater.sys, "version_info", (3, 13))
    monkeypatch.setattr(updater.shutil, "disk_usage", lambda _p: SimpleNamespace(free=0))
    working = updater.BASE / "system-releases/working"
    working.mkdir(parents=True)
    with pytest.raises(ValueError, match="Insufficient storage"):
        updater.prepare_release(bundle(tmp_path / "candidate.tar.gz"))
    assert working.is_dir()
    assert not list(working.parent.glob("staging-*"))
