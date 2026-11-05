from types import SimpleNamespace

import pytest
from kivy.config import Config

from carveracontroller.updates import RELEASES_URL, Release

from .conftest import capture_screenshot, pump_frames, set_window_size


@pytest.fixture
def updates(kivy_app, monkeypatch):
    import carveracontroller.main as main
    from carveracontroller.translation import tr

    app = kivy_app
    previous_language = tr.lang
    tr.switch_lang("en")
    root = app.root
    root.stop_update_checks()
    original = (root.ctl_version, root.fw_version, app.is_community_firmware, app.kiosk_profile)
    root.ctl_version = "1.0.0.dev4"
    root.fw_upd_text = ""
    root.fw_version_new = ""
    root.upgrade_popup.fw_upd_text.text = ""
    requests = []

    def request(url, **callbacks):
        value = SimpleNamespace(url=url, callbacks=callbacks, resp_headers={}, cancel=lambda: None)
        requests.append(value)
        return value

    monkeypatch.setattr(main, "UrlRequest", request)
    monkeypatch.setattr(root._release_check, "request_factory", request)
    yield app, root, requests
    root.stop_update_checks()
    root.upgrade_popup.dismiss()
    root.ctl_version, root.fw_version, app.is_community_firmware, app.kiosk_profile = original
    app.ctl_has_update = app.fw_has_update = False
    root.refresh_firmware_info()
    tr.switch_lang(previous_language)


def test_manual_retry_failure_and_stale_firmware_response(updates):
    app, root, requests = updates
    root.check_for_updates()
    old_fw = requests[0]
    controller = requests[-1]
    controller.callbacks["on_failure"](controller, {"message": "rate limited"})
    assert not app.ctl_has_update
    assert "Unable to check" in root.upgrade_popup.ctl_version_txt.text
    assert not root.upgrade_popup.check_button.disabled
    root.check_for_updates()
    old_fw.callbacks["on_success"](old_fw, "[99.0.0]")
    assert root.fw_upd_text == ""
    assert not app.fw_has_update
    latest_fw = requests[-2]
    root.fw_version = "2.2.0c"
    app.is_community_firmware = True
    latest_fw.callbacks["on_success"](latest_fw, "[2.3.0]\nFirmware changes")
    assert app.fw_has_update and not app.ctl_has_update
    assert not root.ids.main_menu.notify
    root.open_update_popup()
    assert "Available: v2.3.0" in root.upgrade_popup.fw_version_txt.text
    root.fw_version = "2.3.0c"
    root.check_fw_version()
    assert not app.fw_has_update
    assert "Available" not in root.upgrade_popup.fw_version_txt.text
    controller = requests[-1]
    controller.callbacks["on_success"](controller, [])
    assert not root.upgrade_popup.check_button.disabled
    assert root._release_url == RELEASES_URL


@pytest.mark.parametrize("firmware,community", [("2.2.0c", True), ("9.0.0c", True), ("1.0.0", False), ("", False)])
def test_firmware_identity_never_compares_to_controller_or_opens_popup(updates, firmware, community, monkeypatch):
    import carveracontroller.main as main

    app, root, _ = updates
    monkeypatch.setattr(main.Popup, "open", lambda *args: pytest.fail("Unexpected compatibility popup"))
    root.fw_version = firmware
    app.is_community_firmware = community
    original = Config.get("carvera", "show_firmware_check")
    try:
        for enabled in ("0", "1"):
            Config.set("carvera", "show_firmware_check", enabled)
            root.onFirmwareDetected(firmware)
            assert (
                (firmware in root.upgrade_popup.fw_info.text)
                if firmware
                else ("not identified" in root.upgrade_popup.fw_info.text)
            )
            assert Config.get("carvera", "show_firmware_check") == enabled
    finally:
        Config.set("carvera", "show_firmware_check", original)


def test_controller_update_is_available_while_disconnected_and_only_opens_release_page(updates, monkeypatch):
    import carveracontroller.main as main

    app, root, _ = updates
    url = RELEASES_URL + "/tag/kiosk-v1.0.0.dev5"
    root.show_controller_release(Release("1.0.0.dev5", url, "Release notes"), False)
    pump_frames(2)
    assert app.ctl_has_update and root.ids.main_menu.notify
    assert root.upgrade_popup.ctl_upd_text.text == "Release notes"
    opened = []
    monkeypatch.setattr(main.webbrowser, "open", lambda url, **kwargs: opened.append(url))
    root.open_download()
    assert opened == [url]


def test_updates_desktop_layout(updates):
    app, root, _ = updates
    set_window_size((1920, 1080))
    root.show_controller_release(Release("1.0.0.dev5", RELEASES_URL, "Release notes"), False)
    root.fw_version = "2.2.0c"
    app.is_community_firmware = True
    root.open_update_popup()
    pump_frames(5)
    assert root.upgrade_popup.check_button.text == "Check for Updates"
    capture_screenshot(app, "updates-desktop")


@pytest.mark.parametrize("size,scale", [((1920, 1200), 1), ((1920, 1080), 1), ((1920, 1200), 1.25)])
def test_updates_touch_layout(updates, mobile, size, scale):
    from kivy.metrics import Metrics
    from kivy.uix.button import Button
    from kivy.uix.tabbedpanel import TabbedPanel

    app, root, _ = updates
    previous = (Metrics.density, Metrics.fontscale)
    app.kiosk_profile = True
    Metrics.density = 1.5
    Metrics.fontscale = scale
    try:
        set_window_size(size)
        root.fw_version = "2.2.0c"
        app.is_community_firmware = True
        root.fw_upd_text = "[2.2.0]\nFirmware release notes"
        root.check_fw_version()
        root.show_controller_release(Release("1.0.0.dev5", RELEASES_URL, "Changes\n" * 40), False)
        root.open_update_popup()
        pump_frames(8)
        popup = root.upgrade_popup
        panel = next(widget for widget in popup.walk() if isinstance(widget, TabbedPanel))
        panel.switch_to(next(tab for tab in panel.tab_list if tab.text == "Controller"))
        pump_frames(3)
        assert popup.check_button.text == "Check for Updates"
        assert popup.width <= size[0] and popup.height <= size[1]
        for button in (
            widget
            for widget in popup.walk()
            if isinstance(widget, Button) and widget.text in ("Open release page", "Close", "Check for Updates")
        ):
            assert button.width > 0 and button.height > 0
        capture_screenshot(app, f"updates-{size[1]}-{scale}")
        panel.switch_to(next(tab for tab in panel.tab_list if tab.text == "Firmware"))
        pump_frames(3)
        capture_screenshot(app, f"updates-firmware-{size[1]}-{scale}")
    finally:
        root.upgrade_popup.dismiss()
        Metrics.density, Metrics.fontscale = previous
