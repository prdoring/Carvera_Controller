"""Administrator setup, identity transport and offline migration contracts."""

import hashlib
import importlib.util
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "assets/packaging/kiosk/runtime"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    value = load(RUNTIME / "admin_accounts.py", "test_admin_accounts")
    monkeypatch.setattr(value, "STATE", tmp_path / "state")
    return value


@pytest.fixture
def laptop(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return load(ROOT / "scripts/kiosk.py", "test_admin_laptop")


@pytest.fixture
def migration(laptop):
    return laptop.kiosk_admin


def request():
    return {"id": "a" * 32, "admin_public_keys": ["ssh-ed25519 YWJj test"], "legacy_gate": True}


def test_key_validation_rejects_options_multiline_and_private_material(accounts):
    for key in ("command=evil ssh-ed25519 YWJj", "ssh-ed25519 YWJj\nssh-ed25519 YWJj", "-----BEGIN PRIVATE KEY-----"):
        with pytest.raises(ValueError):
            accounts.public_keys([key])


def test_public_keys_are_parsed_and_deduplicated(accounts, monkeypatch):
    calls = []
    monkeypatch.setattr(
        accounts,
        "command",
        lambda *args: calls.append(args) or SimpleNamespace(stdout="256 SHA256:known comment (ED25519)\n"),
    )
    keys, fingerprints = accounts.public_keys(["ssh-ed25519 YWJj one", "ssh-ed25519 YWJj two"])
    assert len(keys) == 1 and fingerprints == ["SHA256:known"]
    assert all(call[0] == "ssh-keygen" for call in calls)


def test_ssh_policy_preserves_other_users_and_requires_keys(accounts):
    value = accounts.ssh_policy("AllowUsers carvera-admin owner\nPermitRootLogin yes\nX11Forwarding no\n")
    assert "AllowUsers carvera-admin owner kiosk-admin" in value
    assert "permitrootlogin no" in value and "PermitRootLogin yes" not in value
    assert "X11Forwarding no" in value
    with pytest.raises(ValueError, match="custom"):
        accounts.ssh_policy("Match User custom\n")


def test_effective_policy_parses_repeated_allowusers(accounts, monkeypatch):
    runtime = SimpleNamespace(
        mkdir=lambda **_kwargs: None,
        is_symlink=lambda: False,
        stat=lambda: SimpleNamespace(st_uid=0, st_mode=0o755),
    )
    def runtime_path(name):
        assert name == "/run/sshd"
        return runtime
    monkeypatch.setattr(accounts, "Path", runtime_path)

    def run(*args):
        if "-T" in args:
            return SimpleNamespace(
                stdout="permitrootlogin no\npasswordauthentication no\nauthenticationmethods publickey\nallowusers carvera-admin\nallowusers kiosk-admin\n"
            )
        if args[0] == "sudo":
            return SimpleNamespace(stdout="(ALL : ALL) NOPASSWD: ALL\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(accounts, "command", run)
    accounts.validate_policy()


@pytest.fixture
def installed_account(accounts, monkeypatch, tmp_path):
    pwd = pytest.importorskip("pwd")
    monkeypatch.setattr(accounts.os, "geteuid", lambda: 0)
    monkeypatch.setattr(accounts, "public_keys", lambda _keys: (["ssh-ed25519 YWJj"], ["SHA256:known"]))
    user = SimpleNamespace(pw_dir="/home/kiosk-admin", pw_uid=os.getuid(), pw_gid=os.getgid())
    state = {"account": None}

    def lookup(_name):
        if state["account"] is None:
            raise KeyError()
        return state["account"]

    def command(*args, **_kwargs):
        if args[0] == "useradd":
            state["account"] = user
            (tmp_path / "root/home/kiosk-admin").mkdir(parents=True)
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(pwd, "getpwnam", lookup)
    monkeypatch.setattr(accounts, "command", command)
    monkeypatch.setattr(accounts, "validate_policy", lambda: None)
    root = tmp_path / "root"
    policy = root / "etc/ssh/sshd_config.d/50-carvera.conf"
    policy.parent.mkdir(parents=True)
    policy.write_text("AllowUsers carvera-admin\n")
    return root, state, user


def test_completed_setup_cannot_reinstall_a_revoked_key(accounts, installed_account):
    root, _state, _user = installed_account
    first = accounts.install(request(), root)
    key = root / "home/kiosk-admin/.ssh/authorized_keys"
    key.write_text("")
    assert accounts.install(request(), root) == first
    assert key.read_text() == ""
    other = {**request(), "id": "b" * 32}
    with pytest.raises(ValueError, match="complete"):
        accounts.install(other, root)
    assert key.read_text() == ""


def test_partial_setup_restores_policy_and_resumes(accounts, installed_account, monkeypatch):
    root, _state, _user = installed_account
    policy = root / "etc/ssh/sshd_config.d/50-carvera.conf"
    monkeypatch.setattr(accounts, "validate_policy", lambda: (_ for _ in ()).throw(ValueError("invalid policy")))
    with pytest.raises(ValueError, match="invalid policy"):
        accounts.install(request(), root)
    assert policy.read_text() == "AllowUsers carvera-admin\n"
    assert not (root / "etc/sudoers.d/kiosk-admin").exists()
    monkeypatch.setattr(accounts, "validate_policy", lambda: None)
    assert accounts.install(request(), root)["account"] == "kiosk-admin"


def test_unrecognized_existing_account_is_not_taken_over(accounts, installed_account):
    root, state, user = installed_account
    state["account"] = user
    with pytest.raises(ValueError, match="unrecognized"):
        accounts.install(request(), root)


def test_identity_and_alias_apply_to_ssh_and_scp(laptop, tmp_path):
    laptop.IDENTITY = str(tmp_path / "owner key")
    laptop.HOST_KEY_ALIAS = "carvera-pi.local"
    ssh, scp = laptop.ssh_args("kiosk-admin@192.0.2.1"), laptop.scp_args("kiosk-admin@192.0.2.1")
    assert "StrictHostKeyChecking=yes" in ssh and "IdentitiesOnly=yes" in ssh
    assert "HostKeyAlias=carvera-pi.local" in ssh
    assert scp[1:] == ssh[1:-1]


@pytest.fixture
def prepared(migration, monkeypatch, tmp_path):
    original = b"console=tty1 root=/dev/disk/by-slot/system rootwait\n"
    target = {
        "image": {"format": "carvera-kiosk-pi4", "version": "1"},
        "capacity": 4096,
        "boot_uuid": "ABCD-1234",
        "boot_partuuid": "12345678-01",
        "root_partuuid": "12345678-02",
        "ssh_fingerprint": "SHA256:pi",
        "cmdline_sha256": hashlib.sha256(original).hexdigest(),
    }
    monkeypatch.setattr(migration, "key_files", lambda _paths: (["ssh-ed25519 YWJj"], ["SHA256:owner"]))
    monkeypatch.setattr(migration, "target_report", lambda *_args: (target, original))
    package = tmp_path / "package with spaces"
    migration.prepare(None, "carvera-admin@pi", ["owner.pub"], package)
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "carvera-image.json").write_text(json.dumps(target["image"]))
    (boot / "cmdline.txt").write_bytes(original)
    monkeypatch.setattr(
        migration, "volume_identity", lambda _boot: {"capacity": 4096, "boot_uuid": "ABCD-1234", "disk": 9}
    )
    first, second = tmp_path / "first.dd", tmp_path / "second.dd"
    image = bytearray(4096)
    image[510:512] = b"\x55\xaa"
    struct.pack_into("<I", image, 440, 0x12345678)
    image[450] = 0x0C
    struct.pack_into("<II", image, 454, 1, 2)
    image[466] = 0x83
    struct.pack_into("<II", image, 470, 3, 5)
    image[512 + 82 : 512 + 90] = b"FAT32   "
    struct.pack_into("<I", image, 512 + 67, 0xABCD1234)
    first.write_bytes(image)
    second.write_bytes(image)
    return boot, package, first, second, original


def test_stage_and_undo_preserve_exact_original_boot_arguments(migration, prepared):
    boot, package, first, second, original = prepared
    result = migration.stage(boot, package, first, second)
    staged = (boot / "cmdline.txt").read_bytes()
    assert original.rstrip() in staged and b'systemd.run="/bin/bash ' in staged
    assert b"systemd.run_failure_action=poweroff" in staged
    assert result["backup"]["bytes"] == 4096
    migration.undo(boot)
    assert (boot / "cmdline.txt").read_bytes() == original


def test_bad_backup_or_target_does_not_change_boot(migration, prepared, monkeypatch):
    boot, package, first, second, original = prepared
    second.write_bytes(b"b" * 4096)
    with pytest.raises(ValueError, match="backup"):
        migration.stage(boot, package, first, second)
    assert (boot / "cmdline.txt").read_bytes() == original
    monkeypatch.setattr(migration, "volume_identity", lambda _boot: {"capacity": 64, "boot_uuid": "wrong"})
    with pytest.raises(ValueError, match="does not match"):
        migration.stage(boot, package, first, second)
    assert (boot / "cmdline.txt").read_bytes() == original


def test_undo_does_not_require_uncorrupted_executable_payload(migration, prepared):
    boot, package, first, second, original = prepared
    migration.stage(boot, package, first, second)
    (boot / migration.BOOTSTRAP / "admin_bootstrap.py").write_text("corrupt")
    migration.undo(boot)
    assert (boot / "cmdline.txt").read_bytes() == original


def test_completed_or_corrupt_request_can_use_retained_package_for_undo(migration, prepared):
    boot, package, first, second, original = prepared
    migration.stage(boot, package, first, second)
    (boot / migration.BOOTSTRAP / "request.json").unlink()
    migration.undo(boot, package)
    assert (boot / "cmdline.txt").read_bytes() == original


def test_undo_allows_staging_the_same_approved_package_again(migration, prepared):
    boot, package, first, second, _original = prepared
    migration.stage(boot, package, first, second)
    result = migration.undo(boot)
    assert Path(result["retained_payload"]).is_dir()
    migration.stage(boot, package, first, second)


def test_matching_backup_files_from_another_card_are_rejected(migration, prepared):
    _boot, _package, first, second, _original = prepared
    target = migration.verify_package(_package)["target"]
    other = bytearray(first.read_bytes())
    struct.pack_into("<I", other, 440, 0x87654321)
    first.write_bytes(other)
    second.write_bytes(other)
    with pytest.raises(ValueError, match="identity"):
        migration.verify_backups(first, second, target)


def test_unexpected_payload_files_are_rejected(migration, prepared):
    _boot, package, _first, _second, _original = prepared
    (package / "sitecustomize.py").write_text("raise RuntimeError()")
    with pytest.raises(ValueError, match="Unexpected"):
        migration.verify_package(package)


def test_fresh_image_requires_both_roles(laptop, tmp_path):
    (tmp_path / "carvera-image.json").write_text('{"format":"carvera-kiosk-pi4-v2"}')
    with pytest.raises(ValueError, match="admin-public-key"):
        laptop.prepare_card(tmp_path, "unused.pub", "pi", None, None)
