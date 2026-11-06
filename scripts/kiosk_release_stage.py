"""Select an exact release inventory and verify uploaded copies before publishing."""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.kiosk_full_release import assemble, required


def hashes(folder):
    result = {}
    for path in folder.iterdir():
        if path.is_symlink() or not path.is_file():
            raise ValueError("Release assets must be regular files")
        with path.open("rb") as source:
            result[path.name] = hashlib.file_digest(source, "sha256").hexdigest()
    return result


def stage(incoming, output, mode, version, commit):
    app = f"carvera-kiosk-app-{version}.tar.gz"
    selected = (
        required(version) - {"setup-release.json", "NOTICES.txt", "SHA256SUMS"}
        if mode == "full"
        else {app, app + ".sha256", f"bundle-{version}.json"}
    )
    allowed = selected | {
        "bundle.json",
        f"bundle-{version}.json",
        *(f"carvera-kiosk-{kind}-{version}.tar.gz.sha256" for kind in ("app", "system", "updater")),
    }
    actual = {path.name for path in incoming.iterdir()}
    if not selected <= actual or actual - allowed:
        raise ValueError("Downloaded build artifacts have a missing, mixed-version or unexpected inventory")
    size = sum((incoming / name).stat().st_size for name in selected)
    if shutil.disk_usage(output.parent).free < size * 2 + 256 * 1024**2:
        raise OSError("Not enough publication staging space for the output and verification download")
    output.mkdir(exist_ok=False)
    for name in sorted(selected):
        source = incoming / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("Build artifacts must be regular files")
        shutil.copyfile(source, output / name)
    if mode == "full":
        assemble(output, version, commit)
    else:
        from scripts.kiosk_release import verify_bundle

        verify_bundle("kiosk-v" + version, commit, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs=2, type=Path)
    parser.add_argument("--incoming", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("full", "app-only"))
    parser.add_argument("--version")
    parser.add_argument("--commit")
    args = parser.parse_args()
    if args.compare:
        if hashes(args.compare[0]) != hashes(args.compare[1]):
            raise SystemExit("Uploaded release assets differ from the verified local inventory")
    else:
        if any(getattr(args, name) is None for name in ("incoming", "output", "mode", "version", "commit")):
            parser.error("Supply the complete staging inputs")
        stage(args.incoming, args.output, args.mode, args.version, args.commit)
