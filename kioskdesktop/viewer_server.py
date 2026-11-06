"""Private noVNC HTTP/WebSocket worker; usable as a frozen or standalone entry point."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from urllib.parse import urlencode

from aiohttp import WSMsgType, web


class ViewerServer:
    def __init__(self, assets: Path, target_port: int, token: str):
        self.assets = assets.resolve(strict=True)
        if not (self.assets / "vnc.html").is_file() or not (self.assets / "core/rfb.js").is_file():
            raise ValueError("The packaged screen viewer is incomplete")
        if type(target_port) is not int or not 1 <= target_port <= 65535:
            raise ValueError("Invalid owned tunnel port")
        if not isinstance(token, str) or not token.isascii() or not 32 <= len(token) <= 128:
            raise ValueError("Invalid viewer session token")
        self.target_port, self.token = target_port, token
        self.port = None
        self.runner = None
        self.clients = set()
        self.connections = set()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self):
        query = urlencode({"autoconnect": "true", "resize": "scale", "path": "websockify?token=" + self.token})
        return self.origin + "/vnc.html?" + query

    async def start(self):
        app = web.Application(client_max_size=8 * 1024**2)
        app.router.add_get("/websockify", self.websocket)
        app.router.add_get("/{path:.*}", self.static)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await self.runner.setup()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(16)
            listener.setblocking(False)
            self.port = listener.getsockname()[1]
            await web.SockSite(self.runner, listener).start()
        except BaseException:
            listener.close()
            await self.runner.cleanup()
            raise
        return self.port

    def check_host(self, request):
        if request.headers.getall("Host", []) != [f"127.0.0.1:{self.port}"]:
            raise web.HTTPForbidden(text="Unexpected local viewer host")

    async def static(self, request):
        self.check_host(request)
        requested = request.match_info["path"] or "vnc.html"
        path = (self.assets / requested).resolve()
        if not path.is_relative_to(self.assets) or not path.is_file():
            raise web.HTTPNotFound()
        if path.suffix.lower() not in {
            ".html",
            ".js",
            ".css",
            ".png",
            ".svg",
            ".json",
            ".woff",
            ".woff2",
            ".ttf",
            ".ico",
        }:
            raise web.HTTPNotFound()
        return web.FileResponse(
            path,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    async def websocket(self, request):
        self.check_host(request)
        tokens = request.query.getall("token", [])
        if (
            request.headers.getall("Origin", []) != [self.origin]
            or len(tokens) != 1
            or not tokens[0].isascii()
            or not secrets.compare_digest(tokens[0], self.token)
        ):
            raise web.HTTPForbidden(text="Invalid viewer origin or session")
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", self.target_port), timeout=5)
        except (OSError, TimeoutError) as error:
            raise web.HTTPBadGateway(text="The owned screen tunnel is unavailable") from error
        ws = web.WebSocketResponse(protocols=("binary",), max_msg_size=8 * 1024**2, heartbeat=30)
        self.connections.add(writer)
        tasks = []
        try:
            await ws.prepare(request)
            self.clients.add(ws)

            async def from_vnc():
                while chunk := await reader.read(65536):
                    await ws.send_bytes(chunk)

            async def from_browser():
                async for message in ws:
                    if message.type == WSMsgType.BINARY:
                        writer.write(message.data)
                        await writer.drain()
                    elif message.type == WSMsgType.TEXT:
                        await ws.close(code=1003, message=b"Binary frames required")
                        return
                    elif message.type in {WSMsgType.CLOSE, WSMsgType.ERROR}:
                        return

            tasks = [asyncio.create_task(from_vnc()), asyncio.create_task(from_browser())]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.clients.discard(ws)
            self.connections.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            if ws.prepared:
                await ws.close()
        return ws

    async def close(self):
        if self.clients:
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        *(ws.close(code=1001, message=b"Viewer disconnected") for ws in tuple(self.clients)),
                        return_exceptions=True,
                    ),
                    timeout=2,
                )
            except TimeoutError:
                pass
        for writer in tuple(self.connections):
            writer.close()
        if self.runner is not None:
            await self.runner.cleanup()


def default_assets():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if (root / "novnc").is_dir():
        return root / "novnc"
    return Path(__file__).resolve().parents[1] / "dist/kiosk/laptop/novnc"


async def worker(args):
    line = await asyncio.to_thread(sys.stdin.buffer.readline, 4097)
    if len(line) > 4096:
        raise ValueError("Invalid viewer worker request")
    value = json.loads(line)
    if not isinstance(value, dict) or set(value) != {"token"}:
        raise ValueError("Invalid viewer worker request")
    server = ViewerServer(args.novnc or default_assets(), args.target_port, value["token"])
    try:
        await server.start()
        print(json.dumps({"port": server.port, "url": server.url, "pid": os.getpid()}), flush=True)
        await asyncio.to_thread(sys.stdin.buffer.read, 1)
    finally:
        await server.close()


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-port", type=int, required=True)
    parser.add_argument("--novnc", type=Path)
    args = parser.parse_args(arguments)
    asyncio.run(worker(args))


if __name__ == "__main__":
    main()
