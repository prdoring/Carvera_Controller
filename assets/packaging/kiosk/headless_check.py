"""Exercise SDL Wayland, maintenance and screen sharing in a local container."""

import json
import os
import shutil
import signal
import socket
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
                print(json.dumps({"backend": "SDL Wayland", "display": status["display"],
                                  "renderer": status["renderer"], "screen_sharing": "RFB ready"}))
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
