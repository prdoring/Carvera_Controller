"""Boot v3 setup and interrupted root expansion on an exact disposable QEMU disk.

Run in Dockerfile.boot-test. All writes are to newly created regular files;
QEMU has no network, host block device, shared directory or listening port.
The session sentinels check routing, not graphical rendering.
"""

import json
import os
import shutil
import stat
import struct
import tempfile
from pathlib import Path

from kiosk_boot import ASSETS, SOURCE, boot, run, write


def main():
    reports = Path(os.environ.get("CARVERA_BOOT_REPORTS", "/tmp"))
    reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="carvera-v3-boot-") as temporary:
        work = Path(temporary)
        root = work / "root"
        shutil.copytree("/guest", root, symlinks=True)
        for name in ("dev", "proc", "sys", "run", "boot/firmware", "var/lib/carvera", "opt/carvera/maintenance"):
            (root / name).mkdir(parents=True, exist_ok=True)
        for name, minor in (("null", 3), ("zero", 5), ("random", 8), ("urandom", 9)):
            path = root / "dev" / name
            if not path.exists():
                os.mknod(path, stat.S_IFCHR | 0o666, os.makedev(1, minor))
        for user in ("carvera", "carvera-admin"):
            run("chroot", root, "useradd", "--create-home", "--shell", "/bin/bash", user)
        write(
            root,
            "/etc/ssh/sshd_config.d/50-carvera.conf",
            "AllowUsers carvera-admin\nPermitRootLogin no\nPasswordAuthentication no\n",
        )
        write(root, "/etc/fstab", "/dev/vda2 / ext4 defaults 0 1\n/dev/vda1 /boot/firmware vfat defaults 0 2\n")
        # The real image gets this from image-gen's rpi/misc-skel layer;
        # Docker deliberately omits its container-managed hosts file from /guest.
        write(
            root, "/etc/hosts", "127.0.0.1 localhost\n::1 localhost ip6-localhost ip6-loopback\n127.0.1.1 carvera-pi\n"
        )
        for name in (
            "admin_accounts.py",
            "provision.py",
            "provision_v3.py",
            "setup_protocol.py",
            "setup_gate.py",
            "settings.py",
            "network.py",
        ):
            shutil.copyfile(ASSETS / "runtime" / name, root / "opt/carvera/maintenance" / name)
        (root / "usr/local/lib/carvera").mkdir(parents=True)
        shutil.copyfile(ASSETS / "firstboot/grow_root.py", root / "usr/local/lib/carvera/grow_root.py")
        shutil.copyfile(SOURCE / "tests/boot/kiosk_setup_guest.py", root / "usr/local/lib/kiosk-setup-check.py")
        write(
            root,
            "/usr/local/lib/growth-check.py",
            """import json, os, sys
from pathlib import Path
sys.path.insert(0, '/usr/local/lib/carvera')
import grow_root
original = grow_root.command
def command(*args, **kwargs):
    case = json.loads(Path('/boot/firmware/test-case.json').read_text())['case']
    if args[0] == 'resize2fs' and case == 'interrupted':
        os._exit(77)
    return original(*args, **kwargs)
grow_root.command = command
grow_root.grow()
""",
        )
        for name in ("carvera-hostkeys.service", "carvera-root-grow.service", "carvera-provision.service"):
            shutil.copyfile(ASSETS / "overlay/etc/systemd/system" / name, root / "etc/systemd/system" / name)
            run("chroot", root, "systemctl", "enable", name)
        # image-gen also enables its own generator. Delay it to exercise the
        # ordering needed to keep two generators from writing the same keys.
        write(
            root,
            "/etc/systemd/system/ssh-hostkeys-generate.service",
            "[Unit]\nAfter=local-fs.target\nBefore=ssh.service\n[Service]\nType=oneshot\n"
            "ExecStart=/bin/sh -c 'sleep 2; ssh-keygen -A; touch /run/upstream-hostkeys-ready'\n"
            "RemainAfterExit=yes\n[Install]\nWantedBy=multi-user.target\n",
        )
        run("chroot", root, "systemctl", "enable", "ssh-hostkeys-generate.service")
        write(
            root,
            "/etc/systemd/system/carvera-hostkeys.service.d/test.conf",
            "[Service]\nExecStartPre=/usr/bin/test -e /run/upstream-hostkeys-ready\n",
        )
        write(
            root,
            "/etc/systemd/system/carvera-root-grow.service.d/test.conf",
            "[Service]\nExecStart=\nExecStart=/usr/bin/python3 /usr/local/lib/growth-check.py\n",
        )
        for name in ("controller", "recovery"):
            write(
                root,
                f"/etc/systemd/system/carvera-{name}.service",
                "[Unit]\nAfter=carvera-provision.service\n[Service]\nType=oneshot\n"
                "ExecCondition=/usr/bin/python3 /opt/carvera/maintenance/setup_gate.py --check\n"
                f"ExecStart=/bin/touch /run/{name}-started\n[Install]\nWantedBy=multi-user.target\n",
            )
            run("chroot", root, "systemctl", "enable", f"carvera-{name}.service")
        write(
            root,
            "/etc/systemd/system/carvera-kiosk.service",
            "[Unit]\nAfter=carvera-provision.service\n[Service]\nType=oneshot\n"
            "ExecStart=/bin/sh -c '/usr/bin/python3 /opt/carvera/maintenance/setup_gate.py --check || touch /run/limited-screen-selected'\n"
            "[Install]\nWantedBy=multi-user.target\n",
        )
        write(
            root,
            "/etc/systemd/system/carvera-setup-check.service",
            "[Unit]\nAfter=carvera-kiosk.service carvera-controller.service carvera-recovery.service\n"
            "FailureAction=poweroff\n[Service]\nType=oneshot\n"
            "ExecStart=/usr/bin/python3 /usr/local/lib/kiosk-setup-check.py\n"
            "StandardOutput=journal+console\nStandardError=journal+console\n[Install]\nWantedBy=multi-user.target\n",
        )
        for name in ("carvera-kiosk.service", "carvera-setup-check.service"):
            run("chroot", root, "systemctl", "enable", name)
        keys = []
        for role in ("maintenance", "administrator"):
            key = work / role
            run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", key)
            keys.append(key.with_suffix(".pub").read_text().strip())
        request = {
            "format": 2,
            "setup_protocol": 1,
            "id": "b" * 32,
            "hostname": "carvera-test",
            "authorized_keys": keys[:1],
            "admin_public_keys": keys[1:],
        }
        write(root, "/usr/local/lib/test-request.json", json.dumps(request))
        boot_tree = work / "boot"
        boot_tree.mkdir()
        (boot_tree / "carvera-image.json").write_text(
            json.dumps({"format": "carvera-kiosk-pi4-v3", "version": "test", "commit": "a" * 40, "setup_protocol": 1})
        )
        (boot_tree / "carvera-setup.json").write_text(json.dumps({"protocol": 1, "phase": "fresh"}))
        capacity, boot_start, boot_size, root_size = 3072 * 1024**2, 2048, 128 * 1024**2, 1536 * 1024**2
        root_start = boot_start + boot_size // 512
        kernel = next((root / "boot").glob("vmlinuz-*"))
        initrd = next((root / "boot").glob("initrd.img-*"))
        fat, ext, disk = work / "boot.img", work / "root.img", work / "card.img"
        with ext.open("wb") as output:
            output.truncate(root_size)
        run("mkfs.ext4", "-q", "-F", "-d", root, ext)

        def reset(case, value=None):
            with fat.open("wb") as output:
                output.truncate(boot_size)
            run("mkfs.vfat", "-F", "32", fat)
            run("mcopy", "-i", fat, "-s", *boot_tree.iterdir(), "::/")
            with disk.open("wb") as output:
                output.truncate(capacity)
                mbr = bytearray(512)
                struct.pack_into("<I", mbr, 440, 0x12345678)
                mbr[450], mbr[466] = 0x0C, 0x83
                struct.pack_into("<II", mbr, 454, boot_start, boot_size // 512)
                struct.pack_into("<II", mbr, 470, root_start, root_size // 512)
                mbr[510:] = b"\x55\xaa"
                output.write(mbr)
                for source, offset in ((fat, boot_start * 512), (ext, root_start * 512)):
                    output.seek(offset)
                    with source.open("rb") as incoming:
                        shutil.copyfileobj(incoming, output)
            set_case(case)
            if value is not None:
                path = work / "request.json"
                path.write_text(json.dumps(value))
                run("mcopy", "-o", "-i", volume, path, "::/carvera-provision.json")
                path.write_text(json.dumps({"protocol": 1, "phase": "prepared", "id": request["id"]}))
                run("mcopy", "-o", "-i", volume, path, "::/carvera-setup.json")

        volume = f"{disk}@@{boot_start * 512}"

        def set_case(case):
            path = work / "case.json"
            path.write_text(json.dumps({"case": case}))
            run("mcopy", "-o", "-i", volume, path, "::/test-case.json")
            run("mdel", "-i", volume, "::/boot-check.json") if case in {"complete", "replay"} else None

        previous_host = None
        for case, value in (
            ("missing", None),
            ("malformed", {**request, "admin_public_keys": ["invalid"]}),
            ("interrupted", request),
            ("complete", None),
            ("replay", None),
        ):
            if case in {"complete", "replay"}:
                set_case(case)
            else:
                reset(case, value)
            boot(
                disk,
                kernel,
                initrd,
                "root=/dev/vda2 rw console=ttyS0 rootwait noresume",
                reports / ("carvera-v3-" + case + ".log"),
            )
            result = json.loads(run("mtype", "-i", volume, "::/boot-check.json").stdout)
            assert result["ok"] and result["case"] == case, result
            if case in {"complete", "replay"}:
                assert result["host"] == previous_host, result
            previous_host = result["host"]
            print("PASS: v3 " + case, flush=True)


if __name__ == "__main__":
    main()
