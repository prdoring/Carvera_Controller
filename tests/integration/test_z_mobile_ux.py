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


def test_wcs_preflights_every_draft_and_preserves_descriptions(mobile, monkeypatch):
    from unittest.mock import Mock

    app, _ = mobile
    popup = app.root.wcs_settings_popup
    popup.original_values = {name: dict.fromkeys(("X", "Y", "Z", "A", "R"), 0.0) for name in ("G54", "G55")}
    for name in ("g54", "g55"):
        for axis in ("x", "y", "z", "a", "r"):
            field = popup.ids[f"{name}_{axis}"]
            field.disabled = False
            field.text = "0"
    send = Mock(return_value=True)
    monkeypatch.setattr(popup.controller, "executeCommand", send)
    popup.ids.g54_x.text = "-12.5"
    popup.ids.g55_z.text = "-."
    assert popup.apply_changes() is False
    send.assert_not_called()
    assert popup.ids.g55_z.validation_error
    assert popup.ids.g54_description.saves_immediately
    popup.ids.g55_z.text = "2.5"
    assert popup.apply_changes() is True
    assert [call.args[0] for call in send.call_args_list] == ["G10L2P1X-12.500", "G10L2P2Z2.500"]
    send.reset_mock()
    send.side_effect = [True, False]
    assert popup.apply_changes() is False
    assert "1/2" in popup.apply_error
    assert popup.ids.g54_x.text == "-12.5"
    assert popup.ids.g55_z.text == "2.5"


def test_wcs_reflow_preserves_existing_editors_and_drafts(mobile):
    app, _ = mobile
    popup = app.root.wcs_settings_popup
    field = popup.ids.g54_x
    field.text = "-17.125"
    for compact in (True, False, True, False, True):
        app.compact_layout = compact
        popup._workspace_layout.update()
        assert popup.ids.wcs_grid.cols == (1 if compact else 8)
        pump_frames(3)
        assert popup.ids.g54_x is field
        assert field.text == "-17.125"
        assert field.parent is not None


def test_main_reflow_and_disclosures_keep_views_and_send_no_commands(mobile):
    from carveracontroller.ui.mobile_main import MobileMainLayout

    app, _ = mobile
    main = MobileMainLayout(app)
    app.root.manual_cmd.text = "G0 X-12.5"
    viewer = app.root.gcode_viewer
    before = len(app.simulation.commands)
    try:
        for compact in (True, False, True):
            app.compact_layout = compact
            app.show_lines = not app.show_lines
            app.show_preview = True
            pump_frames(5)
            assert app.root.gcode_viewer is viewer
            assert app.root.manual_cmd.text == "G0 X-12.5"
        assert app.simulation.commands[before:] == []
    finally:
        app.compact_layout = False
        main.stop()
