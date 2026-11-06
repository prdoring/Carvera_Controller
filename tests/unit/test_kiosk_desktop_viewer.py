"""Exercise the actual private viewer with exact Origin/token and retained port-zero sockets."""

import asyncio
import socket

import pytest

aiohttp = pytest.importorskip("aiohttp")

from kioskdesktop.viewer_server import ViewerServer


def test_viewer_failure_closes_only_its_matching_remote_lease(monkeypatch):
    from kioskdesktop import viewer

    requests, closed = [], []
    lease = {"token": "a" * 64, "generation": "b" * 32}

    class Connection:
        def get_extra_info(self, name):
            assert name == "username"
            return "carvera-admin"

        async def forward_local_port(self, address, port, destination, remote_port):
            assert (address, port, destination, remote_port) == ("127.0.0.1", 0, "127.0.0.1", 5901)
            raise RuntimeError("injected forwarding failure")

        def close(self):
            closed.append(True)

        async def wait_closed(self):
            pass

    async def helper(_connection, action, value=None, **_kwargs):
        requests.append((action, value))
        if action == "health":
            return {"capabilities": {"screen_lease_protocol": 1}}
        if action == "screen-start":
            return {"owned": True, "lease_protocol": 1, "heartbeat_seconds": 20, "lease_seconds": 90, **lease}
        assert action == "screen-stop" and value == lease
        return {"screen_stopped": True}

    monkeypatch.setattr(viewer.transport, "helper", helper)

    async def exercise():
        session = viewer.Session()
        session.connection = Connection()
        with pytest.raises(RuntimeError, match="forwarding failure"):
            await session.run(open_browser=False)

    asyncio.run(exercise())
    assert closed == [True]
    assert requests == [("health", None), ("screen-start", {"lease_protocol": 1}), ("screen-stop", lease)]


def test_viewer_binary_bridge_origin_token_static_paths_and_cleanup(tmp_path):
    (tmp_path / "core").mkdir()
    (tmp_path / "vnc.html").write_text("owned viewer")
    (tmp_path / "core/rfb.js").write_text("// fixture")
    outside = tmp_path.parent / "outside-private.txt"
    outside.write_text("must not be served")
    ports = []

    async def exercise():
        async def echo(reader, writer):
            try:
                while data := await reader.read(65536):
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        target = await asyncio.start_server(echo, "127.0.0.1", 0)
        target_port = target.sockets[0].getsockname()[1]
        server = ViewerServer(tmp_path, target_port, "owned-session-" + "a" * 32)
        try:
            await server.start()
            ports.extend([target_port, server.port])
            async with aiohttp.ClientSession() as client:
                async with client.get(server.origin + "/vnc.html") as response:
                    assert response.status == 200 and await response.text() == "owned viewer"
                async with client.get(server.origin + "/vnc.html", headers={"Host": "foreign.example"}) as response:
                    assert response.status == 403
                async with client.get(server.origin + "/../outside-private.txt") as response:
                    assert response.status == 404
                for origin, token in (
                    (None, server.token),
                    ("https://foreign.example", server.token),
                    (server.origin + ".foreign.example", server.token),
                    (server.origin, "wrong"),
                    (server.origin, ""),
                ):
                    headers = {"Origin": origin} if origin is not None else {}
                    with pytest.raises(aiohttp.WSServerHandshakeError) as rejected:
                        await client.ws_connect(server.origin + "/websockify", params={"token": token}, headers=headers)
                    assert rejected.value.status == 403
                async with client.ws_connect(
                    server.origin + "/websockify",
                    params={"token": server.token},
                    headers={"Origin": server.origin},
                    protocols=("binary",),
                ) as ws:
                    await ws.send_bytes(b"owned-rfb-traffic")
                    message = await ws.receive(timeout=3)
                    assert message.type == aiohttp.WSMsgType.BINARY and message.data == b"owned-rfb-traffic"
        finally:
            await server.close()
            target.close()
            await target.wait_closed()

    asyncio.run(exercise())
    for port in ports:
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            with socket.socket(family) as probe:
                probe.settimeout(0.1)
                assert probe.connect_ex((address, port)) != 0
