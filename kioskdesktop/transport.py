"""Explicit-role SSH with exact host-key pinning and bounded helper replies."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from kioskdesktop import profiles


async def probe(address: str, *, port=22):
    import asyncssh

    profiles.validate_host(address)
    key = await asyncio.wait_for(asyncssh.get_server_host_key(address, config=None, port=port), timeout=15)
    if key is None:
        raise ValueError("The kiosk did not provide an SSH host key")
    return {
        "address": address,
        "public": key.export_public_key("openssh").decode("utf-8").strip(),
        "fingerprint": key.get_fingerprint("sha256"),
    }


async def connect(profile, role: str, passphrase: str, *, port=22):
    import asyncssh

    profiles.validate(profile)
    if role not in profiles.ROLES or not profile.get("host"):
        raise ValueError("Verify this kiosk's SSH identity before connecting")
    host, record = profile["host"], profile["keys"][role]
    key = profiles.unlock(Path(record["path"]), passphrase)
    if key.get_fingerprint("sha256") != record["fingerprint"]:
        raise ValueError("The selected key does not match this access role")
    expected = asyncssh.import_public_key(host["public"].encode("utf-8"))

    class PinnedClient(asyncssh.SSHClient):
        def validate_host_public_key(self, _host, _address, _port, received):
            return received.export_public_key() == expected.export_public_key()

    return await asyncssh.connect(
        host["address"],
        port=port,
        username=profiles.ROLES[role],
        config=None,
        client_factory=PinnedClient,
        known_hosts=([expected], [], []),
        client_keys=[key],
        agent_path=None,
        preferred_auth=("publickey",),
        password=None,
        agent_forwarding=False,
        connect_timeout=15,
        login_timeout=15,
        keepalive_interval=20,
        keepalive_count_max=3,
    )


async def helper(connection, action: str, value=None, timeout=30):
    allowed = {"health", "setup-status", "screen-start", "screen-renew", "screen-stop"}
    if action not in allowed:
        raise ValueError("Unsupported desktop helper action")
    request = json.dumps({"action": action, "value": value, "confirm_machine_idle": False})
    process = await connection.create_process("sudo -n /usr/local/sbin/carvera-maint", encoding="utf-8")
    try:
        process.stdin.write(request)
        process.stdin.write_eof()
        output, error = await asyncio.wait_for(
            asyncio.gather(process.stdout.read(65537), process.stderr.read(4097)), timeout=timeout
        )
        if len(output) > 65536 or len(error) > 4096:
            raise ValueError("The kiosk helper reply exceeded its limit")
        await asyncio.wait_for(process.wait_closed(), timeout=timeout)
        if process.exit_status != 0:
            raise RuntimeError("The kiosk helper rejected the operation; check its version and session status")
        reply = json.loads(output)
        if not isinstance(reply, dict):
            raise ValueError("The kiosk helper returned an invalid response")
        return reply
    finally:
        process.close()


async def verify_first_boot(profile, passphrase: str, administrator_passphrase=None, *, port=22):
    connection = await connect(profile, "maintenance", passphrase, port=port)
    try:
        reply = await helper(connection, "setup-status")
    finally:
        connection.close()
        await connection.wait_closed()
    if reply.get("protocol") != 1 or reply.get("phase") != "complete" or reply.get("id") != profile["id"]:
        raise ValueError("The Pi has not completed this installation transaction")
    image = reply.get("image", {})
    if image.get("format") != "carvera-kiosk-pi4-v3" or image.get("commit") != profile.get("commit"):
        raise ValueError("The installed image does not match this setup profile")
    if image.get("version") != profile.get("components", {}).get("image") or reply.get("cleanup_pending"):
        raise ValueError("Image verification or setup cleanup is incomplete")
    for name in ("controller", "system", "updater"):
        actual = reply.get("components", {}).get(name, {})
        if actual.get("version") != profile.get("components", {}).get(name) or actual.get("commit") != profile.get(
            "commit"
        ):
            raise ValueError("Installed component identities do not match the selected release")
    for role in profiles.ROLES:
        if profile["keys"][role]["fingerprint"] not in reply.get("key_fingerprints", {}).get(role, []):
            raise ValueError("The installed access keys do not match this profile")
    connection = await connect(profile, "administrator", administrator_passphrase or passphrase, port=port)
    try:
        result = await connection.run("sudo -n id -u", check=True, timeout=15)
        if result.stdout.strip() != "0":
            raise ValueError("Administrator sudo verification failed")
    finally:
        connection.close()
        await connection.wait_closed()
    return reply


async def set_recovery_password(profile, passphrase: str, password: str, confirmation: str):
    if not password or password != confirmation or any(char in password for char in "\n\r\0:"):
        raise ValueError("Enter and confirm a valid local recovery password")
    connection = await connect(profile, "administrator", passphrase)
    try:
        result = await connection.run(
            "sudo -n /usr/sbin/chpasswd", input="kiosk-admin:" + password + "\n", check=False, timeout=15
        )
        if result.exit_status:
            raise ValueError("The local recovery password could not be set")
    finally:
        connection.close()
        await connection.wait_closed()
