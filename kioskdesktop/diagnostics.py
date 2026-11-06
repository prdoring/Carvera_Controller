"""Offline packaged-runtime checks; no disks, keys or devices are opened."""

import json
import subprocess
import sys
import tempfile
import tkinter as tk
from pathlib import Path

from kioskdesktop import profiles
from kioskdesktop.theme import Slate, register_fonts


def check(destination):
    import aiohttp
    import asyncssh

    root_path = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    metadata = json.loads((root_path / "desktop-build.json").read_text(encoding="utf-8"))
    register_fonts()
    root = tk.Tk()
    root.withdraw()
    try:
        style = Slate(root)
        fonts = {
            "sans": style.sans.actual("family"),
            "mono": style.mono.actual("family"),
            "unicode": style.text_font("工作室").actual("family"),
        }
        if fonts != {"sans": "IBM Plex Sans", "mono": "IBM Plex Mono", "unicode": "Noto Sans CJK SC"}:
            raise ValueError("Packaged font selection failed")
    finally:
        root.destroy()
    key = asyncssh.generate_private_key("ssh-ed25519")
    encrypted = key.export_private_key(passphrase="packaged-runtime-self-check")
    if (
        asyncssh.import_private_key(encrypted, passphrase="packaged-runtime-self-check").get_fingerprint()
        != key.get_fingerprint()
    ):
        raise ValueError("Encrypted key support is incomplete")
    from kioskdesktop.viewer_server import default_assets

    novnc = default_assets()
    if not all((novnc / name).is_file() for name in ("vnc.html", "core/rfb.js", "app/ui.js")):
        raise ValueError("The packaged screen viewer is incomplete")
    if metadata["kind"] == "setup":
        from kioskdesktop.disk_worker import stage_writer, writer_environment

        with tempfile.TemporaryDirectory(prefix="kiosk-runtime-writer-") as temporary:
            writer = stage_writer(Path(temporary) / "writer")
            if sys.platform == "win32":
                from kioskdesktop.native_version import windows_version

                if windows_version(writer)[:3] != (2, 0, 12):
                    raise ValueError("The packaged writer has an unexpected Windows version")
            else:
                result = subprocess.run(
                    [str(writer), "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=20,
                    env=writer_environment(),
                )
                if not {"Raspberry Pi Imager v2.0.12", "Raspberry Pi Imager 2.0.12"}.intersection(
                    (result.stdout + result.stderr).splitlines()
                ):
                    raise ValueError("The packaged writer has an unexpected version")
    if any(name == "kivy" or name.startswith("carveracontroller") for name in sys.modules):
        raise ValueError("The desktop runtime imported the controller")
    report = {"build": metadata, "fonts": fonts, "ssh": asyncssh.__version__, "http": aiohttp.__version__, "ok": True}
    profiles.write_new(Path(destination), (json.dumps(report, indent=2) + "\n").encode("utf-8"))
