"""Rendered geometry and state transitions in the isolated full application."""

import pytest
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.scrollview import ScrollView

from carveracontroller.ui.android_layout import AndroidTouchLayout, DialogSurface, TouchActionRow
from tests.integration.conftest import pump_frames


@pytest.fixture
def mobile(kivy_app):
    app = kivy_app
    original = (Window.size, Metrics.density, Metrics.fontscale, app.touch_target, app.android_touch)
    app.android_touch = True
    Metrics.density = 1
    app.touch_target = 48
    layout = AndroidTouchLayout(app)
    app._touch_layout = layout
    yield app, layout
    for modal in list(layout.dialogs):
        modal.dismiss(force=True, animation=False)
    app.android_keyboard_height = 0
    layout.stop()
    app._touch_layout = None
    Window.size, Metrics.density, Metrics.fontscale, app.touch_target, app.android_touch = original
    pump_frames(3)


def test_simulator_blocks_physical_connections_and_records_actions(kivy_app):
    sim = kivy_app.simulation
    with pytest.raises(RuntimeError, match="Physical connections"):
        kivy_app.root.controller.open(1, "192.0.2.1")
    before = len(sim.commands)
    kivy_app.root.controller.executeCommand("G54")
    assert sim.commands[before:] == ["G54"]


@pytest.mark.parametrize("size", [(800, 480), (1024, 600), (1920, 1080)])
def test_consequential_choices_have_bounded_body_and_fixed_footer(mobile, size):
    app, layout = mobile
    Window.size = size
    modal = app.root.unlock_popup
    modal.open(animation=False)
    pump_frames(8, sleep=.03)
    surface = modal.children[0]
    assert isinstance(surface, DialogSurface)
    assert sum(isinstance(w, ScrollView) for w in surface.walk()) == 1
    actions = [w for w in surface.walk() if isinstance(w, TouchActionRow)]
    for row in actions:
        assert row.height >= app.touch_target
        for button in row.children:
            assert button.height >= app.touch_target
            left, bottom = button.to_window(*button.pos)
            assert left >= modal.x - 1
            assert left + button.width <= modal.right + 1
    footer = surface.children[0]
    old_height = footer.height
    app.android_keyboard_height = Window.height * .45
    pump_frames(8, sleep=.03)
    assert modal.y >= app.android_keyboard_height
    assert footer.height == old_height
    assert footer.y >= modal.y
    assert footer.top <= modal.top
    layout.update()
    assert sum(isinstance(w, ScrollView) for w in surface.walk()) == 1


def test_large_text_choices_grow_instead_of_shrinking(mobile):
    app, _ = mobile
    Metrics.fontscale = 2
    modal = app.root.select_probe_popup
    modal.open(animation=False)
    pump_frames(8, sleep=.03)
    for row in (w for w in modal.walk() if isinstance(w, TouchActionRow)):
        row._columns()
        assert row.row_default_height >= dp(48)
        assert all(w.height >= dp(48) for w in row.children)
