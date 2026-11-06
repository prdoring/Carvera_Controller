"""Fetch the independently packaged viewer's pinned noVNC presentation."""

import argparse
import subprocess
from pathlib import Path

COMMIT = "a8dfd6a3ea3c74244f5ebdaa5a7f1023007a7820"


def fetch(folder):
    if not folder.exists():
        subprocess.run(
            [
                "git",
                "-c",
                "core.autocrlf=false",
                "clone",
                "--depth",
                "1",
                "--branch",
                "v1.6.0",
                "https://github.com/novnc/noVNC.git",
                str(folder),
            ],
            check=True,
        )
    actual = subprocess.check_output(["git", "-C", str(folder), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-c", "core.autocrlf=input", "-C", str(folder), "status", "--porcelain"], text=True
    ).strip()
    if actual != COMMIT or dirty:
        raise ValueError("The noVNC source does not match its pinned identity")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    fetch(parser.parse_args().folder)
