"""Exercise the actual wizard's resizing, keyboard focus and persistent actions."""

import os

import pytest

tk = pytest.importorskip("tkinter", reason="The separate desktop runtime needs Tk", exc_type=ImportError)
from tkinter import ttk

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
    entries = [widget for widget in descendants(app.form.body) if isinstance(widget, ttk.Entry)]
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
    secret = [widget for widget in descendants(app.form.body) if isinstance(widget, ttk.Entry) and widget.cget("show")]
    assert len(secret) == 4
    assert app.next.cget("text") == "Create keys and review"
    app.next.state(["disabled"])
    assert app.next.instate(["disabled"])


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
