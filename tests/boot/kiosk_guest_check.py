"""Assertions run inside the disposable Debian guest, never on a real Pi."""

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/carvera/updater")
from admin_accounts import install, read_json, write_json


def main():
    boot = Path("/boot/firmware")
    marker = boot / "boot-check.json"
    home = Path("/home/kiosk-admin")
    request = read_json(Path("/usr/local/lib/carvera-test-request.json"))
    if not marker.exists():
        assert (home / ".ssh/authorized_keys").read_text().strip() == request["admin_public_keys"][0]
        (home / ".ssh/authorized_keys").write_text("")
        subprocess.run(["usermod", "--password", "owner-test-console-hash", "kiosk-admin"], check=True)
        install(request)
        assert (home / ".ssh/authorized_keys").read_text() == ""
        assert subprocess.check_output(["getent", "shadow", "kiosk-admin"]).split(b":")[1] == b"owner-test-console-hash"
        # Reproduce power loss after moving a legacy directory but before
        # publishing system-current. The stable updater must restore it at boot.
        legacy = Path("/opt/carvera/system-releases/legacy-boot-test")
        legacy.mkdir(parents=True)
        runtime = Path("/opt/carvera/maintenance")
        runtime.rename(legacy / "runtime")
        runtime.symlink_to("system-current/runtime", target_is_directory=True)
        write_json(
            Path("/var/lib/carvera-system/transaction.json"),
            {
                "id": "b" * 32,
                "phase": "activating",
                "mode": "recovery",
                "legacy": str(legacy),
                "unit_snapshot": {},
                "conversions": [{"alias": "maintenance", "destination": "runtime", "existed": True}],
            },
        )
        Path("/etc/systemd/system/carvera-provision.service.d/10-completed-setup.conf").unlink()
        write_json(marker, {"phase": "interrupted", "replay_preserved_revocation": True})
        subprocess.run(["systemctl", "reboot"], check=True)
    else:
        assert read_json(Path("/var/lib/carvera-system/transaction.json"))["phase"] == "rolled-back"
        assert Path("/opt/carvera/maintenance/original").read_text() == "legacy runtime\n"
        assert not Path("/opt/carvera/maintenance").is_symlink()
        assert Path("/kiosk-started").exists()
        assert Path("/provision-started").exists()
        assert Path("/cpu-started").exists()
        assert (home / ".ssh/authorized_keys").read_text() == ""
        subprocess.run(["systemctl", "is-enabled", "getty@tty2.service"], check=True)
        write_json(marker, {"phase": "complete", "boot_recovery": True, "replay_preserved_revocation": True})
        subprocess.run(["systemctl", "poweroff"], check=True)


if __name__ == "__main__":
    main()
