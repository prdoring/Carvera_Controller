"""Assertions for the disposable v3 setup guest; no machine transports are loaded."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/opt/carvera/maintenance")
import provision_v3
import setup_protocol

BOOT = Path("/boot/firmware")
STATE = Path("/var/lib/carvera-system")


def main():
    case = json.loads((BOOT / "test-case.json").read_text())["case"]
    status = provision_v3.status()
    assert len(status["host_fingerprints"]) == 1, status
    root = json.loads((STATE / "root-grow.json").read_text())
    assert Path("/proc/1/exe").resolve() == Path("/usr/lib/systemd/systemd")
    assert subprocess.check_output(["/proc/1/exe", "--version"]).splitlines()[0].startswith(b"systemd 257")
    if case in {"missing", "malformed", "interrupted"}:
        assert not provision_v3.completion_ready(), status
        assert Path("/run/limited-screen-selected").exists()
        assert not Path("/run/controller-started").exists()
        assert not Path("/run/recovery-started").exists()
        assert status["error"] == ("storage" if case == "interrupted" else "configuration"), status
        if case == "interrupted":
            assert root["phase"] == "partition", root
            partition = int(Path("/sys/class/block/vda2/size").read_text()) * 512
            filesystem = os.statvfs("/")
            assert filesystem.f_blocks * filesystem.f_frsize < partition - 128 * 1024**2
        else:
            assert root["phase"] == "complete", root
    else:
        assert provision_v3.completion_ready(), status
        assert root["phase"] == "complete", root
        assert root["filesystem_bytes"] > 2500 * 1024**2, root
        assert Path("/run/controller-started").exists()
        assert Path("/run/recovery-started").exists()
        assert not Path("/run/limited-screen-selected").exists()
        assert status["phase"] == "complete" and not status["cleanup_pending"], status
        assert subprocess.check_output(["sudo", "-u", "kiosk-admin", "sudo", "-n", "id", "-u"]).strip() == b"0"
        subprocess.run(["systemctl", "is-enabled", "getty@tty2.service"], check=True)
        if case == "complete":
            saved = json.loads(Path("/usr/local/lib/test-request.json").read_text())
            for user, key in (("carvera-admin", "authorized_keys"), ("kiosk-admin", "admin_public_keys")):
                path = Path("/home") / user / ".ssh/authorized_keys"
                assert path.read_text().strip() == saved[key][0]
                path.write_text("")
            subprocess.run(["usermod", "--password", "owner-console-test-hash", "kiosk-admin"], check=True)
            setup_protocol.write_json(BOOT / setup_protocol.REQUEST, saved)
            setup_protocol.write_json(BOOT / setup_protocol.RECEIPT, setup_protocol.receipt("prepared", saved["id"]))
        elif case == "replay":
            for user in ("carvera-admin", "kiosk-admin"):
                assert (Path("/home") / user / ".ssh/authorized_keys").read_text() == ""
            assert (
                subprocess.check_output(["getent", "shadow", "kiosk-admin"]).split(b":")[1]
                == b"owner-console-test-hash"
            )
            assert status["key_fingerprints"] == {"maintenance": [], "administrator": []}
    setup_protocol.write_json(
        BOOT / "boot-check.json",
        {"case": case, "ok": True, "host": status["host_fingerprints"], "growth": root["phase"]},
    )
    subprocess.run(["systemctl", "poweroff"], check=True)


if __name__ == "__main__":
    main()
