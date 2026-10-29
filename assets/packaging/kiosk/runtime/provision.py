#!/usr/bin/python3
"""Import a privately prepared boot-card configuration once."""

import json
import os
import re
import subprocess
from pathlib import Path

from network import profile as wifi_profile
from settings import import_settings

BOOT = Path("/boot/firmware")


def main():
    subprocess.run(["ssh-keygen", "-A"], check=True)
    path = BOOT / "carvera-provision.json"
    if not path.exists():
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    hostname = value["hostname"]
    keys = value["authorized_keys"]
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname):
        raise ValueError("Invalid kiosk hostname")
    if not keys or any(not re.fullmatch(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+(?: [^\r\n]*)?", key) for key in keys):
        raise ValueError("Invalid SSH public key")
    Path("/etc/hostname").write_text(hostname + "\n")
    subprocess.run(["hostname", hostname], check=True)
    hosts = Path("/etc/hosts")
    content = "\n".join(line for line in hosts.read_text().splitlines() if not line.startswith("127.0.1.1"))
    hosts.write_text(content + f"\n127.0.1.1 {hostname}\n")
    ssh = Path("/home/carvera-admin/.ssh")
    ssh.mkdir(mode=0o700, exist_ok=True)
    (ssh / "authorized_keys").write_text("\n".join(keys) + "\n")
    os.chmod(ssh / "authorized_keys", 0o600)
    subprocess.run(["chown", "-R", "carvera-admin:carvera-admin", str(ssh)], check=True)
    wifi = value.get("wifi")
    if wifi:
        for key in ("ssid", "password", "country"):
            if not isinstance(wifi.get(key), str) or any(char in wifi[key] for char in "\r\n\0"):
                raise ValueError("Invalid Wi-Fi provisioning")
        if not re.fullmatch("[A-Z]{2}", wifi["country"]):
            raise ValueError("Specify a two-letter Wi-Fi country")
        _, config = wifi_profile(wifi["ssid"], wifi["password"], autoconnect=True)
        profile = Path("/etc/NetworkManager/system-connections/carvera-wifi.nmconnection")
        profile.touch(mode=0o600, exist_ok=True)
        os.chmod(profile, 0o600)
        with profile.open("w") as output:
            config.write(output, space_around_delimiters=False)
        Path("/etc/modprobe.d/cfg80211_regdomain.conf").write_text(f"options cfg80211 ieee80211_regdom={wifi['country']}\n")
        subprocess.run(["iw", "reg", "set", wifi["country"]], check=True)
        subprocess.run(["rfkill", "unblock", "wifi"], check=True)
    settings = BOOT / "carvera-settings.tar.gz"
    if settings.exists():
        import_settings(settings, Path("/var/lib/carvera"))
        settings.unlink()
        subprocess.run(["chown", "-R", "carvera:carvera", "/var/lib/carvera"], check=True)
    path.unlink()
    Path("/var/lib/carvera/provisioned").touch()


if __name__ == "__main__":
    main()
