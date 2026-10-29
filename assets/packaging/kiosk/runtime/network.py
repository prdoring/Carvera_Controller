"""Create NetworkManager profiles without putting passwords in process arguments."""

import configparser
import uuid


def profile(ssid, password, *, autoconnect):
    if (not isinstance(ssid, str) or not isinstance(password, str)
            or any(char in ssid + password for char in "\r\n\0")
            or not 1 <= len(ssid.encode("utf-8")) <= 32 or not 8 <= len(password.encode("utf-8")) <= 63):
        raise ValueError("Use a Wi-Fi name of at most 32 bytes and a WPA password of 8–63 bytes")

    def escape(value):
        return value.replace("\\", "\\\\").replace(" ", "\\s").replace("\t", "\\t")

    identity = str(uuid.uuid4())
    config = configparser.ConfigParser(interpolation=None)
    config.read_dict({
        "connection": {"id": "Carvera Wi-Fi", "uuid": identity, "type": "wifi", "autoconnect": str(autoconnect).lower()},
        "wifi": {"ssid": escape(ssid), "mode": "infrastructure", "powersave": "2"},
        "wifi-security": {"key-mgmt": "wpa-psk", "psk": escape(password)},
        "ipv4": {"method": "auto"}, "ipv6": {"method": "auto"},
    })
    return identity, config
