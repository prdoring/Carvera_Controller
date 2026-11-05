"""Exercise SDL Wayland, maintenance and screen sharing in a local container."""

import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

from carveracontroller.kiosk_state import read_json, write_json

ROOT = Path(__file__).resolve().parents[3]


def wait_for(check, processes, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(process.poll() is not None for process in processes):
            raise RuntimeError("A local test process exited")
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError("Local Wayland test timed out")


def listeners():
    result = set()
    for name in ("tcp", "tcp6"):
        for line in Path("/proc/net", name).read_text().splitlines()[1:]:
            fields = line.split()
            if fields[3] == "0A":
                result.add(int(fields[1].split(":")[1], 16))
    return result


def pixel(port, x, y):
    """Read one compositor pixel using a local, unauthenticated test viewer."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as connection:
        def read(size):
            chunks, remaining = [], size
            while remaining:
                chunk = connection.recv(min(remaining, 65536))
                if not chunk:
                    raise RuntimeError("Test viewer disconnected")
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        read(12)
        connection.sendall(b"RFB 003.008\n")
        kinds = read(read(1)[0])
        if 1 not in kinds:
            raise RuntimeError("The test viewer requires the no-authentication loopback mode")
        connection.sendall(b"\x01")
        assert read(4) == b"\0\0\0\0"
        connection.sendall(b"\x01")
        header = read(24)
        read(struct.unpack(">I", header[20:24])[0])
        bits, _depth, endian, _true = header[4:8]
        red, green, blue = header[14:17]
        connection.sendall(struct.pack(">BBHi", 2, 0, 1, 0))
        connection.sendall(struct.pack(">BBHHHH", 3, 0, x, y, 1, 1))
        kind, _padding, count = struct.unpack(">BBH", read(4))
        assert kind == 0 and 1 <= count <= 128
        result = None
        for _index in range(count):
            left, top, width, height, encoding = struct.unpack(">HHHHi", read(12))
            assert encoding == 0 and width * height * bits // 8 <= 32 * 1024 * 1024
            data = read(width * height * bits // 8)
            if left <= x < left + width and top <= y < top + height:
                offset = ((y - top) * width + x - left) * bits // 8
                value = int.from_bytes(data[offset:offset + bits // 8], "big" if endian else "little")
                result = tuple((value >> shift) & 255 for shift in (red, green, blue))
        return result


def main():
    processes = []
    port = None
    with tempfile.TemporaryDirectory(prefix="carvera-wayland-") as temporary:
        base = Path(temporary)
        run, data, maintenance, config = (base / name for name in ("run", "data", "maintenance", "labwc"))
        for path in (run, data, maintenance, config):
            path.mkdir(mode=0o700)
        shutil.copy2(ROOT / "assets/packaging/kiosk/overlay/etc/carvera/labwc/rc.xml", config / "rc.xml")
        environment = dict(os.environ, HOME=str(data), XDG_RUNTIME_DIR=str(run), WLR_BACKENDS="headless",
                           WLR_RENDERER="pixman", SDL_VIDEODRIVER="wayland", LIBGL_ALWAYS_SOFTWARE="1",
                           CARVERA_PROFILE="kiosk", CARVERA_SIMULATION="1", CARVERA_DATA_DIR=str(data),
                           CARVERA_RUNTIME_DIR=str(run), CARVERA_MAINT_DIR=str(maintenance), KIVY_NO_ARGS="1",
                           KIVY_NO_CONSOLELOG="0", KIVY_WINDOW="sdl2")
        environment.pop("KIVY_NO_CONSOLELOG", None)
        with (base / "processes.log").open("w+") as log:
            def start(args):
                process = subprocess.Popen(args, env=environment, cwd=ROOT, stdout=log,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                processes.append(process)
                return process

            try:
                start(["labwc", "-C", str(config)])
                wait_for(lambda: (run / "wayland-0").exists(), processes)
                environment["WAYLAND_DISPLAY"] = "wayland-0"
                subprocess.run(["wlr-randr", "--output", "HEADLESS-1", "--custom-mode", "1920x1200@60Hz"],
                               env=environment, check=True)
                app = start(["python", "-m", "carveracontroller"])
                status = wait_for(lambda: read_json(run / "status.json"), processes, timeout=90)
                assert status["pid"] == app.pid
                assert status["display"] == [1920, 1200]
                assert not status["connected"]
                write_json(maintenance / "maintenance.request", {"token": "local-check", "confirmed_idle": True})
                wait_for(lambda: read_json(run / "status.json").get("maintenance"), processes, timeout=10)
                (maintenance / "maintenance.request").unlink()
                wait_for(lambda: not read_json(run / "status.json").get("maintenance", True), processes, timeout=5)
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                start(["wayvnc", "127.0.0.1", str(port)])
                wait_for(lambda: port in listeners(), processes)
                with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
                    assert connection.recv(12).startswith(b"RFB ")
                code = """
import sys
from pathlib import Path
sys.path[:0] = [str(Path.cwd() / 'assets/packaging/kiosk/runtime'), str(Path.cwd() / 'carveracontroller')]
import recovery
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
recovery.call_helper = lambda request: {}
class System(recovery.Recovery):
    def build(self):
        root = super().build()
        with root.canvas.after:
            Color(0, 1, 0, 1)
            Rectangle(pos=(20, 20), size=(30, 30))
        Clock.schedule_once(lambda dt: Path(sys.argv[1]).write_text('ready'), .5)
        return root
System().run()
"""
                program = base / "system-check.py"
                program.write_text(code)
                system = start(["python", str(program), str(base / "system.ready")])
                wait_for(lambda: (base / "system.ready").exists(), processes)
                wait_for(lambda: pixel(port, 35, 1165) == (0, 255, 0), processes)
                os.killpg(app.pid, signal.SIGTERM)
                try:
                    app.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(app.pid, signal.SIGKILL)
                    app.wait(timeout=5)
                processes.remove(app)
                (run / "status.json").unlink(missing_ok=True)
                app = start(["python", "-m", "carveracontroller"])
                wait_for(lambda: read_json(run / "status.json").get("pid") == app.pid, processes, timeout=90)
                assert system.poll() is None
                assert pixel(port, 35, 1165) == (0, 255, 0), "Restarted controller covered System settings"
                print(json.dumps({"backend": "SDL Wayland", "display": status["display"],
                                  "renderer": status["renderer"], "screen_sharing": "RFB ready",
                                  "system": "remains visible across controller restart"}))
            except Exception:
                log.flush()
                print((base / "processes.log").read_text(errors="replace")[-6000:])
                for path in data.rglob("kivy_*.txt"):
                    print(path.read_text(errors="replace")[-6000:])
                raise
            finally:
                for process in reversed(processes):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                remaining = listeners()
                if port is not None and port in remaining:
                    raise RuntimeError("A test screen-sharing listener is still running")
                print("Local test processes stopped; IPv4 and IPv6 listeners checked.")


if __name__ == "__main__":
    main()
