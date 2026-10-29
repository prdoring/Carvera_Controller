"""Build the application wheel and an offline ARM64 deployment bundle."""

import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path


def main(version, commit, output):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}(?:[a-zA-Z0-9.+-]*)", version):
        raise ValueError("Invalid version")
    root = Path.cwd()
    project = root / "pyproject.toml"
    project.write_text(re.sub(r'(?m)^version = "[^"]+"', f'version = "{version}"', project.read_text()), encoding="utf-8")
    (root / "carveracontroller/__version__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    for source in (root / "carveracontroller/locales").rglob("*.po"):
        subprocess.run(["msgfmt", str(source), "-o", str(source.with_suffix(".mo"))], check=True)
    output = Path(output)
    wheels = output / "wheels"
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(wheels)], check=True)
    manifest = {
        "version": version, "commit": commit, "architecture": "aarch64", "python": "3.13",
        "sha256": {f"wheels/{path.name}": hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(wheels.glob("*.whl"))},
    }
    (output / "bundle.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with tarfile.open(output / f"carvera-kiosk-app-{version}.tar.gz", "w:gz") as archive:
        archive.add(output / "bundle.json", arcname="bundle.json")
        for wheel in sorted(wheels.glob("*.whl")):
            archive.add(wheel, arcname="wheels/" + wheel.name)


if __name__ == "__main__":
    main(*sys.argv[1:])
