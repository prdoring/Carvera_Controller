"""One explicitly connected maintenance-only screen session."""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

from kioskdesktop import transport


class Session:
    def __init__(self):
        self.connection = self.forwarder = self.worker = self.lease = None
        self.stop_requested = asyncio.Event()

    async def run(self, profile=None, passphrase=None, report=lambda _value: None, *, open_browser=True, assets=None):
        try:
            if self.stop_requested.is_set():
                return
            if self.connection is None:
                if profile.get("stage") != "verified":
                    raise ValueError("Finish first-boot verification in Setup before using Screen Share")
                self.connection = await transport.connect(profile, "maintenance", passphrase)
            if self.connection.get_extra_info("username") != "carvera-admin":
                raise ValueError("Screen Share requires the maintenance account; administrator keys are not used")
            if profile is not None:
                status = await transport.helper(self.connection, "setup-status")
                if (
                    status.get("protocol") != 1
                    or status.get("phase") != "complete"
                    or status.get("id") != profile["id"]
                    or profile["keys"]["maintenance"]["fingerprint"]
                    not in status.get("key_fingerprints", {}).get("maintenance", [])
                ):
                    raise ValueError("This kiosk does not match the verified installation profile")
            health = await transport.helper(self.connection, "health")
            if health.get("capabilities", {}).get("screen_lease_protocol") != 1:
                raise ValueError("Update the kiosk System tools: screen lease protocol 1 is required")
            result = await transport.helper(self.connection, "screen-start", {"lease_protocol": 1})
            if (
                result.get("lease_protocol") != 1
                or result.get("heartbeat_seconds") != 20
                or result.get("lease_seconds") != 90
                or not result.get("owned")
                or not re.fullmatch("[a-f0-9]{64}", str(result.get("token", "")))
                or not re.fullmatch("[a-f0-9]{32}", str(result.get("generation", "")))
            ):
                raise ValueError("The kiosk returned an unsupported screen lease")
            self.lease = {key: result[key] for key in ("token", "generation")}
            # AsyncSSH binds port zero and retains that exact listener until close.
            self.forwarder = await self.connection.forward_local_port("127.0.0.1", 0, "127.0.0.1", 5901)
            args = (
                [sys.executable, "--viewer-server"]
                if getattr(sys, "frozen", False)
                else [sys.executable, str(Path(__file__).with_name("viewer_server.py"))]
            )
            args.extend(["--target-port", str(self.forwarder.get_port())])
            if assets:
                args.extend(["--novnc", str(assets)])
            options = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
            self.worker = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=8192,
                **options,
            )
            token = secrets.token_urlsafe(32)
            self.worker.stdin.write((json.dumps({"token": token}) + "\n").encode("ascii"))
            await self.worker.stdin.drain()
            line = await asyncio.wait_for(self.worker.stdout.readline(), timeout=20)
            if len(line) > 4096:
                raise ValueError("The packaged viewer returned an invalid startup reply")
            ready = json.loads(line)
            port = ready.get("port")
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("The viewer did not provide its owned local port")
            expected_url = f"http://127.0.0.1:{port}/vnc.html?" + urlencode(
                {"autoconnect": "true", "resize": "scale", "path": "websockify?token=" + token}
            )
            if ready.get("url") != expected_url or type(ready.get("pid")) is not int or ready["pid"] <= 0:
                raise ValueError("The viewer returned an unexpected connection address")
            if getattr(sys, "frozen", False) and ready["pid"] != self.worker.pid:
                raise ValueError("The frozen screen worker has an unexpected process identity")
            report({"phase": "connected", "ports": [port, self.forwarder.get_port()]})
            if open_browser:
                webbrowser.open(ready["url"])
            while not self.stop_requested.is_set():
                try:
                    await asyncio.wait_for(self.stop_requested.wait(), timeout=20)
                except TimeoutError:
                    if self.worker.returncode is not None or self.connection.is_closed():
                        raise ConnectionError("Screen sharing disconnected")
                    reply = await transport.helper(self.connection, "screen-renew", self.lease, timeout=15)
                    if reply.get("renewed") is not True:
                        raise ConnectionError("The screen lease ended")
        finally:
            await self.close()
            report({"phase": "disconnected"})

    async def close(self):
        if self.worker:
            self.worker.stdin.close()
            try:
                await asyncio.wait_for(self.worker.wait(), timeout=8)
            except TimeoutError:
                self.worker.terminate()
                try:
                    await asyncio.wait_for(self.worker.wait(), timeout=5)
                except TimeoutError:
                    self.worker.kill()
                    await self.worker.wait()
            self.worker = None
        if self.forwarder:
            self.forwarder.close()
            await self.forwarder.wait_closed()
            self.forwarder = None
        if self.connection:
            if self.lease:
                try:
                    await transport.helper(self.connection, "screen-stop", self.lease, timeout=15)
                except Exception:
                    # Server monotonic expiry owns cleanup if the SSH connection was lost.
                    pass
            self.connection.close()
            await self.connection.wait_closed()
            self.connection = None
            self.lease = None
