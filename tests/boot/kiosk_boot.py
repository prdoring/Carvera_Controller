"""Exercise real systemd 257 migration boots on disposable file-backed disks.

Run with Dockerfile.boot-test and a read-only source bind. No host disks or
network are used. QEMU uses software emulation and publishes no ports.
"""

import base64
import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import tempfile
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2]
ASSETS = SOURCE / "assets/packaging/kiosk"


def run(*args, **kwargs):
    result = subprocess.run([str(arg) for arg in args], check=False, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.decode(errors='replace')}")
    return result


def write(root, name, text, mode=0o644):
    path = root / name.lstrip("/")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def boot(disk, kernel, initrd, arguments, report):
    with report.open("wb") as output:
        result = subprocess.run(
            [
                "qemu-system-x86_64",
                "-machine",
                "q35",
                "-accel",
                "tcg",
                "-m",
                "768",
                "-smp",
                "2",
                "-display",
                "none",
                "-serial",
                "stdio",
                "-monitor",
                "none",
                "-nic",
                "none",
                "-no-reboot",
                "-kernel",
                str(kernel),
                "-initrd",
                str(initrd),
                "-append",
                arguments,
                "-drive",
                f"file={disk},format=raw,if=virtio",
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=240,
        )
    if result.returncode:
        raise RuntimeError(f"QEMU failed; inspect {report}")


def main():
    with tempfile.TemporaryDirectory(prefix="carvera-boot-") as temporary:
        work = Path(temporary)
        root = work / "root"
        shutil.copytree("/guest", root, symlinks=True)
        for directory in ("dev", "proc", "sys", "run", "boot/firmware"):
            (root / directory).mkdir(exist_ok=True, parents=True)
        for name, minor in (("null", 3), ("zero", 5), ("random", 8), ("urandom", 9)):
            path = root / "dev" / name
            if not path.exists():
                os.mknod(path, stat.S_IFCHR | 0o666, os.makedev(1, minor))
        for user in ("carvera", "carvera-admin"):
            run("chroot", root, "useradd", "--create-home", "--shell", "/bin/bash", user)
        run("chroot", root, "ssh-keygen", "-A")
        fingerprint = (
            run("ssh-keygen", "-l", "-E", "sha256", "-f", root / "etc/ssh/ssh_host_ed25519_key.pub")
            .stdout.decode()
            .split()[1]
        )
        key = work / "owner"
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key)
        write(
            root,
            "/etc/ssh/sshd_config.d/50-carvera.conf",
            "AllowUsers carvera-admin\nPermitRootLogin no\nPasswordAuthentication no\n",
        )
        write(root, "/etc/fstab", "/dev/vda2 / ext4 defaults 0 1\n/dev/vda1 /boot/firmware vfat defaults 0 2\n")
        original = b"root=/dev/vda2 rw console=ttyS0 rootwait noresume\n"
        staged = original.rstrip() + (
            b' systemd.run="/bin/bash /boot/firmware/kiosk-admin-bootstrap/bootstrap.sh"'
            b" systemd.run_success_action=reboot systemd.run_failure_action=poweroff\n"
        )
        capacity, boot_start, boot_size = 1792 * 1024**2, 2048, 128 * 1024**2
        root_start = boot_start + boot_size // 512
        request = {
            "format": 2,
            "id": "a" * 32,
            "legacy_gate": True,
            "admin_public_keys": [key.with_suffix(".pub").read_text().strip()],
            "target": {
                "image": {"format": "carvera-kiosk-pi4", "version": "test"},
                "capacity": capacity,
                "boot_uuid": "ABCD-1234",
                "boot_partuuid": "12345678-01",
                "root_partuuid": "12345678-02",
                "ssh_fingerprint": fingerprint,
                "cmdline_sha256": hashlib.sha256(original).hexdigest(),
            },
            "original_cmdline": base64.b64encode(original).decode(),
            "staged_cmdline": base64.b64encode(staged).decode(),
        }
        boot_tree = work / "boot"
        payload = boot_tree / "kiosk-admin-bootstrap"
        payload.mkdir(parents=True)
        for name in ("admin_accounts.py", "admin_bootstrap.py", "system_update.py"):
            shutil.copyfile(ASSETS / "runtime" / name, payload / name)
        shutil.copyfile(SOURCE / "carveracontroller/kiosk_state.py", payload / "kiosk_state.py")
        shutil.copyfile(ASSETS / "admin-bootstrap.sh", payload / "bootstrap.sh")
        (payload / "request.json").write_text(json.dumps(request))
        (payload / "cmdline.before").write_bytes(original)
        (payload / "payload.sha256").write_text(
            "".join(
                hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n"
                for path in sorted(payload.iterdir())
            )
        )
        (boot_tree / "cmdline.txt").write_bytes(staged)
        (boot_tree / "carvera-image.json").write_text(json.dumps(request["target"]["image"]))
        write(root, "/usr/local/lib/carvera-test-request.json", json.dumps(request))
        check = root / "usr/local/lib/carvera-boot-check.py"
        shutil.copyfile(SOURCE / "tests/boot/kiosk_guest_check.py", check)
        write(root, "/opt/carvera/maintenance/original", "legacy runtime\n")
        for name in ("provision", "cpu"):
            write(
                root,
                f"/etc/systemd/system/carvera-{name}.service",
                "[Unit]\nDescription=Test legacy runtime consumer\n[Service]\nType=oneshot\n"
                "ExecStart=/bin/test -f /opt/carvera/maintenance/original\n"
                f"ExecStart=/bin/touch /{name}-started\n[Install]\nWantedBy=multi-user.target\n",
            )
            run("chroot", root, "systemctl", "enable", f"carvera-{name}.service")
        write(
            root,
            "/etc/systemd/system/carvera-boot-check.service",
            "[Unit]\nDescription=Virtual migration assertions\nAfter=carvera-kiosk.service carvera-provision.service carvera-cpu.service\n"
            "FailureAction=poweroff\n[Service]\nType=oneshot\n"
            "ExecStart=/usr/bin/python3 -E -s /usr/local/lib/carvera-boot-check.py\n"
            "StandardOutput=journal+console\nStandardError=journal+console\n[Install]\nWantedBy=multi-user.target\n",
        )
        run("chroot", root, "systemctl", "enable", "carvera-boot-check.service")
        # The normal kiosk must not run during the dedicated migration boot.
        write(
            root,
            "/etc/systemd/system/carvera-kiosk.service",
            "[Unit]\nDescription=Test kiosk\n[Service]\nType=oneshot\nExecStart=/bin/touch /kiosk-started\n[Install]\nWantedBy=multi-user.target\n",
        )
        run("chroot", root, "systemctl", "enable", "carvera-kiosk.service")
        kernel = next((root / "boot").glob("vmlinuz-*"))
        initrd = next((root / "boot").glob("initrd.img-*"))
        fat, ext, disk = work / "boot.img", work / "root.img", work / "card.img"
        with fat.open("wb") as output:
            output.truncate(boot_size)
        run("mkfs.vfat", "-F", "32", "-i", "ABCD1234", fat)
        run("mcopy", "-i", fat, "-s", *boot_tree.iterdir(), "::/")
        with ext.open("wb") as output:
            output.truncate(capacity - root_start * 512)
        run("mkfs.ext4", "-q", "-F", "-d", root, ext)
        with disk.open("wb") as output:
            output.truncate(capacity)
            mbr = bytearray(512)
            struct.pack_into("<I", mbr, 440, 0x12345678)
            mbr[450] = 0x0C
            struct.pack_into("<II", mbr, 454, boot_start, boot_size // 512)
            mbr[466] = 0x83
            struct.pack_into("<II", mbr, 470, root_start, (capacity // 512) - root_start)
            mbr[510:512] = b"\x55\xaa"
            output.write(mbr)
            for path, offset in ((fat, boot_start * 512), (ext, root_start * 512)):
                output.seek(offset)
                with path.open("rb") as incoming:
                    shutil.copyfileobj(incoming, output)
        report = Path("/tmp/carvera-migration-boot.log")
        boot(disk, kernel, initrd, staged.decode().strip(), report)
        result = run("mtype", "-i", f"{disk}@@{boot_start * 512}", "::/kiosk-admin-migration-result.json").stdout
        answer = json.loads(result)
        assert answer["phase"] == "complete", answer
        assert run("mtype", "-i", f"{disk}@@{boot_start * 512}", "::/cmdline.txt").stdout == original
        # Read back the actual guest root and policy without mounting host disks.
        with disk.open("rb") as incoming, ext.open("wb") as output:
            incoming.seek(root_start * 512)
            shutil.copyfileobj(incoming, output)
        completed = run("debugfs", "-R", "cat /var/lib/carvera-system/access-complete.json", ext).stdout
        assert json.loads(completed)["id"] == request["id"]
        assert b"kiosk-started" not in run("debugfs", "-R", "ls /", ext).stdout
        for expected_phase in ("interrupted", "complete"):
            boot(
                disk, kernel, initrd, original.decode().strip(), Path("/tmp/carvera-normal-" + expected_phase + ".log")
            )
            checked = json.loads(run("mtype", "-i", f"{disk}@@{boot_start * 512}", "::/boot-check.json").stdout)
            assert checked["phase"] == expected_phase, checked
        print(
            "PASS: Debian 13/systemd 257 dedicated migration, real account/SSH/sudo checks, revoked-key replay, normal boot, interrupted conversion recovery before provision/CPU/kiosk"
        )


if __name__ == "__main__":
    main()
