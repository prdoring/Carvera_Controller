"""Reject changed release identities, existing drafts and altered laptop exports."""

import hashlib
import io
import json
import zipfile

import pytest

from scripts import kiosk_full_release, kiosk_publication


@pytest.mark.parametrize("fetched,local", [("a", "a"), ("b", "a"), ("a", "b")])
def test_final_tag_check_reads_the_remote_again_without_rejecting_its_own_draft(monkeypatch, fetched, local):
    commands = []
    tag, expected = "kiosk-v1.2.3.dev1", "a" * 40
    monkeypatch.setattr(kiosk_publication.subprocess, "run", lambda args, **_kwargs: commands.append(args))
    monkeypatch.setattr(kiosk_publication, "git", lambda *_args: fetched * 40)
    monkeypatch.setattr(kiosk_publication, "resolve", lambda *_args: {"commit": local * 40})
    monkeypatch.setattr(
        kiosk_publication,
        "require_unpublished",
        lambda *_args: pytest.fail("The final source check must allow the publisher's existing draft"),
    )
    if fetched == local == "a":
        kiosk_publication.recheck(tag, expected, "full")
    else:
        with pytest.raises(ValueError, match="tag changed"):
            kiosk_publication.recheck(tag, expected, "full")
    assert commands == [["git", "fetch", "--no-tags", "origin", "refs/tags/" + tag]]


@pytest.mark.parametrize("tag", ["main", "kiosk-v01.2.3", "kiosk-v1.2.3.dev01", "kiosk-v1.2.3;echo", "kiosk-v1.2"])
def test_noncanonical_tag_never_reaches_git(monkeypatch, tag):
    monkeypatch.setattr(kiosk_publication, "git", lambda *_args: pytest.fail("Invalid tag reached Git"))
    with pytest.raises(ValueError, match="canonical"):
        kiosk_publication.resolve(tag, "full")


@pytest.mark.parametrize("draft", [False, True])
def test_existing_release_or_draft_is_rejected_across_pages(monkeypatch, draft):
    monkeypatch.setenv("GH_TOKEN", "isolated-test-token")
    calls = []

    def response(request, timeout):
        assert request.get_header("Authorization") == "Bearer isolated-test-token"
        assert timeout == 20
        calls.append(request.full_url)
        value = (
            [{"tag_name": "older", "draft": False}] * 100
            if len(calls) == 1
            else [{"tag_name": "kiosk-v1.2.3.dev1", "draft": draft}]
        )
        return io.BytesIO(json.dumps(value).encode())

    monkeypatch.setattr(kiosk_publication.urllib.request, "urlopen", response)
    with pytest.raises(ValueError, match="already has"):
        kiosk_publication.require_unpublished("kiosk-v1.2.3.dev1")
    assert len(calls) == 2


def test_release_inspection_fails_closed_without_authentication(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(
        kiosk_publication.urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("No anonymous draft inspection")
    )
    with pytest.raises(ValueError, match="GH_TOKEN"):
        kiosk_publication.require_unpublished("kiosk-v1.2.3.dev1")


@pytest.mark.parametrize("changed", [None, "commit", "payload"])
def test_laptop_identity_and_every_exported_byte_are_verified(tmp_path, changed):
    names = {
        "kiosk.py",
        "kiosk_admin.py",
        "bootstrap/bootstrap.sh",
        "bootstrap/admin_accounts.py",
        "bootstrap/admin_bootstrap.py",
        "bootstrap/system_update.py",
        "bootstrap/setup_protocol.py",
        "bootstrap/settings.py",
        "kioskdesktop/viewer.py",
        "kioskdesktop/viewer_server.py",
        "novnc/vnc.html",
        "novnc/core/rfb.js",
        "laptop-requirements.txt",
    }
    original = {name: ("fixture " + name).encode() for name in names}
    metadata = {
        "format": 1,
        "version": "1.2.3.dev1",
        "commit": "b" * 40 if changed == "commit" else "a" * 40,
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in original.items()},
    }
    archive = tmp_path / "laptop.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("laptop/laptop-build.json", json.dumps(metadata))
        for name, data in original.items():
            output.writestr(
                "laptop/" + name, b"modified payload" if changed == "payload" and name == "kiosk.py" else data
            )
    if changed:
        with pytest.raises(ValueError):
            kiosk_full_release.laptop_identity(archive, "1.2.3.dev1", "a" * 40)
    else:
        kiosk_full_release.laptop_identity(archive, "1.2.3.dev1", "a" * 40)
