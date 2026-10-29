#!/usr/bin/python3
"""Select an advertised 60 Hz mode on the single connected display."""

import re
import subprocess
import sys
from pathlib import Path


def parse_outputs(text):
    outputs = []
    for line in text.splitlines():
        if line and not line[0].isspace():
            outputs.append({"name": line.split()[0], "modes": []})
        match = re.fullmatch(r"\s+(\d+)x(\d+) px, ([0-9.]+) Hz(?: \(.*\))?", line)
        if match and outputs:
            width, height, refresh = match.groups()
            outputs[-1]["modes"].append({"width": int(width), "height": int(height), "refresh": float(refresh)})
    return outputs


def apply(mode):
    if mode not in ("1920x1200", "1920x1080"):
        raise ValueError("Unsupported display size")
    result = subprocess.run(["wlr-randr"], capture_output=True, text=True, check=True)
    outputs = parse_outputs(result.stdout)
    if len(outputs) != 1:
        raise ValueError("This kiosk profile requires one connected display")
    output = outputs[0]
    width, height = map(int, mode.split("x"))
    matches = [item for item in output["modes"] if item["width"] == width and item["height"] == height
               and 59 <= item["refresh"] <= 61]
    if not matches:
        raise ValueError(f"The connected screen does not advertise {mode} at 60 Hz")
    selected = min(matches, key=lambda item: abs(item["refresh"] - 60))
    subprocess.run(["wlr-randr", "--output", output["name"], "--mode",
                    f"{mode}@{selected['refresh']:.6f}Hz"], check=True)


if __name__ == "__main__":
    apply(sys.argv[1] if len(sys.argv) == 2 else Path("/etc/carvera/display-mode").read_text().strip())
