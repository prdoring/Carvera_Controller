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
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import webbrowser
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kiosk_admin

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/packaging/kiosk"
IDENTITY = None
HOST_KEY_ALIAS = None


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def ssh_args(host):
    if not re.fullmatch(r"(?:[a-zA-Z0-9_][a-zA-Z0-9_-]*@)?[a-zA-Z0-9][a-zA-Z0-9.:-]*", host):
        raise ValueError("Invalid SSH host")
    arguments = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes"]
    if IDENTITY:
        arguments.extend(["-i", str(Path(IDENTITY).expanduser().resolve()), "-o", "IdentitiesOnly=yes"])
    if HOST_KEY_ALIAS:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", HOST_KEY_ALIAS):
            raise ValueError("Invalid SSH host-key alias")
        arguments.extend(["-o", "HostKeyAlias=" + HOST_KEY_ALIAS])
    return [*arguments, host]


def scp_args(host):
    return ["scp", *ssh_args(host)[1:-1]]


def transfer_path(host, kind):
    result = remote(host, "status")
    advertised = result.get("transfers", {}).get(kind)
    allowed = {f"/var/lib/carvera-maint/{kind}", f"/home/kiosk-admin/transfers/{kind}"}
    if advertised is not None and advertised not in allowed:
        raise ValueError("The helper advertised an unexpected transfer directory")
    return advertised or f"/var/lib/carvera-maint/{kind}"


def remote(host, action, value=None, confirmed=False):
    request = {"action": action, "value": value, "confirm_machine_idle": confirmed}
    result = run(
        ssh_args(host) + ["sudo -n /usr/local/sbin/carvera-maint"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def build(version, app_only=False, system_only=False):
    if not (ASSETS / "Dockerfile").is_file():
        raise ValueError("Run builds from the source checkout")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}(?:[a-zA-Z0-9.+-]*)", version):
        raise ValueError("Specify a valid release version")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        commit += "-dirty"
    image = "carvera-kiosk-builder:" + version.lower().replace("+", "-")
    arguments = [
        "docker",
        "build",
        "-t",
        image,
        "-f",
        ASSETS / "Dockerfile",
        "--build-arg",
        "KIOSK_VERSION=" + version,
        "--build-arg",
        "KIOSK_COMMIT=" + commit,
    ]
    if app_only:
        arguments.extend(["--target", "application"])
    elif system_only:
        arguments.extend(["--target", "system"])
    run([*arguments, ROOT])
    output = ROOT / "dist/kiosk"
    output.mkdir(parents=True, exist_ok=True)
    if app_only or system_only:
        container = "carvera-kiosk-export-" + uuid.uuid4().hex[:8]
        run(["docker", "create", "--name", container, image])
        try:
            name = "carvera-kiosk-" + ("system-" if system_only else "app-") + version + ".tar.gz"
            run(["docker", "cp", container + ":/output/" + name, output / name])
            manifest = "system-bundle.json" if system_only else "bundle.json"
            run(
                [
                    "docker",
                    "cp",
                    container + ":/output/" + manifest,
                    output / (manifest.removesuffix(".json") + "-" + version + ".json"),
                ]
            )
        finally:
            run(["docker", "rm", container])
        with (output / name).open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        (output / (name + ".sha256")).write_text(digest + "  " + name + "\n")
        return str(output / name)
    run(
        [
            "docker",
            "run",
            "--rm",
            "--init",
            "--privileged",
            "--name",
            "carvera-kiosk-image-" + uuid.uuid4().hex[:8],
            "--mount",
            "type=volume,src=carvera-kiosk-work,dst=/work",
            "--mount",
            "type=volume,src=carvera-kiosk-cache,dst=/cache",
            "--mount",
            f"type=bind,src={output},dst=/export",
            image,
        ]
    )
    return str(output)


def pack_settings(source, destination):
    pending = {}
    with tarfile.open(source, "r:*") as archive:
        for count, member in enumerate(archive):
            if member.name in {"system-bundle.json", "updater-bundle.json"}:
                raise ValueError("A system bundle is not a preferences backup")
            if count > 4096:
                raise ValueError("Too many entries in the settings archive")
            path = PurePosixPath(member.name)
            if (
                not member.isfile()
                or member.size > 1024 * 1024
                or path.is_absolute()
                or ".." in path.parts
                or path.suffix not in (".ini", ".json")
                or not (path.name == "makera.ini" or {".kivy", ".carveracontroller"}.intersection(path.parts))
            ):
                continue
            name = (
                "makera.ini"
                if path.name == "makera.ini"
                else ((".kivy/" if ".kivy" in path.parts else ".carveracontroller/") + path.name)
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


def prepare_card(boot, public_key, hostname, ssid, country, settings=None, admin_public_keys=None):
    boot = Path(boot).resolve(strict=True)
    if not (boot / "carvera-image.json").is_file():
        raise ValueError("This volume is not an identified Carvera kiosk boot partition")
    identity = json.loads((boot / "carvera-image.json").read_text())
    if identity.get("format") != "carvera-kiosk-pi4-v2":
        raise ValueError(
            "The card has an unexpected image identity; use a v2 image or admin-migration for an existing kiosk"
        )
    admin_keys, fingerprints = kiosk_admin.key_files(admin_public_keys)
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
    value = {
        "format": 2,
        "id": uuid.uuid4().hex,
        "hostname": hostname,
        "authorized_keys": [key],
        "admin_public_keys": admin_keys,
    }
    if ssid:
        if not re.fullmatch("[A-Z]{2}", country or ""):
            raise ValueError("Specify a two-letter Wi-Fi country with --country")
        password = getpass.getpass("Wi-Fi password: ")
        if (
            not 8 <= len(password.encode("utf-8")) <= 63
            or not 1 <= len(ssid.encode("utf-8")) <= 32
            or any(char in password + ssid for char in "\r\n\0")
        ):
            raise ValueError("Invalid WPA network name or password")
        value["wifi"] = {"ssid": ssid, "password": password, "country": country}
    if settings:
        source = Path(settings).expanduser().resolve(strict=True)
        pack_settings(source, boot / "carvera-settings.tar.gz")
    (boot / "carvera-provision.json").write_text(json.dumps(value), encoding="utf-8")
    return {
        "prepared": str(boot),
        "hostname": hostname,
        "settings": bool(settings),
        "admin_key_fingerprints": fingerprints,
    }


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
    token_directory = tempfile.TemporaryDirectory(prefix="carvera-viewer-")
    forwarded = browser = None
    try:
        forwarded, browser = unused_port(), unused_port()
        tunnel = subprocess.Popen(
            ssh_args(host)[:-1]
            + [
                "-N",
                "-o",
                "ExitOnForwardFailure=yes",
                "-L",
                f"127.0.0.1:{forwarded}:127.0.0.1:5901",
                host,
            ],
            start_new_session=os.name != "nt",
        )
        wait_port(forwarded, tunnel)
        token = secrets.token_urlsafe(32)
        token_file = Path(token_directory.name) / "tokens"
        token_file.write_text(f"{token}: 127.0.0.1:{forwarded}\n", encoding="ascii")
        token_file.chmod(0o600)
        viewer = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "websockify",
                "--web",
                str(novnc),
                "--auth-plugin=ExpectOrigin",
                f"--auth-source=http://127.0.0.1:{browser}",
                "--token-plugin=ReadOnlyTokenFile",
                "--token-source",
                str(token_file),
                f"127.0.0.1:{browser}",
            ],
            start_new_session=os.name != "nt",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_port(browser, viewer)
        query = urlencode({"autoconnect": "true", "resize": "scale", "path": "websockify?token=" + token})
        url = f"http://127.0.0.1:{browser}/vnc.html?{query}"
        print("Opening the private local screen viewer.", flush=True)
        webbrowser.open(url)
        input("Press Enter to close this screen session. ")
    finally:
        for process in (viewer, tunnel):
            if process is not None:
                stop_owned(process)
        try:
            if start.get("owned"):
                remote(host, "screen-stop", start["token"])
        finally:
            token_directory.cleanup()
            for port in (forwarded, browser):
                if port is not None:
                    for family, address in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
                        with socket.socket(family) as connection:
                            connection.settimeout(0.2)
                            if connection.connect_ex((address, port)) == 0:
                                raise RuntimeError(
                                    "A viewer port remains occupied; unrelated listeners were left alone"
                                )


def main():
    global IDENTITY, HOST_KEY_ALIAS
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--version", required=True)
    modes = build_parser.add_mutually_exclusive_group()
    modes.add_argument("--app-only", action="store_true")
    modes.add_argument("--system-only", action="store_true")
    card = sub.add_parser("prepare-card")
    card.add_argument("--boot-dir", required=True)
    card.add_argument("--public-key", required=True)
    card.add_argument("--admin-public-key", action="append", required=True)
    card.add_argument("--hostname", default="carvera-pi")
    card.add_argument("--ssid")
    card.add_argument("--country")
    card.add_argument("--settings")
    migration = sub.add_parser("admin-migration")
    migration.add_argument("operation", choices=("prepare", "stage", "undo"))
    migration.add_argument("--host")
    migration.add_argument("--identity")
    migration.add_argument("--host-key-alias")
    migration.add_argument("--admin-public-key", action="append")
    migration.add_argument("--output")
    migration.add_argument("--boot-dir")
    migration.add_argument("--package")
    migration.add_argument("--backup")
    migration.add_argument("--verification-backup")
    for name in (
        "status",
        "diagnose",
        "logs",
        "screen",
        "deploy",
        "rollback",
        "backup",
        "configure",
        "maintenance",
        "system-status",
        "system-update",
        "system-rollback",
        "system-updater-install",
    ):
        child = sub.add_parser(name)
        child.add_argument("--host", required=True)
        child.add_argument("--identity")
        child.add_argument("--host-key-alias")
        if name in {"system-update", "system-rollback", "system-updater-install"}:
            child.add_argument("--recovery", action="store_true")
            child.add_argument("--confirm-mill-disconnected", action="store_true")
            child.add_argument("--allow-screen-interruption", action="store_true")
        if name in {"system-update", "system-updater-install"}:
            child.add_argument("bundle")
            child.add_argument("--inspect", action="store_true")
        elif name == "system-status":
            child.add_argument("--job")
        if name == "screen":
            bundled = Path(__file__).resolve().parent / "novnc"
            child.add_argument(
                "--novnc", default=str(bundled if bundled.exists() else ROOT / "dist/kiosk/laptop/novnc")
            )
        elif name == "deploy":
            child.add_argument("bundle")
        elif name == "backup":
            child.add_argument("destination")
        elif name == "configure":
            child.add_argument(
                "setting", choices=("governor", "display", "network", "network-confirm", "restart", "reboot")
            )
            child.add_argument("value", nargs="?")
        elif name == "maintenance":
            child.add_argument("operation", choices=("enter", "leave"))
            child.add_argument("--confirm-machine-idle", action="store_true")
    args = parser.parse_args()
    IDENTITY, HOST_KEY_ALIAS = getattr(args, "identity", None), getattr(args, "host_key_alias", None)
    if args.action == "build":
        result = build(args.version, app_only=args.app_only, system_only=args.system_only)
    elif args.action == "prepare-card":
        result = prepare_card(
            args.boot_dir, args.public_key, args.hostname, args.ssid, args.country, args.settings, args.admin_public_key
        )
    elif args.action == "admin-migration":
        if args.operation == "prepare":
            if not args.host or not args.output:
                raise ValueError("Migration preparation requires --host and --output")
            result = kiosk_admin.prepare(ssh_args, args.host, args.admin_public_key, args.output)
        elif args.operation == "stage":
            if not all((args.boot_dir, args.package, args.backup, args.verification_backup)):
                raise ValueError("Staging requires --boot-dir, --package, --backup and --verification-backup")
            result = kiosk_admin.stage(args.boot_dir, args.package, args.backup, args.verification_backup)
        else:
            if not args.boot_dir:
                raise ValueError("Undo requires --boot-dir")
            result = kiosk_admin.undo(args.boot_dir, args.package)
    elif args.action == "system-status":
        result = kiosk_admin.system_request(run, ssh_args, args.host, "status", value=args.job)
    elif args.action in {"system-update", "system-rollback", "system-updater-install"}:
        result = kiosk_admin.system_operation(
            run,
            ssh_args,
            scp_args,
            args.host,
            {"system-update": "apply", "system-rollback": "rollback", "system-updater-install": "updater-install"}[
                args.action
            ],
            getattr(args, "bundle", None),
            inspect=getattr(args, "inspect", False),
            recovery=args.recovery,
            confirmed=args.confirm_mill_disconnected,
            allow_screen_interruption=args.allow_screen_interruption,
        )
    elif args.action == "screen":
        return screen(args.host, args.novnc)
    elif args.action == "maintenance":
        result = remote(args.host, args.operation, confirmed=args.confirm_machine_idle)
    elif args.action == "deploy":
        source = Path(args.bundle).resolve(strict=True)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", source.name):
            raise ValueError("Use a plain bundle file name")
        ssh_args(args.host)
        run([*scp_args(args.host), source, args.host + ":" + transfer_path(args.host, "uploads") + "/" + source.name])
        result = remote(args.host, "deploy", source.name)
    elif args.action == "backup":
        name = "carvera-settings-" + uuid.uuid4().hex[:8] + ".tar.gz"
        remote(args.host, "backup", name)
        if Path(args.destination).exists():
            raise ValueError("Choose a new backup destination")
        run(
            [
                *scp_args(args.host),
                args.host + ":" + transfer_path(args.host, "exports") + "/" + name,
                Path(args.destination),
            ]
        )
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
