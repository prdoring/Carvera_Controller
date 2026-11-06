"""The desktop and Pi accept the same public-key records and fingerprints."""

import shutil

import pytest

asyncssh = pytest.importorskip("asyncssh")
from kioskdesktop import profiles
from kioskdesktop.runtime import shared


@pytest.mark.skipif(not shutil.which("ssh-keygen"), reason="Development conformance check requires OpenSSH")
@pytest.mark.parametrize("algorithm", ["ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256"])
def test_real_crypto_backends_agree_on_valid_records_and_reject_malformed_ones(algorithm):
    key = asyncssh.generate_private_key(algorithm)
    public = key.export_public_key().decode().strip()
    accounts = shared("admin_accounts")
    vectors = [
        (True, [public]),
        (True, [public + " А 工作室", public + " duplicate"]),
        (False, [public + "="]),
        (False, ["no-pty " + public]),
        (False, [public + "\n" + public]),
        (False, ["ssh-ed25519 AAAA"]),
        (False, [key.export_private_key().decode()]),
        (False, [public + " " + "x" * 16384]),
    ]
    for expected, records in vectors:
        results = []
        for validate in (accounts.public_keys, profiles.public_keys):
            try:
                _keys, fingerprints = validate(records)
            except (ValueError, OSError, asyncssh.KeyImportError):
                assert not expected
                results.append(None)
            else:
                assert expected
                results.append(fingerprints)
        assert results[0] == results[1]
