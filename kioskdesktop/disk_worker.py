"""Fixed-operation elevated worker. No caller-selected write paths or commands."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from kioskdesktop import devices, disk_ops, elevation, ipc, profiles
from kioskdesktop.releases import Release, verify_image
from kioskdesktop.runtime import shared

IMAGER_VERSION = "2.0.12"
IMAGER_COMMIT = "84b03d96cd4c390ebe475a4b5db5735e5535e9a6"
IMAGER_WINDOWS_PATCH = "20f707049a4736604aa3d8f63beb914ac3e58088984b6c1f209d10acc01f6008"
IMAGER_DEPENDENCIES = {
    "curl": "a05f34973e6c4bb629d018f7cb51487be1c904d8",
    "libarchive": "ded82291ab41d5e355831b96b0e1ff49e24d8939",
    "libusb": "87a55632db62c9bdc58cd31d3ccfa673f1bb017f",
    "nghttp2": "68cb6900fde14c77f0cd7add0e094a862960eb99",
    "xz": "4b73f2ec19a99ef465282fbce633e8deb33691b3",
    "zlib": "da607da739fa6047df13e66a2af6b8bec7c2a498",
    "zstd": "f8745da6ff1ad1e7bab384bd1f9d742439278e99",
}


def writer_progress(data):
    matches = list(re.finditer(rb"(Writing|Verifying):\s*\[[^\]\r\n]{0,32}\]\s*(\d{1,3})\s*%", data))
    if not matches:
        return None
    match = matches[-1]
    return {"phase": "verifying_write" if match[1] == b"Verifying" else "writing", "percent": min(100, int(match[2]))}


def validate_job(value):
    fields = {
        "protocol",
        "action",
        "device",
        "release",
        "configuration",
        "expected_digest",
        "settings_size",
        "protected_paths",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("protocol") != 1:
        raise ValueError("Invalid card-worker request")
    if value["action"] not in {"flash", "configure", "resume"}:
        raise ValueError("Unsupported card operation")
    selected = value["device"]
    if (
        not isinstance(selected, dict)
        or set(selected) != {"path", "identity"}
        or not isinstance(selected["path"], str)
        or not isinstance(selected["identity"], str)
        or not re.fullmatch("[a-f0-9]{64}", selected["identity"])
    ):
        raise ValueError("Invalid physical-device identity")
    if not isinstance(value["expected_digest"], str) or not re.fullmatch("[a-f0-9]{64}", value["expected_digest"]):
        raise ValueError("The original private transaction identity is required")
    if (
        type(value["settings_size"]) is not int
        or not 0 <= value["settings_size"] <= shared("setup_protocol").MAX_SETTINGS
    ):
        raise ValueError("Invalid preferences payload length")
    paths = value["protected_paths"]
    if (
        not isinstance(paths, list)
        or len(paths) > 32
        or any(not isinstance(path, str) or len(path) > 32768 for path in paths)
    ):
        raise ValueError("Invalid protected source locations")
    release = Release.parse(value["release"])
    configuration = shared("setup_protocol").validate_request(value["configuration"], profiles.public_keys)
    if shared("setup_protocol").identity(configuration)[1] != value["expected_digest"]:
        raise ValueError("The setup configuration changed")
    if value["action"] == "resume" and value["settings_size"]:
        raise ValueError("A prepared retry must reuse the original on-card preferences")
    if value["action"] != "resume" and bool(configuration.get("settings_sha256")) != bool(value["settings_size"]):
        raise ValueError("The preferences payload does not match the transaction")
    return release


def copy_payload(channel, target, length):
    with target.open("xb") as destination:
        remaining = length
        while remaining:
            chunk = channel.read(min(remaining, 1024**2))
            if not chunk:
                raise InterruptedError("The setup application disconnected before staging finished")
            destination.write(chunk)
            remaining -= len(chunk)
        destination.flush()
        os.fsync(destination.fileno())


def confirm_media(channel, selected, proof, action):
    """Consent is given while the worker holds this exact medium, never by an old drive letter."""
    token = secrets.token_hex(32)
    channel.send(
        {
            "phase": "awaiting_confirmation",
            "device": selected.public(),
            "confirmation": token,
            "erases": action == "flash",
        }
    )
    deadline = time.monotonic() + 300
    while not channel.readable():
        if not channel.alive() or time.monotonic() > deadline:
            raise InterruptedError("Card confirmation expired or was cancelled")
        proof.check()
        time.sleep(0.1)
    value = channel.receive()
    if value != {"confirm": token}:
        raise ValueError("The physical card confirmation did not match this operation")
    proof.check()


def stage_writer(destination):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    source, packed = root / "writer", root / "writer.zip"
    with contextlib.ExitStack() as stack:
        archive = None
        if packed.exists():
            if packed.is_symlink() or not packed.is_file() or packed.stat().st_size > 256 * 1024**2:
                raise ValueError("Invalid packaged writer archive")
            # Bound the central directory before ZipFile allocates its entry objects.
            with packed.open("rb") as stream:
                stream.seek(max(0, packed.stat().st_size - 65557))
                tail = stream.read()
            position = tail.rfind(b"PK\x05\x06")
            if position < 0 or len(tail) - position < 22:
                raise ValueError("Invalid writer archive directory")
            disk, directory_disk, count, total, size, offset, comment = struct.unpack_from("<4H2IH", tail, position + 4)
            absolute = packed.stat().st_size - len(tail) + position
            if (
                disk
                or directory_disk
                or count != total
                or not 1 <= total <= 513
                or size > 256 * 1024
                or offset + size != absolute
                or position + 22 + comment != len(tail)
            ):
                raise ValueError("The writer archive exceeds its directory limits")
            archive = stack.enter_context(zipfile.ZipFile(packed))
            if len({item.filename for item in archive.infolist()}) != len(archive.infolist()):
                raise ValueError("Duplicate writer archive entry")

        def member_size(name):
            if archive:
                info = archive.getinfo(name)
                if info.is_dir() or (info.external_attr >> 16) & 0o170000 not in {0, 0o100000}:
                    raise ValueError("Writer archive members must be regular files")
                return info.file_size
            path = source / name
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source.resolve()):
                raise ValueError("Invalid packaged writer file")
            return path.stat().st_size

        def open_member(name):
            return archive.open(name) if archive else (source / name).open("rb")

        if member_size("writer-manifest.json") > 256 * 1024:
            raise ValueError("The packaged writer manifest is oversized")
        with open_member("writer-manifest.json") as incoming:
            value = json.loads(incoming.read(256 * 1024 + 1))
        if (
            value.get("format") != 1
            or value.get("version") != IMAGER_VERSION
            or value.get("commit") != IMAGER_COMMIT
            or value.get("telemetry") is not False
            or value.get("cli_only") is not True
            or value.get("dependencies") != IMAGER_DEPENDENCIES
            or value.get("patches") != ({"imager-cli-windows.patch": IMAGER_WINDOWS_PATCH} if os.name == "nt" else {})
        ):
            raise ValueError("The packaged image writer has an unsupported identity")
        files = value.get("sha256")
        executable = "rpi-imager.exe" if os.name == "nt" else "rpi-imager"
        if not isinstance(files, dict) or not 1 <= len(files) <= 512 or executable not in files:
            raise ValueError("The packaged image writer is incomplete")
        if archive and set(archive.namelist()) != {"writer-manifest.json", *files}:
            raise ValueError("Unexpected writer archive contents")
        if os.name == "nt" and len({name.lower() for name in files}) != len(files):
            raise ValueError("Ambiguous Windows writer filenames")
        destination.mkdir(mode=0o700)
        total = 0
        for name, expected in files.items():
            path = PurePosixPath(name)
            if (
                path.as_posix() != name
                or len(path.parts) > 3
                or not path.parts
                or any(not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*", part) for part in path.parts)
                or any(
                    part.split(".")[0].upper()
                    in {
                        "CON",
                        "PRN",
                        "AUX",
                        "NUL",
                        *("COM" + str(n) for n in range(1, 10)),
                        *("LPT" + str(n) for n in range(1, 10)),
                    }
                    for part in path.parts
                )
                or not isinstance(expected, str)
                or not re.fullmatch("[a-f0-9]{64}", expected)
            ):
                raise ValueError("Invalid writer payload path or checksum")
            length = member_size(name)
            total += length
            if total > 256 * 1024**2:
                raise ValueError("The writer payload exceeds its size limit")
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with open_member(name) as incoming, target.open("xb") as outgoing:
                remaining = length
                while remaining:
                    data = incoming.read(min(remaining, 1024**2))
                    if not data:
                        raise ValueError("The writer payload is truncated")
                    outgoing.write(data)
                    digest.update(data)
                    remaining -= len(data)
                if incoming.read(1):
                    raise ValueError("The writer payload changed size")
            if digest.hexdigest() != expected:
                raise ValueError("The packaged image writer checksum changed")
            target.chmod(0o700 if name == executable else 0o600)
        return destination / executable


def writer_environment():
    if os.name == "nt":
        directory = disk_ops.devices.windows_system_directory()
        return {
            "SystemRoot": str(directory.parent),
            "WINDIR": str(directory.parent),
            "PATH": str(directory),
            "QT_PLUGIN_PATH": "",
            "QT_LOGGING_RULES": "*.debug=false",
        }
    return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C", "QT_LOGGING_RULES": "*.debug=false"}


def parent_death_signal():
    import ctypes

    parent = os.getppid()
    libc = ctypes.CDLL(None)
    if libc.prctl(1, signal.SIGTERM) != 0 or os.getppid() != parent:
        os._exit(1)


def run_writer(executable, image, selected, image_file, proof, channel):
    arguments = [str(executable), "--disable-eject", "--sha256", image.raw_sha256, str(image_file), selected.path]
    options = (
        {"creationflags": subprocess.CREATE_NO_WINDOW}
        if os.name == "nt"
        else {"start_new_session": True, "preexec_fn": parent_death_signal}
    )
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=writer_environment(),
        **options,
    )
    messages = queue.Queue(maxsize=32)

    def read_progress():
        buffer = b""
        while block := process.stdout.read1(4096):
            buffer = (buffer + block)[-8192:]
            value = writer_progress(buffer)
            if value:
                try:
                    messages.put_nowait(value)
                except queue.Full:
                    pass
                buffer = b""

    reader = threading.Thread(target=read_progress, name="owned-writer-output", daemon=True)
    reader.start()
    started = time.monotonic()
    try:
        channel.send({"phase": "writing", "percent": 0})
        while process.poll() is None:
            if not channel.alive():
                raise InterruptedError("The setup application disconnected during writing")
            proof.check()
            if time.monotonic() - started > 7200:
                raise TimeoutError("Card writing exceeded its time limit")
            try:
                channel.send(messages.get(timeout=0.2))
            except queue.Empty:
                pass
        reader.join(5)
        if process.returncode:
            raise OSError("Card writing or read-back verification failed; the card is incomplete")
    finally:
        if process.poll() is None:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        process.stdout.close()
        reader.join(5)


def execute(channel, job, *, owner_home=None):
    release = validate_job(job)
    protected_paths = [*job["protected_paths"], *([owner_home] if owner_home is not None else [])]
    selected = devices.select(job["device"]["path"], job["device"]["identity"], protected_paths)
    if selected.capacity < release.image.minimum_capacity:
        raise ValueError("The selected card is too small for this image")
    protocol = shared("setup_protocol")
    configuration = job["configuration"]
    with disk_ops.disk_lock(selected), disk_ops.MediaProof(selected) as proof, disk_ops.private_stage() as stage:
        needed = (release.image.size if job["action"] == "flash" else 0) + job["settings_size"] + 320 * 1024**2
        if shutil.disk_usage(stage).free < needed:
            raise ValueError("Not enough administrator staging space; no card data was changed")
        image_file, preferences = stage / "image.img.xz", stage / "preferences.tar.gz"
        channel.send({"phase": "staging"})
        if job["action"] == "flash":
            copy_payload(channel, image_file, release.image.size)
        if job["settings_size"]:
            copy_payload(channel, preferences, job["settings_size"])
            if hashlib.sha256(preferences.read_bytes()).hexdigest() != configuration.get("settings_sha256"):
                raise ValueError("Preferences changed while being transferred")
            with preferences.open("rb") as incoming:
                shared("settings").validated_snapshot(incoming)
        if job["action"] == "flash":
            channel.send({"phase": "verifying_image", "bytes": 0, "total": release.image.raw_size})
            with image_file.open("rb") as source:
                layout = verify_image(
                    source,
                    release.image,
                    cancelled=lambda: not channel.alive(),
                    progress=lambda count: channel.send(
                        {"phase": "verifying_image", "bytes": count, "total": release.image.raw_size}
                    ),
                )
            executable = stage_writer(stage / "writer")
            selected = devices.select(selected.path, selected.identity, protected_paths)
            proof.check()
            confirm_media(channel, selected, proof, job["action"])
            run_writer(executable, release.image, selected, image_file, proof, channel)
            selected = disk_ops.refresh(selected, proof, protected_paths)
        else:
            layout = disk_ops.read_layout(selected)
            confirm_media(channel, selected, proof, job["action"])
        proof.check()
        channel.send({"phase": "configuring"})
        with disk_ops.mounted_boot(selected, layout, proof) as boot:
            identity = protocol.read_json(boot / "carvera-image.json")
            if (
                identity.get("format") != protocol.IMAGE_FORMAT
                or identity.get("version") != release.components["image"]
                or identity.get("commit") != release.commit
            ):
                raise ValueError("The flashed card does not match the selected release")
            if job["action"] == "resume":
                existing = protocol.read_json(boot / protocol.REQUEST)
                if protocol.identity(existing)[1] != job["expected_digest"]:
                    raise ValueError("The on-card request does not match the original private transaction")
                if existing != configuration:
                    raise ValueError("The prepared card belongs to a different setup transaction")
                configuration = existing
            result = protocol.prepare(
                boot, configuration, profiles.public_keys, preferences.read_bytes() if job["settings_size"] else None
            )
            proof.check()
        channel.send({"phase": "ejecting"})
        disk_ops.eject(selected, proof)
    channel.send({"phase": "complete", "id": result["id"]})


def main(arguments):
    if not elevation.elevated() or len(arguments) != 3:
        raise SystemExit("Use the setup application's administrator permission prompt")
    address, nonce, raw_pid = arguments
    if not raw_pid.isdigit() or not 1 <= int(raw_pid) <= 0xFFFFFFFF:
        raise SystemExit("Invalid setup process")
    from kioskdesktop.owned_jobs import contain_worker

    contain_worker()
    channel = ipc.worker_connection(address, nonce, int(raw_pid))
    try:
        job = channel.receive()
        execute(channel, job, owner_home=elevation.origin_home(int(raw_pid)))
    except Exception as error:
        try:
            # All public errors are fixed messages; never echo request data or native command output.
            channel.send(
                {
                    "phase": "error",
                    "code": type(error).__name__,
                    "message": "The card operation did not finish. Keep the card inserted and review its setup status.",
                }
            )
        except (OSError, ValueError, InterruptedError):
            pass
        raise SystemExit(1) from None
    finally:
        channel.close()
