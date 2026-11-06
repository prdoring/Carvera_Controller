"""Crash boundaries across the complete v3 provisioning transaction."""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fcntl")

RUNTIME = Path(__file__).resolve().parents[2] / "assets/packaging/kiosk/runtime"


@pytest.fixture
def boot_setup(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(RUNTIME))
    module = importlib.import_module("provision_v3")
    root = tmp_path / "root"
    for name in (
        "etc",
        "home/carvera-admin",
        "home/kiosk-admin",
        "var/lib/carvera",
        "boot/firmware",
        "var/lib/carvera-system",
    ):
        (root / name).mkdir(parents=True, exist_ok=True)
    (root / "etc/hosts").write_text("127.0.0.1 localhost\n")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "BOOT", root / "boot/firmware")
    monkeypatch.setattr(module, "STATE", root / "var/lib/carvera-system")
    monkeypatch.setattr(module, "RUNTIME", root / "run/carvera-maint")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.accounts, "STATE", module.STATE)
    monkeypatch.setattr(module.accounts, "public_keys", lambda keys: (keys, ["SHA256:test"]))
    calls = []
    monkeypatch.setattr(module, "command", lambda *args: calls.append(args) or SimpleNamespace(stdout=""))

    def install(value):
        module.accounts.write_json(module.STATE / "access-complete.json", {"id": value["id"]})
        (root / "home/kiosk-admin/.ssh").mkdir(exist_ok=True)
        module.accounts.atomic_write(
            root / "home/kiosk-admin/.ssh/authorized_keys", "\n".join(value["admin_public_keys"])
        )

    monkeypatch.setattr(module.accounts, "install", install)
    image = {"format": module.protocol.IMAGE_FORMAT, "version": "1.1.0.dev5", "commit": "a" * 40, "setup_protocol": 1}
    module.protocol.write_json(module.BOOT / "carvera-image.json", image)
    module.protocol.write_json(module.BOOT / module.protocol.RECEIPT, module.protocol.receipt("fresh"))
    module.protocol.write_json(module.STATE / "root-grow.json", {"phase": "complete"})
    value = {
        "format": 2,
        "setup_protocol": 1,
        "id": "b" * 32,
        "hostname": "carvera-test",
        "authorized_keys": ["ssh-ed25519 YWJj"],
        "admin_public_keys": ["ssh-ed25519 ZGVm"],
        "wifi": {"ssid": "Workshop", "password": "private-test-value", "country": "US"},
    }
    module.protocol.prepare(module.BOOT, value, module.accounts.public_keys)
    return module, root, value, calls


def test_boot_completion_is_authoritative_and_public_status_redacted(boot_setup):
    module, _root, value, _calls = boot_setup
    module.run()
    assert module.completion_ready()
    assert module.protocol.read_json(module.BOOT / module.protocol.RECEIPT)["phase"] == "complete"
    assert not (module.BOOT / module.protocol.REQUEST).exists()
    public = json.dumps(module.status()) + (module.RUNTIME / "setup-status.json").read_text()
    assert value["wifi"]["password"] not in public
    assert module.protocol.identity(value)[1] not in public


@pytest.mark.parametrize("step", ["hostname_step", "maintenance_step", "network_step", "settings_step"])
def test_failure_after_each_change_resumes_only_same_transaction(boot_setup, monkeypatch, step):
    module, _root, value, _calls = boot_setup
    original = getattr(module, step)

    def failed(request):
        original(request)
        raise OSError("injected interruption")

    monkeypatch.setattr(module, step, failed)
    with pytest.raises(OSError):
        module.run()
    assert not module.completion_ready()
    assert module.protocol.read_json(module.BOOT / module.protocol.RECEIPT)["phase"] == "applying"
    changed = {**value, "id": "c" * 32}
    module.protocol.write_json(module.BOOT / module.protocol.REQUEST, changed)
    module.protocol.write_json(
        module.BOOT / module.protocol.RECEIPT, module.protocol.receipt("prepared", changed["id"])
    )
    with pytest.raises(ValueError, match="original"):
        module.run()
    module.protocol.write_json(module.BOOT / module.protocol.REQUEST, value)
    monkeypatch.setattr(module, step, original)
    module.run()
    assert module.completion_ready()


def test_completed_replay_never_restores_revoked_keys(boot_setup, monkeypatch):
    module, root, _value, _calls = boot_setup
    module.run()
    for home in ("carvera-admin", "kiosk-admin"):
        (root / "home" / home / ".ssh/authorized_keys").write_text("")
    monkeypatch.setattr(module.accounts, "install", lambda _value: pytest.fail("Completed access must not replay"))
    (module.BOOT / module.protocol.RECEIPT).unlink()
    module.run()
    assert module.protocol.read_json(module.BOOT / module.protocol.RECEIPT)["phase"] == "complete"
    assert module.status()["key_fingerprints"] == {"maintenance": [], "administrator": []}


def test_root_completion_survives_failure_to_write_fat_receipt(boot_setup, monkeypatch):
    module, _root, _value, _calls = boot_setup
    original = module.protocol.write_json

    def failed(path, value):
        if path == module.BOOT / module.protocol.RECEIPT and value.get("phase") == "complete":
            raise OSError("injected FAT write failure")
        original(path, value)

    monkeypatch.setattr(module.protocol, "write_json", failed)
    with pytest.raises(OSError):
        module.run()
    assert module.completion_ready()
    monkeypatch.setattr(module.protocol, "write_json", original)
    monkeypatch.setattr(module.accounts, "install", lambda _value: pytest.fail("Only reconcile completion"))
    module.run()
    assert not module.status()["cleanup_pending"]


def test_missing_or_invalid_image_does_not_authorize_controller_start(boot_setup):
    module, _root, _value, _calls = boot_setup
    (module.BOOT / "carvera-image.json").unlink()
    assert not module.completion_ready()
    (module.BOOT / "carvera-image.json").write_text("not json")
    assert not module.completion_ready()


def test_missing_root_journal_never_turns_an_applying_card_fresh(boot_setup):
    module, _root, value, calls = boot_setup
    module.protocol.write_json(module.BOOT / module.protocol.RECEIPT, module.protocol.receipt("applying", value["id"]))
    with pytest.raises(ValueError, match="journal is missing"):
        module.run()
    assert not calls
    assert module.protocol.read_json(module.BOOT / module.protocol.RECEIPT)["phase"] == "applying"


def test_empty_authoritative_completion_never_replays_initial_setup(boot_setup):
    module, _root, _value, calls = boot_setup
    module.protocol.write_json(module.STATE / "setup-complete.json", {})
    with pytest.raises(ValueError, match="completion record"):
        module.run()
    assert not calls
