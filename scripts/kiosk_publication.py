"""Resolve release inputs once and recheck the tag immediately before publication."""

import argparse
import json
import os
import re
import subprocess
import urllib.request


def git(*arguments):
    return subprocess.check_output(["git", *arguments], text=True).strip()


def resolve(tag, mode):
    number = r"(?:0|[1-9][0-9]*)"
    if not re.fullmatch(
        r"kiosk-v" + number + r"\." + number + r"\." + number + r"(?:(?:\.dev|rc)" + number + r")?", tag
    ):
        raise ValueError("Use a canonical kiosk-vX.Y.Z, .devN or rcN tag")
    commit = git("rev-parse", tag + "^{commit}")
    if not re.fullmatch("[a-f0-9]{40}", commit):
        raise ValueError("A full source commit is required")
    subprocess.run(["git", "merge-base", "--is-ancestor", commit, "origin/main"], check=True)
    release_version = tag[len("kiosk-v") :]
    preview = ".dev" in release_version or "rc" in release_version
    if mode not in {"full", "app-only"} or (mode == "full" and not preview):
        raise ValueError("Unsigned desktop/full releases must be prereleases until signing is configured")
    return {"version": release_version, "commit": commit, "prerelease": preview, "mode": mode, "tag": tag}


def recheck(tag, expected, mode):
    subprocess.run(["git", "fetch", "--no-tags", "origin", "refs/tags/" + tag], check=True)
    actual = git("rev-parse", "FETCH_HEAD^{commit}")
    if actual != expected or resolve(tag, mode)["commit"] != expected:
        raise ValueError("The release tag changed after its build started")


def require_unpublished(tag):
    headers = {"User-Agent": "Carvera-Kiosk-Publication", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GH_TOKEN")
    if not token:
        raise ValueError("Authenticated release inspection requires GH_TOKEN")
    headers["Authorization"] = "Bearer " + token
    for page in range(1, 11):
        request = urllib.request.Request(
            f"https://api.github.com/repos/prdoring/Carvera_Controller/releases?per_page=100&page={page}",
            headers=headers,
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(4 * 1024**2 + 1)
        if len(data) > 4 * 1024**2:
            raise ValueError("The release catalogue exceeded its inspection limit")
        releases = json.loads(data)
        if (
            not isinstance(releases, list)
            or len(releases) > 100
            or any(not isinstance(item, dict) for item in releases)
        ):
            raise ValueError("Invalid release catalogue")
        if any(item.get("tag_name") == tag for item in releases):
            raise ValueError("This tag already has a draft or published release; use a new version")
        if len(releases) < 100:
            return
    raise ValueError("Release inspection exceeded its pagination limit")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "recheck"))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--mode", choices=("full", "app-only"), required=True)
    parser.add_argument("--commit")
    args = parser.parse_args()
    value = resolve(args.tag, args.mode)
    if args.action == "recheck":
        recheck(args.tag, args.commit, args.mode)
    require_unpublished(args.tag)
    print(json.dumps(value))
