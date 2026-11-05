from types import SimpleNamespace

import pytest

from carveracontroller.updates import (
    MAX_PAGES,
    MAX_RESPONSE_BYTES,
    ReleaseCheck,
    asset_name,
    release_version,
    select_release,
)


def release(version="1.0.0.dev5", platform="linux", architecture="aarch64", kiosk=True, checksum=True, **overrides):
    name = asset_name(version, platform, architecture, kiosk)
    names = [name, name + ".sha256"] if checksum else [name]
    item = {
        "tag_name": "kiosk-v" + version,
        "draft": False,
        "prerelease": ".dev" in version or "rc" in version,
        "body": "Release notes",
        "assets": [{"name": name, "size": 10, "state": "uploaded"} for name in names],
    }
    return dict(item, **overrides)


@pytest.mark.parametrize("tag", ["v2.2.0", "fork-v1.0.0", "dev", "kiosk-v1.0", "kiosk-v1.0.0+local", None])
def test_reject_non_fork_release_tags(tag):
    with pytest.raises(ValueError):
        release_version(tag)


def test_versions_have_prerelease_ordering():
    tags = ["1.0.0.dev2", "1.0.0.dev4", "1.0.0rc1", "1.0.0rc2", "1.0.0", "1.0.1.dev1"]
    parsed = [release_version("kiosk-v" + version) for version in tags]
    assert parsed == sorted(parsed)
    assert len(set(parsed)) == len(parsed)


@pytest.mark.parametrize(
    "installed,expected", [("1.0.0.dev4", "1.1.0.dev1"), ("1.0.0rc1", "1.1.0.dev1"), ("1.0.0", "1.0.1")]
)
def test_channel_and_highest_version_not_publication_order(installed, expected):
    items = [release("1.0.1"), release("1.1.0.dev1"), release("1.0.0"), release("0.9.0")]
    assert select_release(items, installed, "linux", "aarch64", True).version == expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"draft": True},
        {"tag_name": "v2.2.0"},
        {"assets": []},
        {"assets": None},
        {"body": []},
        {"assets": [{"name": "carvera-kiosk-app-1.0.0.dev5.tar.gz", "size": 0, "state": "uploaded"}]},
    ],
)
def test_ineligible_release_does_not_light_dot(overrides):
    assert select_release([release(**overrides)], "1.0.0.dev4", "linux", "aarch64", True) is None


def test_kiosk_requires_app_and_checksum_but_accepts_full_release_checksums():
    item = release(checksum=False)
    assert select_release([item], "1.0.0.dev4", "linux", "aarch64", True) is None
    item["assets"].append({"name": "SHA256SUMS", "size": 200, "state": "uploaded"})
    assert select_release([item], "1.0.0.dev4", "linux", "aarch64", True).version == "1.0.0.dev5"


def test_linux_desktop_package_cannot_update_kiosk():
    item = release(platform="linux", kiosk=False)
    assert select_release([item], "1.0.0.dev4", "linux", "aarch64", True) is None
    assert select_release([item], "1.0.0.dev4", "linux", "aarch64").version == "1.0.0.dev5"


@pytest.mark.parametrize(
    "platform,architecture,suffix",
    [
        ("win", "AMD64", "-windows-x64.exe"),
        ("win", "x86", "-windows-x86.exe"),
        ("macosx", "arm64", "-AppleSilicon.dmg"),
        ("macosx", "x86_64", "-Intel.dmg"),
        ("linux", "x86_64", "-x86_64.appimage"),
        ("android", "aarch64", ".apk"),
    ],
)
def test_matching_platform_asset(platform, architecture, suffix):
    assert asset_name("1.0.0", platform, architecture).endswith(suffix)
    item = release("1.0.1", platform, architecture, False)
    assert select_release([item], "1.0.0", platform, architecture).version == "1.0.1"


def test_no_update_for_source_current_or_unsupported_architecture():
    for installed in ("0.0.0", "1.0.0.dev5", "1.0.0"):
        assert select_release([release()], installed, "linux", "aarch64", True) is None
    assert select_release([release()], "1.0.0.dev4", "linux", "x86_64", True) is None
    assert asset_name("1.0.0", "win", "ARM64") is None


@pytest.fixture
def checker():
    requests, results = [], []

    def factory(url, **callbacks):
        req = SimpleNamespace(url=url, callbacks=callbacks, resp_headers={}, cancelled=False)
        req.cancel = lambda: setattr(req, "cancelled", True)
        requests.append(req)
        return req

    check = ReleaseCheck(factory)
    done = lambda value, error: results.append((value, error))
    return check, requests, results, done


def respond(req, data, links=""):
    req.resp_headers = {"link": links}
    req.callbacks["on_success"](req, data)


def test_pagination_selects_newest_matching_asset(checker):
    check, requests, results, done = checker
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    respond(requests[-1], [release()], '<https://api.github.com/ignored>; rel="next"')
    assert len(requests) == 2 and not results
    assert requests[-1].url.endswith("page=2")
    respond(requests[-1], [release("1.0.0rc1")])
    assert results[0][0].version == "1.0.0rc1"
    assert results[0][1] is False


def test_pagination_header_is_case_insensitive(checker):
    check, requests, results, done = checker
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    req = requests[-1]
    req.resp_headers = {"Link": '<next>; rel="next"'}
    req.callbacks["on_success"](req, [])
    assert len(requests) == 2 and not results
    respond(requests[-1], [release()])
    assert results[0][0].version == "1.0.0.dev5"


@pytest.mark.parametrize("event", ["on_error", "on_failure"])
def test_network_failure_allows_retry(checker, event):
    check, requests, results, done = checker
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    requests[-1].callbacks[event](requests[-1], "failure")
    assert results == [(None, True)]
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    respond(requests[-1], [release()])
    assert results[-1][0].version == "1.0.0.dev5"


@pytest.mark.parametrize("payload", [{"message": "rate limited"}, "not json", [None], [{}] * 101])
def test_invalid_api_response_is_not_reported_as_current(checker, payload):
    check, requests, results, done = checker
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    respond(requests[-1], payload)
    assert results == [(None, True)]


def test_superseded_cancelled_and_completed_callbacks_are_ignored(checker):
    check, requests, results, done = checker
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    old = requests[-1]
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    assert old.cancelled
    respond(old, [release("99.0.0")])
    old.callbacks["on_error"](old, "late failure")
    assert not results
    latest = requests[-1]
    respond(latest, [release()])
    latest.callbacks["on_error"](latest, "late failure")
    assert len(results) == 1
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    check.cancel()
    respond(requests[-1], [release()])
    assert len(results) == 1


def test_bounded_pagination_and_response_size(checker):
    check, requests, results, done = checker
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    for _ in range(MAX_PAGES):
        respond(requests[-1], [], '<next>; rel="next"')
    assert len(requests) == MAX_PAGES
    assert results == [(None, True)]
    check.start("1.0.0.dev4", "linux", "aarch64", True, done)
    req = requests[-1]
    req.callbacks["on_progress"](req, MAX_RESPONSE_BYTES + 1, -1)
    assert req.cancelled and results[-1] == (None, True)


def test_source_build_skips_network_and_invalid_version_reports_error(checker):
    check, requests, results, done = checker
    check.start("0.0.0", "linux", "aarch64", True, done)
    assert not requests and results == [(None, False)]
    check.start("not-a-version", "linux", "aarch64", True, done)
    assert not requests and results[-1] == (None, True)
