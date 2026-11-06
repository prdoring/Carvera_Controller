"""Install the kiosk owner account without replacing existing credentials."""

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

IMAGE_FORMAT = "carvera-kiosk-pi4-v2"
LEGACY_FORMAT = "carvera-kiosk-pi4"
STATE = Path("/var/lib/carvera-system")
ADMIN = "kiosk-admin"


def command(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, encoding="utf-8", capture_output=True, timeout=30, **kwargs)


def atomic_write(path, content, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content if isinstance(content, bytes) else content.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
            if hasattr(os, "fchmod"):
                os.fchmod(output.fileno(), mode)
        os.replace(temporary, path)
        if os.name != "nt":
            descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def key_records(values):
    """Validate common record boundaries without an operating-system dependency."""
    if not isinstance(values, list) or not 1 <= len(values) <= 16:
        raise ValueError("Provide between one and sixteen SSH public keys")
    result = []
    for value in values:
        if not isinstance(value, str) or len(value.encode("utf-8")) > 16384:
            raise ValueError("Invalid SSH public key")
        if len(value.splitlines()) != 1:
            raise ValueError("Provide a single public key without extra lines")
        value = value.strip()
        if not re.fullmatch(
            r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(?:256|384|521)) [A-Za-z0-9+/=]+(?: [^\r\n\0]*)?", value
        ):
            raise ValueError("Provide a single public key without authorized_keys options")
        encoded = value.split(" ", 2)[1]
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as error:
            raise ValueError("Invalid SSH public-key encoding") from error
        if base64.b64encode(decoded).decode("ascii") != encoded:
            raise ValueError("Use canonical OpenSSH public-key encoding")
        result.append(value)
    return result


def public_keys(values, verify=None):
    keys, fingerprints = [], []
    for value in key_records(values):
        if verify is not None:
            fingerprint = verify(value)
            if fingerprint not in fingerprints:
                keys.append(value)
                fingerprints.append(fingerprint)
            continue
        with tempfile.TemporaryDirectory(prefix="kiosk-key-") as temporary:
            path = Path(temporary) / "public.pub"
            path.write_text(value + "\n", encoding="utf-8")
            try:
                result = command("ssh-keygen", "-l", "-E", "sha256", "-f", str(path))
            except subprocess.CalledProcessError as error:
                raise ValueError("OpenSSH could not validate this public key") from error
        lines = result.stdout.strip().splitlines()
        if len(lines) != 1 or len(lines[0].split()) < 2:
            raise ValueError("OpenSSH did not recognize a single public key")
        fingerprint = lines[0].split()[1]
        if fingerprint not in fingerprints:
            fingerprints.append(fingerprint)
            keys.append(value)
    return keys, fingerprints


def request_identity(request):
    if not isinstance(request, dict) or len(json.dumps(request).encode("utf-8")) > 65536:
        raise ValueError("Invalid administrator setup request")
    identity = request.get("id", "")
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
        raise ValueError("Invalid administrator setup identity")
    return identity, hashlib.sha256(json.dumps(request, sort_keys=True).encode("utf-8")).hexdigest()


def ssh_policy(original):
    lines, users = [], []
    for line in original.splitlines():
        fields = line.split()
        if fields and fields[0].lower() == "match":
            raise ValueError("Review the custom SSH policy before installing an administrator")
        if fields and fields[0].lower() == "allowusers":
            users.extend(fields[1:])
        else:
            lines.append(line)
    # The managed policy must not depend on an earlier permissive directive.
    fixed = {
        "permitrootlogin": "no",
        "passwordauthentication": "no",
        "authenticationmethods": "publickey",
        "kbdinteractiveauthentication": "no",
    }
    lines = [line for line in lines if not line.split() or line.split()[0].lower() not in fixed]
    lines.extend(f"{name} {value}" for name, value in fixed.items())
    lines.append("AllowUsers " + " ".join(dict.fromkeys([*users, "carvera-admin", ADMIN])))
    return "\n".join(lines) + "\n"


def validate_policy():
    runtime = Path("/run/sshd")
    runtime.mkdir(mode=0o755, exist_ok=True)
    if runtime.is_symlink() or runtime.stat().st_uid != 0 or runtime.stat().st_mode & 0o022:
        raise ValueError("Unsafe SSH runtime directory")
    command("/usr/sbin/visudo", "-cf", "/etc/sudoers")
    command("/usr/sbin/sshd", "-t")
    for user in ("carvera-admin", ADMIN):
        output = command("/usr/sbin/sshd", "-T", "-C", f"user={user},host=localhost,addr=127.0.0.1").stdout
        values = dict(
            line.split(" ", 1) for line in output.splitlines() if " " in line and not line.startswith("allowusers ")
        )
        allowed = [name for line in output.splitlines() if line.startswith("allowusers ") for name in line.split()[1:]]
        if any(values.get(option) for option in ("denyusers", "allowgroups", "denygroups")):
            raise ValueError("Review custom SSH user/group restrictions before administrator setup")
        if (
            values.get("permitrootlogin") != "no"
            or values.get("passwordauthentication") != "no"
            or values.get("authenticationmethods") != "publickey"
            or user not in allowed
        ):
            raise ValueError("The effective SSH policy does not allow the intended key-only login")
    rules = command("sudo", "-n", "-l", "-U", ADMIN).stdout
    if "NOPASSWD: ALL" not in rules:
        raise ValueError("The kiosk administrator does not have the expected sudo rule")


def install(request, root=Path("/")):
    """Return a durable result; completed requests never rewrite credentials."""
    import pwd

    if os.geteuid() != 0:
        raise ValueError("Administrator setup requires root")
    identity, digest = request_identity(request)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(STATE, 0o700)
    completion = STATE / "access-complete.json"
    completed = read_json(completion)
    if completed:
        if completed.get("id") == identity and completed.get("digest") == digest:
            return completed
        raise ValueError("Administrator setup is complete; use explicit key rotation instead of provisioning again")
    keys, fingerprints = public_keys(request.get("admin_public_keys"))
    journal = STATE / "access-pending.json"
    pending = read_json(journal)
    if pending and (pending.get("id"), pending.get("digest")) != (identity, digest):
        raise ValueError("A different administrator setup is incomplete")
    try:
        account = pwd.getpwnam(ADMIN)
    except KeyError:
        account = None
    if account is not None and not pending:
        image_account = read_json(STATE / "image-account.json")
        if (
            image_account.get("uid") != account.pw_uid
            or image_account.get("home") != account.pw_dir
            or (root / account.pw_dir.lstrip("/") / ".ssh/authorized_keys").exists()
        ):
            raise ValueError("An unrecognized kiosk-admin account already exists")
    managed = [
        root / "etc/ssh/sshd_config.d/50-carvera.conf",
        root / "etc/sudoers.d/kiosk-admin",
        root / "etc/systemd/system/carvera-provision.service.d/10-completed-setup.conf",
    ]
    saved = STATE / "access-before"
    if not pending:
        saved.mkdir(mode=0o700, exist_ok=True)
        snapshots = []
        for index, path in enumerate(managed):
            if path.is_symlink():
                raise ValueError("Managed access policy must not be a symbolic link")
            exists = path.exists()
            snapshots.append(
                {"path": str(path), "exists": exists, "mode": path.stat().st_mode & 0o777 if exists else 0o600}
            )
            if exists:
                atomic_write(saved / str(index), path.read_bytes())
        pending = {"id": identity, "digest": digest, "snapshots": snapshots}
        write_json(journal, pending)
    try:
        if account is None:
            command("useradd", "--create-home", "--shell", "/bin/bash", "--password", "*", ADMIN)
            account = pwd.getpwnam(ADMIN)
        home = root / account.pw_dir.lstrip("/")
        if account.pw_dir != "/home/kiosk-admin" or home.is_symlink():
            raise ValueError("Unexpected kiosk administrator home")
        ssh = home / ".ssh"
        ssh.mkdir(mode=0o700, exist_ok=True)
        if ssh.is_symlink() or (ssh / "authorized_keys").is_symlink():
            raise ValueError("Administrator SSH paths must not be symbolic links")
        existing = (ssh / "authorized_keys").read_text().splitlines() if (ssh / "authorized_keys").exists() else []
        atomic_write(ssh / "authorized_keys", "\n".join(dict.fromkeys([*existing, *keys])) + "\n")
        for path in (home, ssh, ssh / "authorized_keys"):
            os.chown(path, account.pw_uid, account.pw_gid)
        os.chmod(ssh, 0o700)
        transfers = home / "transfers"
        transfers.mkdir(mode=0o700, exist_ok=True)
        os.chown(transfers, account.pw_uid, account.pw_gid)
        for name in ("uploads", "exports"):
            path = transfers / name
            path.mkdir(mode=0o700, exist_ok=True)
            os.chown(path, account.pw_uid, account.pw_gid)
        original = managed[0].read_text() if managed[0].exists() else ""
        atomic_write(managed[0], ssh_policy(original), 0o644)
        atomic_write(managed[1], "kiosk-admin ALL=(ALL:ALL) NOPASSWD: ALL\n", 0o440)
        if request.get("legacy_gate") is True:
            atomic_write(
                managed[2], "[Unit]\nConditionPathExists=!/var/lib/carvera-system/access-complete.json\n", 0o644
            )
        command("ssh-keygen", "-A")
        validate_policy()
        command("systemctl", "enable", "getty@tty2.service")
        result = {
            "id": identity,
            "digest": digest,
            "key_fingerprints": fingerprints,
            "account": ADMIN,
            "operation": "migration" if request.get("legacy_gate") else "provision",
            "target": request.get("target", {"hostname": request.get("hostname"),
                                              "image_format": "carvera-kiosk-pi4-v3" if request.get("setup_protocol") == 1 else IMAGE_FORMAT}),
        }
        write_json(completion, result)
        journal.unlink(missing_ok=True)
        return result
    except Exception:
        for index, snapshot in enumerate(pending["snapshots"]):
            path = Path(snapshot["path"])
            if snapshot["exists"]:
                atomic_write(path, (saved / str(index)).read_bytes(), snapshot["mode"])
            else:
                path.unlink(missing_ok=True)
        # Keep the journal and account for an idempotent retry; SSH admission was restored.
        raise
