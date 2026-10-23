"""Rendered geometry and state transitions in the isolated full application."""

import pytest
from kivy.core.window import Window
from kivy.metrics import Metrics, dp
from kivy.uix.scrollview import ScrollView

from carveracontroller.ui.android_layout import DialogSurface, TouchActionRow
from tests.integration.conftest import pump_frames


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


def test_font_scale_can_grow_and_return_without_losing_a_draft(mobile):
    app, layout = mobile
    field = app.root.coord_popup.setx_popup.txt_offset
    field.text = "-19.25"
    layout.size_controls(field)
    normal = field.font_size
    Metrics.fontscale = 2
    layout.size_controls(field)
    assert field.font_size == pytest.approx(normal * 2)
    Metrics.fontscale = 1
    layout.size_controls(field)
    assert field.font_size == pytest.approx(normal)
    assert field.text == "-19.25"


def test_interface_scale_notifies_existing_layouts(mobile, monkeypatch):
    from kivy.config import Config

    from carveracontroller import main

    _, layout = mobile
    old = Config.get("carvera", "android_ui_scale")
    monkeypatch.setattr(main, "kivy_platform", "android")
    monkeypatch.setenv("CARVERA_ANDROID_DENSITY", "1.5")
    notifications = []
    def changed(_metrics, value):
        notifications.append(value)
    Metrics.bind(density=changed)
    try:
        Config.set("carvera", "android_ui_scale", "1.5")
        main.load_app_configs()
        assert Metrics.density == pytest.approx(2.25)
        assert notifications == [2.25]
        layout.update()
    finally:
        Metrics.unbind(density=changed)
        Config.set("carvera", "android_ui_scale", old)


def test_reopened_modal_stays_above_keyboard_during_resize(mobile):
    app, layout = mobile
    modal = app.root.input_popup
    for _ in range(4):
        modal.open(animation=False)
        pump_frames(3)
        modal.dismiss(force=True, animation=False)
    modal.open(animation=False)
    pump_frames(5)
    app.android_keyboard_height = Window.height * .45
    layout.update()
    Window.dispatch("on_resize", *Window.size)
    pump_frames(5)
    assert modal.y >= app.android_keyboard_height
    assert modal.top <= Window.height + 1


def test_switching_origin_tabs_prepares_the_new_content(mobile):
    from kivy.uix.tabbedpanel import TabbedPanel

    app, _ = mobile
    popup = app.root.coord_popup.origin_popup
    popup.open(animation=False)
    pump_frames(5)
    panel = next(widget for widget in popup.walk() if isinstance(widget, TabbedPanel))
    for tab in panel.tab_list:
        panel.switch_to(tab)
        pump_frames(6)
        surface = tab.content
        assert isinstance(surface, DialogSurface)
        assert surface._prepared
        assert isinstance(surface.children[0], TouchActionRow)
        assert isinstance(surface.children[-1], ScrollView)


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


def test_large_text_main_controls_contain_their_labels(mobile):
    from carveracontroller.ui.mobile_main import MobileMainLayout
    from carveracontroller.ui.touch import JogTouchButton

    app, layout = mobile
    app.root.content.current = "Control"
    Window.size = (1536, 864)
    Metrics.fontscale = 2
    Metrics.density = 2.25
    app.touch_target = 108
    layout.update()
    main = MobileMainLayout(app)
    try:
        pump_frames(12, sleep=.02)
        main._control_sizes()
        pump_frames(8)
        before = list(app.simulation.commands)
        assert all(group.get_root_window() is Window for group in app.root._mobile_action_groups)
        for key in ("jog_mode_btn", "jog_speed_btn", "kb_jog_btn", "pendant_jogging_en_btn"):
            button = app.root.ids[key]
            assert button.get_root_window() is Window
            assert button.height >= app.touch_target
            assert button.texture_size[1] <= button.height
        assert app.simulation.commands == before
        for widget in app.root.walk():
            if isinstance(widget, JogTouchButton):
                _, y = widget.to_window(*widget.pos)
                assert y >= app.root.ids.control_center.parent.y - 1
                assert y + widget.height <= Window.height
    finally:
        main.stop()


def test_compact_probing_chooser_keeps_lazy_settings_and_hides_collapsed_jog(mobile):
    from carveracontroller.addons.probing.ProbingPopup import DeferredProbeSettings, ProbingPopup

    app, layout = mobile
    Window.size = (640, 384)
    layout.update()
    popup = ProbingPopup(app.root.controller)
    popup.open(animation=False)
    pump_frames(12, sleep=.02)
    panel = popup.ids.tabbedpanelid
    assert panel.mobile_selector.height >= app.touch_target
    assert panel.tab_height == 0
    assert popup.ids.jog_panel.height == 0
    assert popup.ids.jog_panel.opacity == 0
    deferred = [w for tab in panel.tab_list for w in tab.content.walk() if isinstance(w, DeferredProbeSettings)]
    assert sum(w._settings is not None for w in deferred) == 1
    panel.mobile_selector.text = next(tab.text for tab in panel.tab_list if tab is not panel.current_tab)
    pump_frames(8)
    assert sum(w._settings is not None for w in deferred) == 2
    popup.toggle_jog_panel()
    pump_frames(8)
    assert popup.ids.jog_panel.opacity == 1
    assert popup.ids.jog_panel.height > 0
    popup.dismiss(force=True, animation=False)


def test_cmm_full_session_save_state_and_facing_generation_feedback(mobile):
    from carveracontroller.addons.cmm_workbench.core.session import CMMWorkbenchFeature
    from carveracontroller.addons.facing.FacingWizardPopup import FacingWizardPopup

    app, _ = mobile
    cmm = app.root._ensure_cmm_workbench_popup()
    cmm._mark_session_saved()
    cmm.session.features.append(CMMWorkbenchFeature.new_point("Test point", 1, 2, 3))
    cmm._update_save_state()
    assert cmm.session_dirty
    cmm._mark_session_saved()
    assert not cmm.session_dirty
    cmm.session.features[-1].label = "Renamed point"
    cmm._update_save_state()
    assert cmm.session_dirty
    facing = FacingWizardPopup()
    assert facing.program_state == "Not generated"
    facing._gcode_plain = "G1 X1"
    facing._mark_facing_gcode_stale_from_ui()
    assert "Out of date" in facing.program_state
    facing.open(animation=False)
    pump_frames(8)
    assert facing.ids.btn_generate_program.parent is not None
    assert facing.ids.btn_generate_program.get_root_window() is Window


def test_cmm_jog_overlay_is_bounded_and_keeps_existing_controls(mobile):
    from carveracontroller.ui.touch import JogTouchButton

    app, layout = mobile
    Window.size = (640, 384)
    cmm = app.root._ensure_cmm_workbench_popup()
    cmm.open(animation=False)
    pump_frames(5)
    cmm.open_jog_popup()
    pump_frames(10)
    layout.update()
    modal = cmm._jog_popup
    assert modal._mobile_jog_ready
    assert modal.y >= 0
    assert modal.top <= Window.height
    buttons = [w for w in modal.walk() if isinstance(w, JogTouchButton)]
    assert len(buttons) == 8
    for widget in buttons:
        x, y = widget.to_window(*widget.pos)
        assert x >= modal.x
        assert x + widget.width <= modal.right + 1
        assert y >= modal.y
        assert y + widget.height <= modal.top + 1
        assert widget.width >= app.touch_target
        assert widget.height >= app.touch_target
