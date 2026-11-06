"""Storage growth retries preserve partition identity at each crash boundary."""

import importlib.util
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def growth(monkeypatch, tmp_path):
    source = Path(__file__).resolve().parents[2] / "assets/packaging/kiosk/firstboot/grow_root.py"
    spec = importlib.util.spec_from_file_location("kiosk_grow_root", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "BOOT", tmp_path / "boot")
    monkeypatch.setattr(module, "STATE", tmp_path / "state")
    module.BOOT.mkdir()
    module.STATE.mkdir()
    (module.BOOT / "carvera-image.json").write_text(json.dumps({"format": "carvera-kiosk-pi4-v3"}))
    target = {
        "disk": "/dev/test-card",
        "root": "/dev/test-card2",
        "signature": "12345678",
        "filesystem": "root-uuid",
        "root_start": 2048,
        "root_size": 4096,
        "capacity": 65536,
    }
    monkeypatch.setattr(module, "discover", lambda: dict(target))
    calls = []

    def command(*args, **_kwargs):
        calls.append(args)
        if args[0] == "growpart":
            unchanged = target["root_size"] == target["capacity"] - target["root_start"]
            target["root_size"] = target["capacity"] - target["root_start"]
            return SimpleNamespace(returncode=1 if unchanged else 0)
        return SimpleNamespace(returncode=0)

    def save(value):
        (module.STATE / "root-grow.json").write_text(json.dumps(value))

    monkeypatch.setattr(module, "command", command)
    monkeypatch.setattr(module, "save", save)
    monkeypatch.setattr(
        module.os,
        "statvfs",
        lambda _path: SimpleNamespace(f_bavail=1024**2, f_frsize=4096, f_blocks=2 * 1024**2),
        raising=False,
    )
    return module, target, calls


@pytest.mark.parametrize("boundary", ["growpart", "resize2fs", "complete"])
def test_interrupted_growth_retries_without_recreating_or_shrinking_partitions(growth, monkeypatch, boundary):
    module, target, calls = growth
    command, save = module.command, module.save
    failed = False

    def interrupted(*args, **kwargs):
        nonlocal failed
        result = command(*args, **kwargs)
        if args[0] == boundary and not failed:
            failed = True
            raise OSError("injected power loss after the disk operation")
        return result

    def interrupted_save(value):
        nonlocal failed
        if value["phase"] == boundary and not failed:
            failed = True
            raise OSError("injected power loss before completion")
        save(value)

    monkeypatch.setattr(module, "command", interrupted)
    monkeypatch.setattr(module, "save", interrupted_save)
    with pytest.raises(OSError):
        module.grow()
    assert module.read(module.STATE / "root-grow.json")["phase"] != "complete"
    module.grow()
    assert module.read(module.STATE / "root-grow.json")["phase"] == "complete"
    assert target["root_start"] == 2048 and target["root_size"] == target["capacity"] - 2048
    count = len(calls)
    module.grow()
    assert len(calls) == count


def test_a_different_root_identity_is_never_resumed(growth):
    module, target, calls = growth
    module.grow()
    target["filesystem"] = "another-root"
    calls.clear()
    with pytest.raises(ValueError, match="another filesystem"):
        module.grow()
    assert not calls


def test_growth_rejects_extra_partitions_and_changed_starts(growth):
    module, _target, _calls = growth
    mbr = bytearray(512)
    mbr[510:] = b"\x55\xaa"
    for index, (kind, start, size) in enumerate(((0xC, 2048, 4096), (0x83, 6144, 8192))):
        mbr[446 + index * 16 + 4] = kind
        struct.pack_into("<II", mbr, 446 + index * 16 + 8, start, size)
    values = {"boot_start": 2048, "boot_size": 4096, "root_start": 6144, "root_size": 8192, "capacity": 65536}
    module.validate_layout(bytes(mbr), **values)
    with pytest.raises(ValueError):
        module.validate_layout(bytes(mbr), **{**values, "root_start": 6145})
    struct.pack_into("<II", mbr, 446 + 2 * 16 + 8, 14336, 1024)
    with pytest.raises(ValueError):
        module.validate_layout(bytes(mbr), **values)
