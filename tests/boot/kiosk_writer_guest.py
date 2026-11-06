"""CI-only writer adapter for the uniquely identified disposable second QEMU disk."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/ci-source")
sys._MEIPASS = "/opt/ci-assets"

from kioskdesktop import devices, disk_ops, disk_worker
from kioskdesktop.releases import Image, verify_image
from kioskdesktop.runtime import shared


def main():
    expected = json.loads(Path("/opt/ci-assets/test.json").read_text())
    # This adapter has no target argument and is never bundled in production.
    actual_serial = Path("/sys/class/block/vdb/serial").read_text().strip()
    assert actual_serial == expected["serial"], (actual_serial, expected["serial"])
    assert expected["serial"].startswith("CARVERA-CI-")
    assert int(Path("/sys/class/block/vdb/size").read_text()) * 512 == expected["capacity"]
    selected = next(item for item in devices.inventory() if item.path == "/dev/vdb")
    assert selected.virtual and not selected.eligible
    try:
        devices.select(selected.path, selected.identity, [])
    except ValueError:
        pass
    else:
        raise AssertionError("Production selection accepted a protected virtual disk")
    image = Image(**expected["image"])
    source = Path("/opt/ci-assets/source.img.xz")
    with source.open("rb") as incoming:
        layout = verify_image(incoming, image)
    executable = disk_worker.stage_writer(Path("/var/tmp/ci-writer"))
    with disk_ops.MediaProof(selected) as proof:
        proof.check()
        # The unsafe upstream option is confined to this guest with an exact serial,
        # capacity and new backing file. Verification stays enabled.
        subprocess.run(
            [
                str(executable),
                "--enable-writing-system-drives",
                "--disable-eject",
                "--sha256",
                image.raw_sha256,
                str(source),
                "/dev/vdb",
            ],
            check=True,
            timeout=120,
        )
        proof.check()
        with Path("/dev/vdb").open("rb", buffering=0) as incoming:
            result, remaining = hashlib.sha256(), image.raw_size
            while remaining:
                block = incoming.read(min(1024**2, remaining))
                assert block
                result.update(block)
                remaining -= len(block)
            assert result.hexdigest() == image.raw_sha256
        subprocess.run(["blockdev", "--rereadpt", "/dev/vdb"], check=True)
        subprocess.run(["udevadm", "settle", "--timeout=15"], check=True)
        selected = next(item for item in devices.inventory() if item.path == "/dev/vdb")
        assert selected.virtual and not selected.eligible
        protocol, accounts = shared("setup_protocol"), shared("admin_accounts")
        with disk_ops.mounted_boot(selected, layout, proof) as boot:
            protocol.prepare(boot, expected["request"], accounts.public_keys)
        # Reopen the actual filesystem after unmounting, independently of cached files.
        with disk_ops.mounted_boot(selected, layout, proof) as boot:
            assert protocol.read_json(boot / protocol.REQUEST) == expected["request"]
            receipt = protocol.read_json(boot / protocol.RECEIPT)
            assert receipt == protocol.receipt("prepared", expected["request"]["id"])
            assert "digest" not in receipt and "password" not in receipt
        proof.check()
    print("PASS: protected virtual selection, real pinned writer/readback, mount/configure/unmount/remount", flush=True)
    subprocess.run(["systemctl", "poweroff"], check=True)


if __name__ == "__main__":
    main()
