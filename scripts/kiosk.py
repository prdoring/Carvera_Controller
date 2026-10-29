"""Build and maintain a Carvera kiosk. Device commands require an explicit host."""

import argparse
import configparser
import ctypes
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import time
import uuid
import webbrowser
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/packaging/kiosk"


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def ssh_args(host):
    if not re.fullmatch(r"(?:[a-zA-Z0-9_][a-zA-Z0-9_-]*@)?[a-zA-Z0-9][a-zA-Z0-9.:-]*", host):
        raise ValueError("Invalid SSH host")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes", host]


def remote(host, action, value=None, confirmed=False):
    request = {"action": action, "value": value, "confirm_machine_idle": confirmed}
    result = run(ssh_args(host) + ["sudo -n /usr/local/sbin/carvera-maint"],
                 input=json.dumps(request), text=True, capture_output=True)
    return json.loads(result.stdout)


def build(version, app_only=False):
    if not (ASSETS / "Dockerfile").is_file():
        raise ValueError("Run builds from the source checkout")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}(?:[a-zA-Z0-9.+-]*)", version):
        raise ValueError("Specify a valid release version")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        commit += "-dirty"
    image = "carvera-kiosk-builder:" + version.lower().replace("+", "-")
    arguments = ["docker", "build", "-t", image, "-f", ASSETS / "Dockerfile",
                 "--build-arg", "KIOSK_VERSION=" + version, "--build-arg", "KIOSK_COMMIT=" + commit]
    if app_only:
        arguments.extend(["--target", "application"])
    run([*arguments, ROOT])
    output = ROOT / "dist/kiosk"
    output.mkdir(parents=True, exist_ok=True)
    if app_only:
        container = "carvera-kiosk-export-" + uuid.uuid4().hex[:8]
        run(["docker", "create", "--name", container, image])
        try:
            name = "carvera-kiosk-app-" + version + ".tar.gz"
            run(["docker", "cp", container + ":/output/" + name, output / name])
            run(["docker", "cp", container + ":/output/bundle.json", output / ("bundle-" + version + ".json")])
        finally:
            run(["docker", "rm", container])
        with (output / name).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        (output / (name + ".sha256")).write_text(digest + "  " + name + "\n")
        return str(output / name)
    run(["docker", "run", "--rm", "--init", "--privileged", "--name", "carvera-kiosk-image-" + uuid.uuid4().hex[:8],
         "--mount", "type=volume,src=carvera-kiosk-work,dst=/work",
         "--mount", "type=volume,src=carvera-kiosk-cache,dst=/cache",
         "--mount", f"type=bind,src={output},dst=/export", image])
    return str(output)


def pack_settings(source, destination):
    pending = {}
    with tarfile.open(source, "r:*") as archive:
        for count, member in enumerate(archive):
            if count > 4096:
                raise ValueError("Too many entries in the settings archive")
            path = PurePosixPath(member.name)
            if (not member.isfile() or member.size > 1024 * 1024 or path.is_absolute() or ".." in path.parts
                    or path.suffix not in (".ini", ".json")
                    or not (path.name == "makera.ini" or {".kivy", ".carveracontroller"}.intersection(path.parts))):
                continue
            name = "makera.ini" if path.name == "makera.ini" else (
                (".kivy/" if ".kivy" in path.parts else ".carveracontroller/") + path.name
            )
            if name in pending:
                raise ValueError("Duplicate preference files in settings archive")
            content = archive.extractfile(member).read()
            if path.suffix == ".json":
                if not isinstance(json.loads(content), dict):
                    raise ValueError("Expected a settings object")
            else:
                configparser.ConfigParser(interpolation=None).read_string(content.decode("utf-8"))
            pending[name] = content
            if sum(map(len, pending.values())) > 16 * 1024 * 1024:
                raise ValueError("Settings exceed 16 MiB")
    if not pending:
        raise ValueError("No supported preferences found in settings archive")
    with tarfile.open(destination, "w:gz") as archive:
        for name, content in pending.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), 0o600
            archive.addfile(member, io.BytesIO(content))


def prepare_card(boot, public_key, hostname, ssid, country, settings=None):
    boot = Path(boot).resolve(strict=True)
    if not (boot / "carvera-image.json").is_file():
        raise ValueError("This volume is not an identified Carvera kiosk boot partition")
    identity = json.loads((boot / "carvera-image.json").read_text())
    if identity.get("format") != "carvera-kiosk-pi4":
        raise ValueError("The card has an unexpected image identity")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise ValueError("Invalid hostname")
    public_key = Path(public_key).expanduser()
    key = public_key.read_text().strip()
    if not re.fullmatch(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+(?: [^\r\n]*)?", key):
        raise ValueError("Select an SSH public key, not a private key")
    run(["ssh-keygen", "-l", "-f", Path(public_key).resolve()], capture_output=True)
    if os.name == "nt":
        label = ctypes.create_unicode_buffer(261)
        if not ctypes.windll.kernel32.GetVolumeInformationW(boot.anchor, label, len(label), None, None, None, None, 0):
            raise OSError("Could not read the selected volume label")
        if label.value.lower() not in ("bootfs", "boot"):
            raise ValueError("Select the flashed card's bootfs volume")
    value = {"hostname": hostname, "authorized_keys": [key]}
    if ssid:
        if not re.fullmatch("[A-Z]{2}", country or ""):
            raise ValueError("Specify a two-letter Wi-Fi country with --country")
        password = getpass.getpass("Wi-Fi password: ")
        if (not 8 <= len(password.encode("utf-8")) <= 63 or not 1 <= len(ssid.encode("utf-8")) <= 32
                or any(char in password + ssid for char in "\r\n\0")):
            raise ValueError("Invalid WPA network name or password")
        value["wifi"] = {"ssid": ssid, "password": password, "country": country}
    if settings:
        source = Path(settings).expanduser().resolve(strict=True)
        pack_settings(source, boot / "carvera-settings.tar.gz")
    (boot / "carvera-provision.json").write_text(json.dumps(value), encoding="utf-8")
    return {"prepared": str(boot), "hostname": hostname, "settings": bool(settings)}


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_port(port, process):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("The viewer helper exited")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("The viewer helper did not start")


def stop_owned(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def screen(host, novnc):
    novnc = Path(novnc).resolve()
    if not (novnc / "vnc.html").is_file():
        raise ValueError("Use --novnc with the laptop/novnc directory exported by the image build")
    try:
        import websockify  # noqa: F401
    except ImportError as error:
        raise ValueError("Install the supplied laptop-requirements.txt before opening the viewer") from error
    start = remote(host, "screen-start")
    tunnel = viewer = None
    try:
        forwarded, browser = unused_port(), unused_port()
        tunnel = subprocess.Popen(ssh_args(host)[:-1] + [
            "-N", "-o", "ExitOnForwardFailure=yes", "-L", f"127.0.0.1:{forwarded}:127.0.0.1:5900", host,
        ], start_new_session=os.name != "nt")
        wait_port(forwarded, tunnel)
        viewer = subprocess.Popen([
            sys.executable, "-m", "websockify", "--web", str(novnc),
            f"127.0.0.1:{browser}", f"127.0.0.1:{forwarded}",
        ], start_new_session=os.name != "nt")
        wait_port(browser, viewer)
        url = f"http://127.0.0.1:{browser}/vnc.html?autoconnect=true&resize=scale"
        print(url, flush=True)
        webbrowser.open(url)
        input("Press Enter to close this screen session. ")
    finally:
        for process in (viewer, tunnel):
            if process is not None:
                stop_owned(process)
        if start.get("owned"):
            remote(host, "screen-stop", start["token"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--version", required=True)
    build_parser.add_argument("--app-only", action="store_true")
    card = sub.add_parser("prepare-card")
    card.add_argument("--boot-dir", required=True)
    card.add_argument("--public-key", required=True)
    card.add_argument("--hostname", default="carvera-pi")
    card.add_argument("--ssid")
    card.add_argument("--country")
    card.add_argument("--settings")
    for name in ("status", "diagnose", "logs", "screen", "deploy", "rollback", "backup", "configure", "maintenance"):
        child = sub.add_parser(name)
        child.add_argument("--host", required=True)
        if name == "screen":
            bundled = Path(__file__).resolve().parent / "novnc"
            child.add_argument("--novnc", default=str(bundled if bundled.exists() else ROOT / "dist/kiosk/laptop/novnc"))
        elif name == "deploy":
            child.add_argument("bundle")
        elif name == "backup":
            child.add_argument("destination")
        elif name == "configure":
            child.add_argument("setting", choices=("governor", "display", "network", "network-confirm", "restart", "reboot"))
            child.add_argument("value", nargs="?")
        elif name == "maintenance":
            child.add_argument("operation", choices=("enter", "leave"))
            child.add_argument("--confirm-machine-idle", action="store_true")
    args = parser.parse_args()
    if args.action == "build":
        result = build(args.version, app_only=args.app_only)
    elif args.action == "prepare-card":
        result = prepare_card(args.boot_dir, args.public_key, args.hostname, args.ssid, args.country, args.settings)
    elif args.action == "screen":
        return screen(args.host, args.novnc)
    elif args.action == "maintenance":
        result = remote(args.host, args.operation, confirmed=args.confirm_machine_idle)
    elif args.action == "deploy":
        source = Path(args.bundle).resolve(strict=True)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", source.name):
            raise ValueError("Use a plain bundle file name")
        ssh_args(args.host)
        run(["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", source,
             args.host + ":/var/lib/carvera-maint/uploads/" + source.name])
        result = remote(args.host, "deploy", source.name)
    elif args.action == "backup":
        name = "carvera-settings.tar.gz"
        remote(args.host, "backup", name)
        run(["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
             args.host + ":/var/lib/carvera-maint/exports/" + name, Path(args.destination)])
        result = {"saved": args.destination}
    elif args.action == "configure":
        value = args.value
        if args.setting == "network":
            value = {"ssid": input("Wi-Fi network: "), "password": getpass.getpass("Wi-Fi password: ")}
        result = remote(args.host, args.setting, value)
    else:
        result = remote(args.host, args.action)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        print(error.stderr.strip() if error.stderr else str(error), file=sys.stderr)
        sys.exit(1)
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
