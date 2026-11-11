"""Encrypted per-role access and saved profiles never fall back to administrator keys."""

import json
import os

import pytest

pytest.importorskip("asyncssh")

from kioskdesktop import profiles


def test_generated_keys_are_separate_encrypted_and_profile_contains_no_passphrase(tmp_path):
    import asyncssh

    path, value = profiles.create(
        "carvera-test", "private-test-passphrase", "private-test-passphrase", directory=tmp_path
    )
    assert value == profiles.load(path)
    assert value["keys"]["maintenance"]["fingerprint"] != value["keys"]["administrator"]["fingerprint"]
    assert "private-test-passphrase" not in path.read_text()
    for record in value["keys"].values():
        with pytest.raises(asyncssh.KeyImportError):
            asyncssh.read_private_key(record["path"])
        assert (
            profiles.unlock(profiles.Path(record["path"]), "private-test-passphrase").get_fingerprint()
            == record["fingerprint"]
        )
        if os.name != "nt":
            assert profiles.Path(record["path"]).stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("passphrase,confirmation", [("", ""), ("one", "two")])
def test_invalid_passphrase_does_not_create_files(tmp_path, passphrase, confirmation):
    with pytest.raises(ValueError):
        profiles.create("carvera-test", passphrase, confirmation, directory=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_new_profiles_never_overwrite_existing_keys(tmp_path):
    first, _value = profiles.create("carvera-test", "passphrase", "passphrase", directory=tmp_path)
    snapshot = {path: path.read_bytes() for path in first.parent.iterdir()}
    second, _value = profiles.create("carvera-test", "passphrase", "passphrase", directory=tmp_path)
    assert first.parent != second.parent
    assert all(path.read_bytes() == data for path, data in snapshot.items())


def test_profiles_reject_role_substitution_and_secret_fields(tmp_path):
    path, value = profiles.create("carvera-test", "passphrase", "passphrase", directory=tmp_path)
    changed = json.loads(path.read_text())
    changed["keys"]["maintenance"]["account"] = "kiosk-admin"
    with pytest.raises(ValueError, match="role"):
        profiles.validate(changed)
    with pytest.raises(ValueError, match="Unexpected"):
        profiles.validate({**value, "password": "never-store-this"})


def test_existing_unencrypted_key_is_not_rewritten(tmp_path):
    import asyncssh

    key = tmp_path / "original"
    original = asyncssh.generate_private_key("ssh-ed25519").export_private_key()
    key.write_bytes(original)
    with pytest.raises(ValueError, match="encrypted"):
        profiles.unlock(key, "passphrase")
    assert key.read_bytes() == original


def test_saved_setups_ignore_invalid_profiles_and_distinguish_duplicate_names(tmp_path):
    first, _value = profiles.create("test-pi", "passphrase", "passphrase", directory=tmp_path)
    second, _value = profiles.create("test-pi", "passphrase", "passphrase", directory=tmp_path)
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "profile.json").write_text('{"password":"private-value"}')
    found = profiles.saved(tmp_path)
    assert {path for path, _value in found} == {first, second}
    assert len({value["id"] for _path, value in found}) == 2
