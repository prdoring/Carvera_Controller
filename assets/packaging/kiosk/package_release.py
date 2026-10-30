"""Export standalone laptop tools and checksums for a kiosk image release."""

import hashlib
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def release_names(version):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}(?:[a-zA-Z0-9.+-]*)", version):
        raise ValueError("Invalid release version")
    return (
        f"carvera-kiosk-pi4-{version}.img.xz",
        f"carvera-kiosk-laptop-{version}.zip",
        f"carvera-kiosk-app-{version}.tar.gz",
    )


def package_laptop(version, output, helper, novnc):
    output, helper, novnc = Path(output), Path(helper), Path(novnc)
    archive_name = release_names(version)[1]
    for relative in ("vnc.html", "app/ui.js", "core/rfb.js"):
        if not (novnc / relative).is_file():
            raise ValueError(f"Incomplete noVNC directory: {relative}")
    assets = Path(__file__).resolve().parent
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kiosk-laptop-", dir=output) as temporary:
        stage = Path(temporary)
        laptop = stage / "laptop"
        laptop.mkdir()
        shutil.copy2(helper, laptop / "kiosk.py")
        shutil.copy2(assets / "laptop-requirements.txt", laptop / "laptop-requirements.txt")
        instructions = (assets / "laptop-README.md").read_text(encoding="utf-8")
        (laptop / "README.md").write_text(instructions.replace("@VERSION@", version), encoding="utf-8")
        shutil.copytree(novnc, laptop / "novnc", ignore=shutil.ignore_patterns(".git", "__pycache__"))
        files = sorted(path for path in laptop.rglob("*") if path.is_file())
        private_names = {
            "makera.ini",
            "carvera-provision.json",
            "carvera-settings.tar.gz",
            "id_rsa",
            "id_ed25519",
            "authorized_keys",
        }
        for path in files:
            if path.name in private_names or re.search(
                rb"(?m)^-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----\r?$", path.read_bytes()
            ):
                raise ValueError(f"Private data in laptop tools: {path.relative_to(laptop)}")
        archive = stage / archive_name
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.write(path, path.relative_to(stage).as_posix())
        archive.replace(output / archive_name)
        shutil.copytree(laptop, output / "laptop", dirs_exist_ok=True)
    return output / archive_name


def write_checksums(version, output):
    output = Path(output)
    lines = []
    for name in release_names(version):
        path = output / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing or empty release download: {name}")
        with path.open("rb") as source:
            lines.append(f"{hashlib.file_digest(source, 'sha256').hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    version, output, helper, novnc = sys.argv[1:]
    package_laptop(version, output, helper, novnc)
    write_checksums(version, output)
