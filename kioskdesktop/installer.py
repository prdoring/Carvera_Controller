"""User-owned preparation and the short-lived card-worker client."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import time
import urllib.request
from pathlib import Path

from kioskdesktop import elevation, ipc, profiles
from kioskdesktop.releases import Release, verify_image
from kioskdesktop.runtime import shared


def prepare(profile_path, profile, release: Release, wifi=None, preferences=None):
    """Persist the exact private request before any card write or permission prompt."""
    folder = Path(profile_path).parent
    protocol = shared("setup_protocol")
    request = {
        "format": 2,
        "setup_protocol": 1,
        "id": profile["id"],
        "hostname": profile["hostname"],
        "authorized_keys": [profile["keys"]["maintenance"]["public"]],
        "admin_public_keys": [profile["keys"]["administrator"]["public"]],
    }
    if wifi is not None:
        request["wifi"] = wifi
    payload = None
    if preferences:
        payload = shared("settings").prepare_archive(preferences)
        request["settings_sha256"] = hashlib.sha256(payload).hexdigest()
    protocol.validate_request(request, profiles.public_keys)
    transaction = {
        "protocol": 1,
        "configuration": request,
        "digest": protocol.identity(request)[1],
        "release": release.document(),
    }
    path = folder / "transaction.json"
    if path.exists():
        if protocol.read_json(path) != transaction:
            raise ValueError("This profile already has a different installation; open its saved transaction")
    else:
        if payload:
            profiles.write_new(folder / "preferences.tar.gz", payload)
        profiles.write_new(path, json.dumps(transaction, sort_keys=True).encode("utf-8"))
    protocol.write_json(folder / "release.json", release.document())
    profile.update(stage="prepared", release=release.version, commit=release.commit, components=release.components)
    profiles.save(Path(profile_path), profile)
    return transaction


def load_release(profile_path, profile):
    value = shared("setup_protocol").read_json(Path(profile_path).parent / "release.json")
    release = Release.parse(value)
    if release.commit != profile.get("commit") or release.components != profile.get("components"):
        raise ValueError("Saved release metadata does not match the installation profile")
    return release


def finish_verification(profile_path, profile):
    load_release(profile_path, profile)
    profiles.save(Path(profile_path), profile)
    for name in ("transaction.json", "preferences.tar.gz"):
        path = Path(profile_path).parent / name
        if path.is_symlink():
            raise ValueError("Unexpected local setup payload link")
        path.unlink(missing_ok=True)


def image_cache():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    if not base.is_absolute():
        raise ValueError("The image cache must use an absolute user-owned location")
    return base / "carvera-kiosk/images"


def transaction(profile_path, profile):
    value = shared("setup_protocol").read_json(Path(profile_path).parent / "transaction.json")
    if set(value) != {"protocol", "configuration", "digest", "release"} or value["protocol"] != 1:
        raise ValueError("The private installation transaction is invalid")
    request = shared("setup_protocol").validate_request(value["configuration"], profiles.public_keys)
    if (
        shared("setup_protocol").identity(request) != (profile["id"], value["digest"])
        or request["authorized_keys"] != [profile["keys"]["maintenance"]["public"]]
        or request["admin_public_keys"] != [profile["keys"]["administrator"]["public"]]
    ):
        raise ValueError("The saved transaction does not match this profile")
    Release.parse(value["release"])
    return value


def download(release, folder: Path, progress=lambda _value: None, cancelled=lambda: False):
    """Download to the original user's private cache; the worker verifies independently."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / (release.image.sha256 + ".img.xz")
    if target.exists():
        with target.open("rb") as source:
            verify_image(source, release.image, cancelled=cancelled)
        return target
    temporary = target.with_suffix(".part")
    try:
        with temporary.open("xb") as destination:
            request = urllib.request.Request(release.image.url, headers={"User-Agent": "Carvera-Kiosk-Setup"})
            with urllib.request.urlopen(request, timeout=30) as response:
                if not response.geturl().startswith("https://"):
                    raise ValueError("The image download was redirected to an insecure connection")
                count, digest = 0, hashlib.sha256()
                while block := response.read(1024**2):
                    if cancelled():
                        raise InterruptedError("Download cancelled")
                    count += len(block)
                    if count > release.image.size:
                        raise ValueError("Image download exceeds its declared size")
                    digest.update(block)
                    destination.write(block)
                    progress({"phase": "downloading", "bytes": count, "total": release.image.size})
            if count != release.image.size or digest.hexdigest() != release.image.sha256:
                raise ValueError("The downloaded image failed checksum verification")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, target)
        return target
    finally:
        temporary.unlink(missing_ok=True)


class CardOperation:
    def __init__(self):
        self.endpoint = None
        self.cancelled = False
        self.last_phase = None
        self.confirmed = threading.Event()
        self.process = None

    def cancel(self):
        self.cancelled = True
        if self.endpoint:
            self.endpoint.close()

    def confirm(self):
        self.confirmed.set()

    def is_running(self):
        if self.process is None:
            return False
        if self.process.poll() is None:
            return True
        if isinstance(self.process, elevation.WindowsProcess):
            self.process.close()
        self.process = None
        return False

    def run(self, selected, profile_path, profile, *, action, image=None, progress=lambda _value: None):
        value = transaction(profile_path, profile)
        release = Release.parse(value["release"])
        preferences = Path(profile_path).parent / "preferences.tar.gz"
        streams = []
        process = None
        status_path = Path(profile_path).parent / "card-status.json"
        shared("setup_protocol").write_json(status_path, {"id": profile["id"], "phase": "preparing", "action": action})
        try:
            image_stream = Path(image).open("rb") if action == "flash" else None
            if image_stream:
                streams.append(image_stream)
            settings = (
                preferences.open("rb") if value["configuration"].get("settings_sha256") and action != "resume" else None
            )
            if settings:
                streams.append(settings)
            for stream in streams:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError("Select regular image and preferences files")
            if image_stream and os.fstat(image_stream.fileno()).st_size != release.image.size:
                raise ValueError("The selected image length does not match its release metadata")
            protected = [
                str(Path.home()),
                str(Path(profile_path).resolve()),
                str(Path(__file__).resolve()),
                str(Path(os.sys.executable).resolve()),
            ]
            if image:
                protected.append(str(Path(image).resolve()))
            job = {
                "protocol": 1,
                "action": action,
                "device": {"path": selected.path, "identity": selected.identity},
                "release": value["release"],
                "configuration": value["configuration"],
                "expected_digest": value["digest"],
                "settings_size": os.fstat(settings.fileno()).st_size if settings else 0,
                "protected_paths": protected,
            }
            self.endpoint = ipc.Endpoint()
            progress({"phase": "permission"})
            if self.cancelled:
                raise InterruptedError("Card operation cancelled")
            process = elevation.launch(self.endpoint)
            self.process = process
            channel = self.endpoint.accept(process.pid, process)
            channel.send(job)
            for stream in streams:
                remaining = os.fstat(stream.fileno()).st_size
                while remaining:
                    if self.cancelled:
                        raise InterruptedError("Card operation cancelled")
                    chunk = stream.read(min(remaining, 1024**2))
                    if not chunk:
                        raise ValueError("A source file changed while being transferred")
                    channel.write(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise ValueError("A source file changed while being transferred")
            while True:
                reply = channel.receive()
                if reply.get("phase") == "complete" and reply.get("id") != profile["id"]:
                    raise ValueError("The worker completed a different transaction")
                if reply.get("phase") != "error":
                    if reply.get("phase") != self.last_phase:
                        shared("setup_protocol").write_json(
                            status_path, {"id": profile["id"], "phase": reply["phase"], "action": action}
                        )
                    self.last_phase = reply.get("phase")
                if reply.get("phase") == "awaiting_confirmation":
                    if (
                        reply.get("device", {}).get("identity") != selected.identity
                        or reply.get("device", {}).get("capacity") != selected.capacity
                        or reply.get("erases") != (action == "flash")
                    ):
                        raise ValueError("The physical card changed before confirmation")
                    progress(reply)
                    deadline = time.monotonic() + 295
                    while not self.confirmed.wait(0.1):
                        if self.cancelled or time.monotonic() > deadline or not channel.alive():
                            raise InterruptedError("Card confirmation cancelled or expired")
                    channel.send({"confirm": reply["confirmation"]})
                    continue
                progress(reply)
                if reply.get("phase") == "error":
                    raise RuntimeError(
                        "The card operation did not finish. Reopen the same profile to retry configuration."
                    )
                if self.last_phase == "complete":
                    return reply
        finally:
            for stream in streams:
                stream.close()
            if self.endpoint:
                self.endpoint.close()
                self.endpoint = None
            if process:
                deadline = time.monotonic() + 120
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)
                if self.is_running():
                    raise TimeoutError("The administrator worker is still cleaning up; keep the card inserted")


def desktop_target():
    import platform

    machine = platform.machine().lower()
    if os.name == "nt" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if os.sys.platform.startswith("linux") and machine in {"amd64", "x86_64", "aarch64", "arm64"}:
        return "linux-arm64" if machine in {"aarch64", "arm64"} else "linux-x64"
    raise ValueError("This desktop platform is not supported yet")
