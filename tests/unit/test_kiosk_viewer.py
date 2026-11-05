"""The optional viewer rejects cross-origin and tokenless browser control."""

import base64
import os
import signal
import socket
import subprocess
import sys
import time

import pytest


def handshake(port, origin, token):
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        lines = [
            f"GET /websockify?token={token} HTTP/1.1",
            f"Host: 127.0.0.1:{port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Version: 13",
            "Sec-WebSocket-Key: " + base64.b64encode(os.urandom(16)).decode(),
        ]
        if origin is not None:
            lines.append("Origin: " + origin)
        connection.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        return connection.recv(4096).split(b"\r\n", 1)[0]


def test_exact_origin_and_per_session_token(tmp_path):
    pytest.importorskip("websockify")
    with socket.socket() as target, socket.socket() as reservation:
        target.bind(("127.0.0.1", 0))
        target.listen()
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
        reservation.close()
        token = "owned-session-token"
        source = tmp_path / "tokens"
        source.write_text(f"{token}: 127.0.0.1:{target.getsockname()[1]}\n")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "websockify",
                "--auth-plugin=ExpectOrigin",
                f"--auth-source=http://127.0.0.1:{port}",
                "--token-plugin=ReadOnlyTokenFile",
                "--token-source",
                str(source),
                f"127.0.0.1:{port}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail("The viewer did not start")
                    time.sleep(0.05)
            expected = f"http://127.0.0.1:{port}"
            for origin in (
                None,
                "https://foreign.example",
                expected + ".foreign.example",
                "http://localhost:" + str(port),
            ):
                assert b"101" not in handshake(port, origin, token)
            assert b"101" not in handshake(port, expected, "wrong-token")
            assert b"101" not in handshake(port, expected, "")
            assert b"101" in handshake(port, expected, token)
        finally:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
            source.unlink()
        with socket.socket() as connection:
            assert connection.connect_ex(("127.0.0.1", port)) != 0
