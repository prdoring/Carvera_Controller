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
    Path(destination).write_bytes(kiosk_admin.shared_settings().prepare_archive(source))


def prepare_card(boot, public_key, hostname, ssid, country, settings=None, admin_public_keys=None):
    boot = Path(boot).resolve(strict=True)
    if not (boot / "carvera-image.json").is_file():
        raise ValueError("This volume is not an identified Carvera kiosk boot partition")
    identity = json.loads((boot / "carvera-image.json").read_text())
    if identity.get("format") not in {"carvera-kiosk-pi4-v2", "carvera-kiosk-pi4-v3"}:
        raise ValueError(
            "The card has an unexpected image identity; use a v2 image or admin-migration for an existing kiosk"
        )
    admin_keys, fingerprints = kiosk_admin.key_files(admin_public_keys)
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise ValueError("Invalid hostname")
    public_key = Path(public_key).expanduser()
    key = public_key.read_text().strip()
    kiosk_admin.account_module().key_records([key])
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
    if identity.get("format") == "carvera-kiosk-pi4-v3":
        module = kiosk_admin.shared_setup()
        value["setup_protocol"] = 1
        current = module.read_json(boot / module.RECEIPT)
        if current.get("phase") == "prepared":
            value["id"] = current.get("id")
        preferences = None
        if settings:
            with tempfile.TemporaryDirectory(prefix="kiosk-preferences-") as temporary:
                packed = Path(temporary) / "preferences.tar.gz"
                pack_settings(Path(settings).expanduser().resolve(strict=True), packed)
                preferences = packed.read_bytes()
        if preferences is not None:
            value["settings_sha256"] = hashlib.sha256(preferences).hexdigest()
        return module.prepare(boot, value, kiosk_admin.account_module().public_keys, preferences)
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


def screen(host, novnc):
    import asyncio

    if (ROOT / "kioskdesktop").is_dir():
        sys.path.insert(0, str(ROOT))
    novnc = Path(novnc).resolve()
    if not (novnc / "vnc.html").is_file() or not (novnc / "core/rfb.js").is_file():
        raise ValueError("Use --novnc with the laptop/novnc directory exported by the image build")
    ssh_args(host)
    if not host.startswith("carvera-admin@") or not IDENTITY:
        raise ValueError("Screen sharing requires --host carvera-admin@ADDRESS and an explicit --identity key")
    try:
        import asyncssh

        from kioskdesktop.viewer import Session
    except ImportError as error:
        raise ValueError("Install the supplied laptop-requirements.txt before opening the viewer") from error
    selected_key = Path(IDENTITY).expanduser()
    if selected_key.is_symlink() or not selected_key.is_file() or selected_key.stat().st_size > 65536:
        raise ValueError("Select a regular maintenance private key no larger than 64 KiB")
    data = selected_key.read_bytes()
    try:
        key = asyncssh.import_private_key(data)
    except asyncssh.KeyImportError:
        key = asyncssh.import_private_key(data, passphrase=getpass.getpass("Maintenance key passphrase: "))

    async def run_viewer():
        session = Session()
        session.connection = await asyncssh.connect(
            host.split("@", 1)[1],
            username="carvera-admin",
            config=None,
            known_hosts=str(Path.home() / ".ssh/known_hosts"),
            host_key_alias=HOST_KEY_ALIAS,
            client_keys=[key],
            agent_path=None,
            preferred_auth=("publickey",),
            agent_forwarding=False,
            connect_timeout=15,
            login_timeout=15,
            keepalive_interval=20,
            keepalive_count_max=3,
        )

        def report(value):
            if value.get("phase") == "connected":
                print("Opening the private local screen viewer. Press Ctrl+C to disconnect.", flush=True)

        await session.run(report=report, assets=novnc)

    try:
        asyncio.run(run_viewer())
    except KeyboardInterrupt:
        return {"screen_closed": True}


def transfer_file(host, name, destination=None):
    ssh_args(host)
    if destination is None:
        source = Path(name).resolve(strict=True)
        filename = source.name
    else:
        filename = name
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", filename):
        raise ValueError("Use a plain file name")
    options = scp_args(host)
    if destination is None:
        if not source.is_file() or source.stat().st_size > 512 * 1024 * 1024 or not filename.endswith(".tar.gz"):
            raise ValueError("Stage an application or preferences .tar.gz file no larger than 512 MiB")
        run(options + [source, host + ":" + transfer_path(host, "uploads") + "/" + filename])
        return {"staged": filename}
    target = Path(destination)
    if target.exists() or target.is_symlink():
        raise FileExistsError("Choose a new destination; existing backups are never overwritten")
    with tempfile.TemporaryDirectory(prefix="carvera-fetch-", dir=target.parent) as directory:
        downloaded = Path(directory) / "download"
        run(options + [host + ":" + transfer_path(host, "exports") + "/" + filename, downloaded])
        with target.open("xb") as output:
            try:
                with downloaded.open("rb") as incoming:
                    shutil.copyfileobj(incoming, output)
            except Exception:
                output.close()
                target.unlink(missing_ok=True)
                raise
    return {"saved": str(target)}


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
        "stage",
        "fetch",
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
        elif name == "stage":
            child.add_argument("source")
        elif name == "fetch":
            child.add_argument("name")
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
    elif args.action == "stage":
        result = transfer_file(args.host, args.source)
    elif args.action == "fetch":
        result = transfer_file(args.host, args.name, args.destination)
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
