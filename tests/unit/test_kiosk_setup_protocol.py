"""Desktop retries and public receipts must not replace partially applied setup."""

import hashlib
import json

import pytest

from kioskdesktop.runtime import shared


@pytest.fixture
def protocol():
    return shared("setup_protocol")


@pytest.fixture
def card(tmp_path, protocol):
    (tmp_path / "carvera-image.json").write_text(json.dumps({"format": protocol.IMAGE_FORMAT, "setup_protocol": 1}))
    protocol.write_json(tmp_path / protocol.RECEIPT, protocol.receipt("fresh"))
    return tmp_path


def request():
    return {
        "format": 2,
        "setup_protocol": 1,
        "id": "a" * 32,
        "hostname": "carvera-pi",
        "authorized_keys": ["ssh-ed25519 YWJj"],
        "admin_public_keys": ["ssh-ed25519 YWJj"],
        "wifi": {"ssid": "Workshop", "password": "private-test-value", "country": "US"},
    }


def test_preparation_is_repeatable_and_receipt_has_no_password_digest(card, protocol):
    value = request()
    verify = lambda keys: keys
    assert protocol.prepare(card, value, verify) == protocol.prepare(card, value, verify)
    public = protocol.read_json(card / protocol.RECEIPT)
    assert public == {"protocol": 1, "phase": "prepared", "id": value["id"]}
    assert protocol.identity(value)[1] not in json.dumps(public)


@pytest.mark.parametrize("phase", ["applying", "complete", "unknown"])
def test_nonfresh_card_never_accepts_offline_reconfiguration(card, protocol, phase):
    protocol.write_json(card / protocol.RECEIPT, {"protocol": 1, "phase": phase, "id": "a" * 32})
    with pytest.raises(ValueError, match="cannot accept"):
        protocol.prepare(card, request(), lambda keys: keys)
    assert not (card / protocol.REQUEST).exists()


def test_prepared_retry_cannot_change_id_keys_or_wifi(card, protocol):
    original = request()
    protocol.prepare(card, original, lambda keys: keys)
    for changed in (
        {**original, "id": "b" * 32},
        {**original, "admin_public_keys": ["ssh-ed25519 ZGVm"]},
        {**original, "wifi": {**original["wifi"], "password": "other-password"}},
    ):
        with pytest.raises(ValueError):
            protocol.prepare(card, changed, lambda keys: keys)
    assert protocol.read_json(card / protocol.REQUEST) == original


def test_settings_bytes_are_bound_to_request(card, protocol):
    value = {**request(), "settings_sha256": hashlib.sha256(b"preferences").hexdigest()}
    with pytest.raises(ValueError, match="Preferences"):
        protocol.prepare(card, value, lambda keys: keys, b"changed")
    protocol.prepare(card, value, lambda keys: keys, b"preferences")
    assert (card / protocol.SETTINGS).read_bytes() == b"preferences"
    (card / protocol.SETTINGS).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        protocol.prepare(card, value, lambda keys: keys)


def test_validation_finishes_before_card_writes(card, protocol):
    value = {**request(), "wifi": {"ssid": "Workshop", "password": "short", "country": "US"}}
    with pytest.raises(ValueError):
        protocol.prepare(card, value, lambda keys: keys)
    assert protocol.read_json(card / protocol.RECEIPT)["phase"] == "fresh"
    assert not (card / protocol.REQUEST).exists()


def test_missing_receipt_is_not_assumed_fresh(card, protocol):
    (card / protocol.RECEIPT).unlink()
    with pytest.raises(FileNotFoundError):
        protocol.prepare(card, request(), lambda keys: keys)


def test_shared_public_key_boundaries_have_no_external_dependency():
    accounts = shared("admin_accounts")
    for invalid in (["command=evil ssh-ed25519 YWJj"], ["ssh-ed25519 YWJj\nssh-ed25519 YWJj"], ["PRIVATE KEY"], []):
        with pytest.raises(ValueError):
            accounts.public_keys(invalid, verify=lambda value: "SHA256:known")
    keys, fingerprints = accounts.public_keys(
        ["ssh-ed25519 YWJj one", "ssh-ed25519 YWJj two"], verify=lambda value: "SHA256:known"
    )
    assert keys == ["ssh-ed25519 YWJj one"] and fingerprints == ["SHA256:known"]
