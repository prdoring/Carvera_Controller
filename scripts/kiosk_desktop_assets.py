"""Download the redistributable fallback font with pinned checksums."""

import argparse
import hashlib
import urllib.request
from pathlib import Path

FILES = {
    "NotoSansCJKsc-Regular.otf": (
        "Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
        "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b",
        16437364,
    ),
    "LICENSE": ("LICENSE", "6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2", 4301),
}


def fetch(destination):
    destination.mkdir(parents=True, exist_ok=True)
    for name, (relative, expected, length) in FILES.items():
        path = destination / name
        if not path.exists():
            url = "https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/" + relative
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(length + 1)
            if len(data) != length or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("The fallback font download failed verification")
            with path.open("xb") as output:
                output.write(data)
        if path.stat().st_size != length or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("The cached fallback font does not match its pinned checksum")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    fetch(parser.parse_args().destination)
