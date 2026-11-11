"""Use a real isolated SSH server to test roles, host pinning and first boot."""

import asyncio
import json
import socket

import pytest

asyncssh = pytest.importorskip("asyncssh")

from kioskdesktop import profiles, transport


@pytest.mark.parametrize(
    "error,expected",
    [
        (asyncssh.KeyImportError("private-value"), "could not be unlocked"),
        (asyncssh.HostKeyNotVerifiable("private-value"), "identity has changed"),
        (asyncssh.PermissionDenied("private-value"), "rejected this access key"),
        (transport.InstallationError("private-value"), "did not pass its checks"),
        (TimeoutError("private-value"), "Could not reach"),
    ],
)
def test_connection_guidance_distinguishes_failures_without_disclosing_output(error, expected):
    message = transport.failure_message(error)
    assert expected in message
    assert "private-value" not in message


def test_first_boot_exact_host_account_roles_and_component_identity(tmp_path):
    _path, profile = profiles.create("kiosk-test", "test-key-passphrase", "test-key-passphrase", directory=tmp_path)
    profile.update(
        stage="prepared",
        commit="a" * 40,
        components=dict.fromkeys(("image", "controller", "system", "updater"), "1.1.0.dev5"),
    )
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    rsa_key = asyncssh.generate_private_key("ssh-rsa")
    accepted, commands, ports = [], [], []
    sudo_allowed = [True]
    status = {
        "protocol": 1,
        "phase": "complete",
        "id": profile["id"],
        "cleanup_pending": False,
        "image": {"format": "carvera-kiosk-pi4-v3", "commit": profile["commit"], "version": "1.1.0.dev5"},
        "components": {
            key: {"version": "1.1.0.dev5", "commit": profile["commit"]} for key in ("controller", "system", "updater")
        },
        "key_fingerprints": {key: [value["fingerprint"]] for key, value in profile["keys"].items()},
    }

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            accepted.append(username)
            return True

        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            role = next((role for role, account in profiles.ROLES.items() if account == username), None)
            return role and key.get_fingerprint("sha256") == profile["keys"][role]["fingerprint"]

    async def process(session):
        commands.append(session.command)
        if session.command == "sudo -n id -u":
            if not sudo_allowed[0]:
                session.exit(1)
                return
            session.stdout.write("0\n")
        elif session.command == "sudo -n /usr/local/sbin/carvera-maint":
            request = json.loads(await session.stdin.read())
            assert request["action"] == "setup-status"
            session.stdout.write(json.dumps(status))
        else:
            session.exit(1)
            return
        session.exit(0)

    async def exercise():
        server = await asyncssh.create_server(
            Server, "127.0.0.1", 0, server_host_keys=[rsa_key, host_key], process_factory=process
        )
        port = server.get_port()
        ports.append(port)
        try:
            profile["host"] = await transport.probe("127.0.0.1", port=port)
            assert profile["host"]["fingerprint"] == host_key.get_fingerprint("sha256")
            assert (await transport.verify_first_boot(profile, "test-key-passphrase", port=port))["id"] == profile["id"]
            status["components"]["system"]["commit"] = "c" * 40
            with pytest.raises(ValueError, match="component identities"):
                await transport.verify_first_boot(profile, "test-key-passphrase", port=port)
            status["components"]["system"]["commit"] = profile["commit"]
            sudo_allowed[0] = False
            with pytest.raises(transport.InstallationError, match="Administrator sudo"):
                await transport.verify_first_boot(profile, "test-key-passphrase", port=port)
            foreign = asyncssh.generate_private_key("ssh-ed25519")
            profile["host"] = {
                "address": "127.0.0.1",
                "public": foreign.export_public_key().decode().strip(),
                "fingerprint": foreign.get_fingerprint("sha256"),
            }
            with pytest.raises(asyncssh.HostKeyNotVerifiable):
                await transport.connect(profile, "maintenance", "test-key-passphrase", port=port)
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())
    assert set(accepted) == {"carvera-admin", "kiosk-admin"}
    assert commands == [
        "sudo -n /usr/local/sbin/carvera-maint",
        "sudo -n id -u",
        "sudo -n /usr/local/sbin/carvera-maint",
        "sudo -n /usr/local/sbin/carvera-maint",
        "sudo -n id -u",
    ]
    for port in ports:
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            with socket.socket(family) as probe:
                assert probe.connect_ex((address, port)) != 0
