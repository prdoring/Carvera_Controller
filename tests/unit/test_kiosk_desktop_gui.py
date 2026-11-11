"""Exercise the actual wizard's resizing, keyboard focus and persistent actions."""

import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

tk = pytest.importorskip("tkinter", reason="The separate desktop runtime needs Tk", exc_type=ImportError)
from tkinter import ttk

from kioskdesktop import devices, installer, profiles, releases, transport
from kioskdesktop.theme import register_fonts
from kioskdesktop.wizard import Wizard

pytestmark = pytest.mark.skipif(
    os.name != "nt" and not os.environ.get("DISPLAY"), reason="Requires a desktop display or Xvfb"
)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@pytest.mark.parametrize("scale", [1, 1.25, 1.5])
@pytest.mark.parametrize("geometry", ["640x540", "600x400"])
def test_wizard_keeps_actions_and_errors_visible_while_form_scrolls(scale, geometry, wizard):
    root, app = wizard
    root.geometry(geometry)
    app.theme.scale(scale)
    app.variables["network"].set("Wi-Fi")
    app.network_page()
    app.notice("Configuration incomplete. Retry with this setup profile.", error=True)
    settle(root)
    assert app.theme.sans.actual("family") == "IBM Plex Sans"
    for widget in (app.status, app.back, app.next, app.text_size):
        assert widget.winfo_viewable()
        assert root.winfo_rootx() <= widget.winfo_rootx()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
        assert widget.winfo_rooty() >= root.winfo_rooty()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    entries = [
        widget for widget in descendants(app.form.body) if isinstance(widget, ttk.Entry) and widget.winfo_viewable()
    ]
    assert len(entries) >= 4
    first = entries[0]
    assert first.tk_focusNext() is not first
    last = entries[-1]
    last.focus_force()
    settle(root)
    assert root.focus_get() is last
    assert last.winfo_rooty() >= app.form.canvas.winfo_rooty()
    assert last.winfo_rooty() + last.winfo_height() <= app.form.canvas.winfo_rooty() + app.form.canvas.winfo_height()
    app.access_page()
    settle(root)
    secret = [
        widget
        for widget in descendants(app.form.body)
        if isinstance(widget, ttk.Entry) and widget.cget("show") and widget.winfo_viewable()
    ]
    assert len(secret) == 2
    assert app.next.cget("text") == "Review setup"
    app.next.state(["disabled"])
    assert app.next.instate(["disabled"])


def test_network_fields_and_validation_follow_the_selected_network(wizard):
    root, app = wizard
    app.variables["hostname"].set("workshop-pi")
    app.variables["network"].set("Ethernet")
    app.network_page()
    settle(root)
    assert not app.wifi_box.winfo_ismapped()
    assert "workshop-pi.local" in app.address_preview.cget("text")
    assert app.valid_network()
    app.variables["network"].set("Wi-Fi")
    app.wifi_visibility()
    settle(root)
    assert app.wifi_box.winfo_ismapped()
    app.variables["ssid"].set("")
    assert not app.valid_network()
    app.variables["ssid"].set("Workshop")
    app.variables["password"].set("test-wifi-password")
    app.variables["country"].set("US")
    assert app.valid_network()


def test_review_prepares_but_only_held_card_confirmation_allows_writing(wizard, monkeypatch):
    _root, app = wizard
    app.profile = {"hostname": "test-pi"}
    app.profile_path = Path("test-setup/profile.json")
    app.release = SimpleNamespace(version="1.1.0.dev5")
    app.selected = SimpleNamespace(description="Test card", path="test-device", capacity=8 * 10**9)
    app.mode = "flash"
    prepared = []
    monkeypatch.setattr(app, "install", lambda: prepared.append(True))
    app.review()
    assert not any(isinstance(widget, ttk.Checkbutton) for widget in descendants(app.form.body))
    app.next.invoke()
    assert prepared == [True]
    consent = threading.Event()
    app.card_operation = SimpleNamespace(confirm=consent.set)
    app.confirm_media({"device": vars(app.selected), "erases": True})
    assert app.next.instate(["disabled"])
    app.confirm_write()
    assert not consent.is_set()
    checkbox = next(widget for widget in descendants(app.form.body) if isinstance(widget, ttk.Checkbutton))
    checkbox.invoke()
    app.next.invoke()
    assert consent.is_set()


@pytest.mark.parametrize(
    "phase,action,label",
    [
        (None, "flash", "Select card again"),
        ("writing", "flash", "Select card again"),
        ("verifying_write", "flash", "Select card again"),
        ("configuring", "flash", "Retry saving settings"),
        ("ejecting", "flash", "I safely removed the card"),
    ],
)
def test_card_failure_offers_the_right_recovery(wizard, phase, action, label):
    _root, app = wizard
    app.mode = action
    app.profile_path = Path("test-setup/profile.json")
    app.card_operation = SimpleNamespace(last_phase=phase, confirmed=threading.Event(), is_running=lambda: False)
    app.install_failed(RuntimeError("private-error-output"))
    assert app.next.cget("text") == label
    text = " ".join(widget.cget("text") for widget in descendants(app.form.body) if isinstance(widget, ttk.Label))
    assert "private-error-output" not in text
    if phase is None:
        assert "has not been erased" in text
    if phase == "configuring":
        assert app.mode == "configure"


@pytest.mark.parametrize(
    "phase,stage,expected",
    [
        ("complete", "prepared", "start"),
        ("ejecting", "prepared", "eject"),
        ("configuring", "prepared", "resume"),
        ("writing", "prepared", "resume"),
        (None, "prepared", "resume"),
        (None, "verified", "finish"),
    ],
)
def test_saved_setup_routes_from_matching_record(wizard, monkeypatch, tmp_path, phase, stage, expected):
    _root, app = wizard
    path = tmp_path / "profile.json"
    path.write_text("{}")
    profile = {"hostname": "test-pi", "id": "a" * 32, "stage": stage}
    monkeypatch.setattr(profiles, "load", lambda _path: profile)
    monkeypatch.setattr(installer, "load_release", lambda *_args: SimpleNamespace(version="1.1.0.dev5"))
    (tmp_path / "card-status.json").write_text(json.dumps({"id": profile["id"], "phase": phase}))
    routed = []
    for method, route in (
        ("card_ready", "start"),
        ("ejection_failed", "eject"),
        ("resume_page", "resume"),
        ("finish", "finish"),
    ):
        monkeypatch.setattr(app, method, lambda route=route: routed.append(route))
    app.open_profile(path)
    assert routed == [expected]
    assert app.variables["host"].get() == "test-pi.local"
    if expected == "resume":
        assert app.mode == ("configure" if phase == "configuring" else "flash")


def test_fingerprint_consent_precedes_passphrase_and_changed_identity_blocks(wizard):
    root, app = wizard
    host = {"address": "test-pi.local", "fingerprint": "SHA256:test", "public": "test-public-key"}
    app.profile = {"hostname": "test-pi"}
    app.boot_page()
    assert not any(isinstance(widget, ttk.Entry) and widget.cget("show") for widget in descendants(app.form.body))
    app.confirm_host(host)
    app.access_check_page(host)
    assert app.confirmed_host is None
    checkbox = next(widget for widget in descendants(app.form.body) if isinstance(widget, ttk.Checkbutton))
    checkbox.invoke()
    app.next.invoke()
    settle(root)
    assert app.confirmed_host == host
    assert any(isinstance(widget, ttk.Entry) and widget.cget("show") for widget in descendants(app.form.body))
    app.profile["host"] = {**host, "public": "original-public-key"}
    app.boot_page()
    app.confirm_host(host)
    assert app.confirmed_host is None
    assert "changed" in app.status.cget("text")
    assert app.profile["host"]["public"] == "original-public-key"


def test_offline_selection_requires_matching_image_and_refresh_clears_card(wizard, monkeypatch):
    _root, app = wizard
    card = SimpleNamespace(description="Test reader", path="test-card", capacity=8 * 10**9, eligible=True)
    release = SimpleNamespace(version="1.1.0.dev5", image=SimpleNamespace(minimum_capacity=4 * 10**9))
    monkeypatch.setattr(devices, "inventory", lambda _protected: [card])

    def offline(_previews):
        pytest.fail("Offline setup must not query the release server")

    monkeypatch.setattr(releases, "discover", offline)
    monkeypatch.setattr(app, "background", lambda function, success, *_args, **_kwargs: success(function()))
    app.begin("flash")
    app.card_box.current(0)
    app.cards_ready([card])
    assert app.card_box.current() == -1
    assert app.selected is None
    app.variables["source"].set("offline")
    app.source_changed()
    app.release = release
    app.card_box.current(0)
    app.card_continue()
    assert "both setup-release.json" in app.status.cget("text")
    assert app.profile is None


def test_removed_or_replaced_card_must_be_selected_again(wizard, monkeypatch):
    _root, app = wizard
    card = SimpleNamespace(
        description="Test reader", path="test-card", capacity=8 * 10**9, identity="original", eligible=True
    )
    replacement = SimpleNamespace(**{**vars(card), "identity": "replacement"})
    release = SimpleNamespace(version="1.1.0.dev5", image=SimpleNamespace(minimum_capacity=4 * 10**9))
    inventory = [card]
    monkeypatch.setattr(devices, "inventory", lambda _protected: inventory)
    monkeypatch.setattr(releases, "discover", lambda _previews: [release])
    monkeypatch.setattr(app, "background", lambda function, success, *_args, **_kwargs: success(function()))
    app.begin("flash")
    app.variables["source"].set("download")
    app.source_changed()
    app.card_box.current(0)
    inventory = [replacement]
    app.card_continue()
    assert app.selected is None
    assert app.card_box.current() == -1
    assert "removed or changed" in app.status.cget("text")


def test_finish_later_keeps_setup_and_small_window_actions_visible(wizard, monkeypatch):
    root, app = wizard
    app.profile = {"hostname": "test-pi", "stage": "prepared"}
    app.profile_path = Path("test-setup/profile.json")
    closed = []
    monkeypatch.setattr(app, "close", lambda: closed.append(True))
    root.geometry("600x400")
    app.theme.scale(1.5)
    app.card_ready()
    settle(root)
    for widget in (app.back, app.next):
        assert widget.winfo_rootx() >= root.winfo_rootx()
        assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
    assert app.next.cget("text") == "Check laptop access"
    app.back.invoke()
    assert closed == [True]
    assert app.profile["stage"] == "prepared"


def test_critical_confirmation_survives_a_full_progress_queue(wizard):
    _root, app = wizard
    import queue

    app.messages = queue.Queue(maxsize=1)
    app.report({"phase": "writing", "percent": 5})
    confirmation = {"phase": "awaiting_confirmation"}
    thread = threading.Thread(target=app.report, args=(confirmation,))
    thread.start()
    try:
        app.messages.get(timeout=1)
        thread.join(1)
        assert not thread.is_alive()
        assert app.messages.get(timeout=1) == ("progress", confirmation)
    finally:
        app.messages = queue.Queue(maxsize=64)


def settle(root):
    import time

    previous, stable, deadline = None, 0, time.monotonic() + 3

    def sample():
        nonlocal previous, stable
        root.update_idletasks()
        geometry = [
            (str(widget), widget.winfo_geometry(), widget.winfo_ismapped()) for widget in (root, *descendants(root))
        ]
        stable = stable + 1 if geometry == previous else 0
        previous = geometry
        if stable >= 4 or time.monotonic() >= deadline:
            root.quit()
        else:
            root.after(40, sample)

    root.after(0, sample)
    root.mainloop()
    assert stable >= 4, "The window layout did not settle"


@pytest.fixture(scope="module")
def wizard():
    register_fonts()
    root = tk.Tk()
    try:
        app = Wizard(root)
        root.wait_visibility()
        yield root, app
    finally:
        root.destroy()
