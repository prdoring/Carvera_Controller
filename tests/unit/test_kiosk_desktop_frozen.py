"""Exercise the packaged worker entry point, its real sockets and forced cleanup."""

import asyncio
import json
import os
import socket
from urllib.parse import parse_qs, urlsplit

import pytest

aiohttp = pytest.importorskip("aiohttp")
EXECUTABLE = os.environ.get("CARVERA_DESKTOP_EXE")


@pytest.mark.skipif(not EXECUTABLE, reason="Set CARVERA_DESKTOP_EXE to a native frozen distribution")
@pytest.mark.parametrize("force,keep_open", [(False, False), (True, False), (False, True)])
def test_actual_frozen_server_origin_token_bridge_and_listener_cleanup(force, keep_open):
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
        ports.append(target_port)
        options = {"creationflags": 0x08000000} if os.name == "nt" else {}
        process = await asyncio.create_subprocess_exec(
            EXECUTABLE,
            "--viewer-server",
            "--target-port",
            str(target_port),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=8192,
            **options,
        )
        token = "owned-test-token-" + "a" * 32
        try:
            process.stdin.write((json.dumps({"token": token}) + "\n").encode())
            await process.stdin.drain()
            line = await asyncio.wait_for(process.stdout.readline(), timeout=20)
            ready = json.loads(line)
            assert ready["pid"] == process.pid
            ports.append(ready["port"])
            parsed = urlsplit(ready["url"])
            assert parsed.hostname == "127.0.0.1" and parsed.port == ready["port"]
            assert parse_qs(parsed.query)["path"] == ["websockify?token=" + token]
            origin = f"http://127.0.0.1:{ready['port']}"
            async with aiohttp.ClientSession() as client:
                async with client.get(origin + "/vnc.html") as response:
                    assert response.status == 200 and "noVNC" in await response.text()
                async with client.get(origin + "/defaults.json") as response:
                    assert response.status == 200 and (await response.json())["show_dot"] is True
                async with client.get(origin + "/vendor/pako/lib/utils/common.js") as response:
                    assert response.status == 200
                    assert response.content_type in {"text/javascript", "application/javascript"}
                for headers, query in (
                    ({}, token),
                    ({"Origin": "https://foreign.example"}, token),
                    ({"Origin": origin}, "wrong"),
                ):
                    with pytest.raises(aiohttp.WSServerHandshakeError) as failure:
                        await client.ws_connect(origin + "/websockify", params={"token": query}, headers=headers)
                    assert failure.value.status == 403
                async with client.ws_connect(
                    origin + "/websockify", params={"token": token}, headers={"Origin": origin}, protocols=("binary",)
                ) as connection:
                    await connection.send_bytes(b"frozen-owned-rfb-data")
                    assert (await connection.receive(timeout=5)).data == b"frozen-owned-rfb-data"
                    if keep_open:
                        process.stdin.close()
                        await asyncio.wait_for(process.wait(), timeout=8)
                        assert process.returncode == 0
            if force:
                process.kill()
            elif not keep_open:
                process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=10)
            if not force:
                assert process.returncode == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            target.close()
            await target.wait_closed()

    asyncio.run(exercise())
    for port in ports:
        for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
            with socket.socket(family) as connection:
                connection.settimeout(0.2)
                assert connection.connect_ex((address, port)) != 0
