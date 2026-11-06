"""The desktop presentation is derived from the kiosk without importing its app."""

import sys

import pytest

pytest.importorskip("tkinter", reason="The separate desktop runtime needs Tk", exc_type=ImportError)

from kioskdesktop import theme


def test_theme_uses_canonical_colors_without_loading_controller():
    before = set(sys.modules)
    value = theme.colors()
    assert value["BACKGROUND"] == "#222829"
    assert value["ACCENT"] == "#d69963"
    assert value["ERROR"] == "#f18a73"
    assert not any(name.startswith(("kivy", "carveracontroller")) for name in set(sys.modules) - before)


def test_packaged_theme_is_identical_to_canonical_source(tmp_path):
    from scripts.build_kiosk_desktop import ROOT, stage_theme

    destination = tmp_path / "slate"
    stage_theme(destination)
    for name in ("ui/theme.py", "data/fonts/IBMPlexSans-Regular.ttf", "data/fonts/OFL.txt", "data/theme/button.png"):
        assert (destination / name).read_bytes() == (ROOT / "carveracontroller" / name).read_bytes()
