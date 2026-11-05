"""Fork release selection and cancellable GitHub checks, independent of firmware."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from packaging.version import InvalidVersion, Version

REPOSITORY = "prdoring/Carvera_Controller"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases"
TAG_PREFIX = "kiosk-v"
MAX_PAGES = 10
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    notes: str


def release_version(tag: object) -> Version:
    """Reject inherited tags and non-release identifiers before parsing."""
    if not isinstance(tag, str) or not re.fullmatch(r"kiosk-v\d+\.\d+\.\d+(?:\.dev\d+|rc\d+)?", tag):
        raise ValueError("Expected kiosk-vX.Y.Z, kiosk-vX.Y.Z.devN or kiosk-vX.Y.ZrcN")
    version = Version(tag[len(TAG_PREFIX) :])
    if str(version) != tag[len(TAG_PREFIX) :]:
        raise ValueError("Use canonical release versions without leading zeros")
    return version


def asset_name(version: str, platform: str, architecture: str, kiosk: bool = False) -> str | None:
    architecture = architecture.lower()
    if kiosk:
        return f"carvera-kiosk-app-{version}.tar.gz" if architecture in ("aarch64", "arm64") else None
    prefix = f"carveracontroller-community-{version}"
    if platform == "android":
        return prefix + ".apk"
    if platform == "win":
        arch = {"amd64": "x64", "x86_64": "x64", "x86": "x86", "i386": "x86", "i686": "x86"}.get(architecture)
        return f"{prefix}-windows-{arch}.exe" if arch else None
    if platform == "macosx":
        arch = {"arm64": "AppleSilicon", "aarch64": "AppleSilicon", "x86_64": "Intel"}.get(architecture)
        return f"{prefix}-{arch}.dmg" if arch else None
    if platform == "linux":
        arch = {"amd64": "x86_64", "arm64": "aarch64"}.get(architecture, architecture)
        return f"{prefix}-{arch}.appimage"
    return None


def select_release(
    releases: list[dict[str, Any]],
    installed: str,
    platform: str,
    architecture: str,
    kiosk: bool = False,
) -> Release | None:
    current = Version(installed)
    if current == Version("0.0.0"):
        return None
    best = None
    best_version = current
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") is not False:
            continue
        try:
            candidate = release_version(item.get("tag_name"))
        except ValueError:
            continue
        if candidate <= best_version:
            continue
        if not current.is_prerelease and (candidate.is_prerelease or item.get("prerelease") is not False):
            continue
        tag = item["tag_name"]
        version = tag[len(TAG_PREFIX) :]
        assets = item.get("assets")
        if not isinstance(assets, list):
            continue
        names = {
            asset.get("name")
            for asset in assets
            if isinstance(asset, dict)
            and asset.get("state") == "uploaded"
            and isinstance(asset.get("size"), int)
            and asset["size"] > 0
            and isinstance(asset.get("name"), str)
        }
        name = asset_name(version, platform, architecture, kiosk)
        if name is None or name not in names or (kiosk and name + ".sha256" not in names and "SHA256SUMS" not in names):
            continue
        notes = item.get("body")
        if notes is None:
            notes = ""
        if not isinstance(notes, str):
            continue
        best_version = candidate
        best = Release(version, f"{RELEASES_URL}/tag/{tag}", notes)
    return best


class ReleaseCheck:
    """UrlRequest callbacks run on Kivy's event loop; cancel invalidates queued callbacks."""

    def __init__(self, request_factory: Callable[..., Any]):
        self.request_factory = request_factory
        self.request: Any = None
        self.generation = 0

    def cancel(self):
        self.generation += 1
        if self.request is not None:
            self.request.cancel()
            self.request = None

    def start(
        self,
        installed: str,
        platform: str,
        architecture: str,
        kiosk: bool,
        done: Callable[[Release | None, bool], None],
    ):
        self.cancel()
        generation = self.generation
        releases: list[dict[str, Any]] = []

        def finish(release: Release | None = None, error: bool = False):
            if generation != self.generation:
                return
            self.cancel()
            done(release, error)

        def failed(*args):
            finish(error=True)

        def progress(req, size, total):
            if generation == self.generation and max(size, total) > MAX_RESPONSE_BYTES:
                finish(error=True)

        def load(page):
            def loaded(req, result):
                if generation != self.generation:
                    return
                if not isinstance(result, list) or len(result) > 100 or any(not isinstance(x, dict) for x in result):
                    finish(error=True)
                    return
                releases.extend(result)
                links = next((value for key, value in (req.resp_headers or {}).items() if key.lower() == "link"), "")
                if 'rel="next"' in links.lower():
                    if page >= MAX_PAGES:
                        finish(error=True)
                    else:
                        load(page + 1)
                    return
                try:
                    release = select_release(releases, installed, platform, architecture, kiosk)
                except (InvalidVersion, TypeError, ValueError):
                    finish(error=True)
                else:
                    finish(release)

            try:
                self.request = self.request_factory(
                    f"{API_URL}?per_page=100&page={page}",
                    on_success=loaded,
                    on_error=failed,
                    on_failure=failed,
                    on_progress=progress,
                    timeout=10,
                    req_headers={"Accept": "application/vnd.github+json", "User-Agent": "Carvera-Controller-Kiosk"},
                )
            except Exception:
                finish(error=True)

        try:
            current = Version(installed)
        except InvalidVersion:
            finish(error=True)
            return
        if current == Version("0.0.0"):
            finish()
            return
        load(1)
