"""Validate an application-only release without changing a kiosk or publishing it."""

import argparse
import ast
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile
from pathlib import Path

from carveracontroller.updates import TAG_PREFIX, release_version


def checkout_commit(tag):
    release_version(tag)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    tagged = subprocess.check_output(["git", "rev-parse", tag + "^{commit}"], text=True).strip()
    if commit != tagged or subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():
        raise ValueError("Release builds require a clean checkout of the release tag")
    return commit


def verify_bundle(tag, commit, output):
    release_version(tag)
    version = tag[len(TAG_PREFIX) :]
    output = Path(output)
    name = f"carvera-kiosk-app-{version}.tar.gz"
    bundle = output / name
    with bundle.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if (output / (name + ".sha256")).read_text().strip() != f"{digest}  {name}":
        raise ValueError("Application archive checksum does not match")
    manifest = json.loads((output / f"bundle-{version}.json").read_text())
    if (manifest["version"], manifest["commit"], manifest["architecture"], manifest["python"]) != (
        version,
        commit,
        "aarch64",
        "3.13",
    ):
        raise ValueError("Bundle identity does not match the release")
    with tarfile.open(bundle, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        if len(names) != len(members) or any(not member.isfile() for member in members):
            raise ValueError("Bundle contains duplicate entries or non-files")
        if names != {"bundle.json", *manifest["sha256"]}:
            raise ValueError("Bundle contents do not match its manifest")
        if json.load(archive.extractfile("bundle.json")) != manifest:
            raise ValueError("Published and archived manifests differ")
        application_found = False
        for member in members:
            if member.name == "bundle.json":
                continue
            path = Path(member.name)
            if len(path.parts) != 2 or path.parts[0] != "wheels" or path.suffix != ".whl":
                raise ValueError("Unexpected bundle entry")
            data = archive.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != manifest["sha256"][member.name]:
                raise ValueError("Wheel checksum does not match")
            with zipfile.ZipFile(io.BytesIO(data)) as wheel:
                if wheel.testzip() is not None:
                    raise ValueError("Damaged wheel")
                if path.name.startswith("carvera_controller_community-"):
                    source = ast.parse(wheel.read("carveracontroller/__version__.py").decode())
                    values = {
                        target.id: ast.literal_eval(statement.value)
                        for statement in source.body
                        if isinstance(statement, ast.Assign)
                        for target in statement.targets
                        if isinstance(target, ast.Name)
                    }
                    if values.get("__release_version__") != version or values.get("__version__") != version:
                        raise ValueError("Application version metadata does not match")
                    application_found = True
        if not application_found:
            raise ValueError("Application wheel is missing")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("tag")
    parser.add_argument("--output", default="dist/kiosk")
    args = parser.parse_args()
    version = release_version(args.tag)
    commit = checkout_commit(args.tag)
    if args.action == "verify":
        verify_bundle(args.tag, commit, args.output)
    print(json.dumps({"version": str(version), "prerelease": version.is_prerelease, "commit": commit}))


if __name__ == "__main__":
    main()
