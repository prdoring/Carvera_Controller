"""Check the working space and text which outer-window bounds cannot establish."""

import pytest
from kivy.core.window import Window
from kivy.metrics import Metrics, dp, sp
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView

from carveracontroller.ui.android_layout import DialogLabel, TouchActionRow, control_height
from tests.integration.conftest import pump_frames, set_window_size


def test_plain_explanation_does_not_reserve_a_touch_row(mobile):
    label = DialogLabel(text="Choose an option", width=500, size_hint_x=None)
    pump_frames(4)
    assert label.height == pytest.approx(label.texture_size[1] + dp(8))
    assert label.height < mobile[0].touch_target


def test_numeric_field_height_does_not_follow_neighbor_labels(mobile):
    from kivy.uix.gridlayout import GridLayout

    from carveracontroller.ui.android_layout import fit_form_grid
    from carveracontroller.ui.editing import EditingTextInput

    grid = GridLayout(cols=2, width=240, size_hint_x=None)
    field = EditingTextInput(input_filter='float', multiline=False)
    neighbor = Button(text='A long neighboring action ' * 12, text_size=(100, None))
    grid.add_widget(field)
    grid.add_widget(neighbor)
    fit_form_grid(grid)
    neighbor.texture_update()
    pump_frames(8)
    assert field.height == pytest.approx(control_height())
    neighbor.text *= 2
    neighbor.texture_update()
    pump_frames(8)
    assert field.height == pytest.approx(control_height())


def test_large_wcs_form_stays_within_scroll_bounds_after_opening(mobile):
    from carveracontroller.main import WCSSettingsPopup

    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    popup = WCSSettingsPopup(app.root.controller, app.root.wcs_settings_popup.wcs_names)
    popup._workspace_layout.update()
    popup.open(animation=False)
    pump_frames(60, sleep=.02)
    view = popup.ids.wcs_grid.parent.parent
    assert isinstance(view, ScrollView)
    assert 0 <= view.scroll_y <= 1
    label = popup._workspace_layout.cards[0].children[-1]
    _x, y = label.to_window(*label.pos)
    _vx, bottom = view.to_window(*view.pos)
    assert y < bottom + view.height and y + label.height > bottom


def test_short_actions_use_one_line_and_long_actions_wrap(mobile):
    row = TouchActionRow(width=650, size_hint_x=None)
    row.add_widget(Button(text="Close"))
    row.add_widget(Button(text="Apply"))
    pump_frames(5)
    assert row.cols == 2
    assert row.row_default_height == pytest.approx(control_height())
    Metrics.fontscale = 2
    row.children[0].text = "Apply all numerical coordinate offsets"
    row._columns()
    pump_frames(5)
    assert row.cols == 1
    assert all(button.texture_size[1] <= button.height for button in row.children)


def test_safe_area_is_preserved_when_the_keyboard_overlays_the_screen(mobile):
    app, layout = mobile
    old = list(app.safe_area_padding)
    try:
        set_window_size((1024, 600))
        app.safe_area_padding = [12, 24, 18, 30]
        app.android_keyboard_height = 240
        layout.update()
        assert app.root.pos == [12, 30]
        assert app.root.size == [994, 546]
        app.root.unlock_popup.open(animation=False)
        pump_frames(8)
        assert app.root.unlock_popup.y >= 240
        assert app.root.unlock_popup.top <= 576
    finally:
        app.safe_area_padding = old


def test_short_unlock_dialog_has_no_empty_scrolling_body(mobile):
    app, _ = mobile
    set_window_size((800, 480))
    modal = app.root.unlock_popup
    modal.open(animation=False)
    pump_frames(12)
    surface = modal.children[0]
    assert surface.actions is not None
    assert surface.height >= surface.body.height + surface.actions.height
    assert not surface.viewport.do_scroll_y
    assert modal.height < Window.height * .8


def test_input_dialog_has_stable_natural_height_and_no_idle_scrolling(mobile):
    app, _ = mobile
    set_window_size((800, 480))
    modal = app.root.input_popup
    modal.open(animation=False)
    pump_frames(20)
    height = modal.height
    pump_frames(20)
    assert modal.height == pytest.approx(height)
    assert modal.height < 260
    assert not modal.children[0].viewport.do_scroll_y
    app.android_keyboard_height = 240
    pump_frames(15)
    assert modal.y >= 240
    assert modal.children[0].actions.y >= modal.y
    assert modal.txt_content.height >= app.touch_target


def test_numeric_editor_does_not_reserve_desktop_spacers(mobile):
    from carveracontroller.ui.settings_fields import EditingSettingNumeric

    app, _ = mobile
    set_window_size((800, 480))
    app.root.config_popup.open(animation=False)
    pump_frames(8)
    setting = next(item for item in app.root.config_popup._all_setting_items() if type(item) is EditingSettingNumeric)
    setting._create_popup(None)
    pump_frames(20)
    assert setting.popup.height < 220
    assert len(setting.popup.content.body.children) == 1
    assert not setting.popup.content.viewport.do_scroll_y


def test_macro_editor_is_measured_before_a_scrolling_parent_exists(mobile):
    from carveracontroller.custom_widgets import SettingGCodeSnippet

    app, _ = mobile
    app.root.config_popup.open(animation=False)
    pump_frames(8)
    setting = next(item for item in app.root.config_popup._all_setting_items() if type(item) is SettingGCodeSnippet)
    setting.open_popup()
    pump_frames(20)
    assert setting.gcode_input.get_root_window() is Window
    assert setting.gcode_input.height >= app.touch_target
    assert setting._popup.content.actions is not None
    field = setting.gcode_input
    field.text = "G1 X-12.5"
    field.focus = True
    app.android_keyboard_height = 240
    pump_frames(24, sleep=.02)
    viewport = setting._popup.content.viewport
    cursor = field.to_window(*field.cursor_pos)
    assert field.text == "G1 X-12.5"
    assert viewport.y <= cursor[1] <= viewport.top


@pytest.mark.parametrize("size,density,font", [((800, 480), 1, 1), ((1920, 1080), 2.25, 2)])
def test_facing_reserves_a_working_form_and_contains_wrapped_choices(mobile, size, density, font):
    from carveracontroller.addons.facing.FacingWizardPopup import FacingWizardPopup

    app, layout = mobile
    set_window_size(size)
    Metrics.density, Metrics.fontscale = density, font
    app.touch_target = 48 * density
    layout.update()
    modal = FacingWizardPopup()
    modal.open(animation=False)
    pump_frames(18)
    field = modal.ids.txt_w
    parent = field.parent
    while not isinstance(parent, ScrollView):
        parent = parent.parent
    assert parent.height >= app.touch_target * 2
    assert field.height >= app.touch_target
    choices = [widget for widget in field.parent.children if isinstance(widget, Button)]
    assert all(widget.texture_size[1] <= widget.height for widget in choices)


def test_console_scene_is_the_mdi_page_after_transition(mobile):
    app, _ = mobile
    simulation = app.simulation
    simulation.app = app
    simulation._scenes = {}
    before = list(simulation.commands)
    simulation._action({"op": "show", "scene": "console"})
    pump_frames(30, sleep=.02)
    assert app.root.content.current == "File"
    assert app.root.cmd_manager.current == "manual_cmd_page"
    assert not app.root.content.transition.is_active
    assert simulation.commands == before


def test_cmm_live_position_button_stays_inside_its_row(mobile):
    app, layout = mobile
    set_window_size((800, 480))
    layout.update()
    modal = app.root._ensure_cmm_workbench_popup()
    modal.open(animation=False)
    pump_frames(15)
    row = modal.ids.manual_position_row
    assert max(child.right for child in row.children) <= row.right + 1
    assert min(child.x for child in row.children) >= row.x - 1


def test_cmm_live_position_text_fits_at_maximum_small_screen_scale(mobile):
    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    modal = app.root._ensure_cmm_workbench_popup()
    modal.open(animation=False)
    pump_frames(20, sleep=.02)
    label = modal.ids.lbl_wcs_live
    assert not label.opacity or label.texture_size[1] <= label.height
    if not label.opacity:
        assert modal.ids.position_details.opacity == 1
        expected = label.text.replace('  ', '\n')
        before = list(app.simulation.commands)
        modal.ids.position_details.dispatch('on_release')
        pump_frames(8)
        assert any(isinstance(widget, DialogLabel) and widget.text == expected
                   for surface in Window.children for widget in surface.walk())
        assert app.simulation.commands == before


def test_wide_tool_selector_does_not_keep_empty_tab_space(mobile):
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem

    from carveracontroller.ui.mobile_tools import operation_selector

    app, layout = mobile
    set_window_size((1920, 1080))
    layout.update()
    assert not app.compact_layout
    parent = BoxLayout()
    panel = TabbedPanel(do_default_tab=False, size_hint=(None, None), width=700)
    parent.add_widget(panel)
    for index in range(3):
        panel.add_widget(TabbedPanelItem(text=f'Operation {index}: ' + 'long translated parameter names ' * 4))
    pump_frames(6)
    operation_selector(panel)
    layout.size_controls(panel)
    assert panel.mobile_selector.height >= app.touch_target
    assert panel.tab_height == 0


@pytest.mark.parametrize('state,playing', [('Idle', False), ('Run', True), ('Pause', True)])
def test_compact_job_controls_keep_stop_inside_the_window(mobile, state, playing):
    from carveracontroller.CNC import CNC
    from carveracontroller.ui.mobile_main import MobileMainLayout

    app, layout = mobile
    original = app.state, app.playing, app.selected_remote_filename, CNC.vars['state']
    main = None
    try:
        set_window_size((800, 480))
        Metrics.density, Metrics.fontscale = 1.5, 2
        app.touch_target = 72
        app.root.config_loaded = True
        CNC.vars['state'] = app.state = state
        app.playing = playing
        app.selected_remote_filename = 'part.cnc'
        layout.update()
        main = MobileMainLayout(app)
        pump_frames(20)
        controls = [widget for widget in app.root.walk() if getattr(widget, 'android_label', '') and widget.opacity]
        assert controls
        for button in controls:
            left, bottom = button.to_window(*button.pos)
            assert left >= 0
            assert left + button.width <= Window.width, [(getattr(child, 'text', ''), child.width, child.size_hint_x) for child in button.parent.children]
            assert bottom >= 0
    finally:
        if main is not None:
            main.stop()
        app.state, app.playing, app.selected_remote_filename, CNC.vars['state'] = original


def test_late_probe_fields_receive_scaled_input_policy(mobile):
    from kivy.uix.textinput import TextInput

    from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

    app, layout = mobile
    Metrics.fontscale = 2
    modal = ProbingPopup(app.root.controller)
    modal.open(animation=False)
    pump_frames(12)
    panel = modal.ids.tabbedpanelid
    for tab in list(panel.tab_list)[:2]:
        panel.switch_to(tab)
        pump_frames(12)
        fields = [widget for widget in tab.content.walk() if isinstance(widget, TextInput)]
        assert fields
        assert all(field.font_size == pytest.approx(sp(16)) for field in fields)
        assert all(field.height >= app.touch_target for field in fields)


def test_cmm_largest_small_screen_retains_form_space(mobile):
    from carveracontroller.ui.android_layout import control_height

    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    modal = app.root._ensure_cmm_workbench_popup()
    modal.open(animation=False)
    pump_frames(20)
    field = modal.ids.t_manual_wx
    parent = field.parent
    while not isinstance(parent, ScrollView):
        parent = parent.parent
    assert parent.height >= control_height() * 2
    assert modal.ids.cmm_actions.rows is None
    assert modal.ids.cmm_actions.cols == 3
    assert modal.ids.cmm_actions.height == pytest.approx(modal.ids.cmm_actions.row_default_height)


def test_large_text_settings_prioritize_value_and_keep_description_accessible(mobile):
    from kivy.uix.settings import SettingItem

    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    popup = app.root.config_popup
    popup.open(animation=False)
    pump_frames(20)
    item = next(item for item in popup._all_setting_items() if isinstance(item, SettingItem) and item.desc and hasattr(item, '_mobile_info'))
    assert item._mobile_info.opacity == 1
    assert item.desc not in item.ids.labellayout.text
    assert item._mobile_value_row.height >= app.touch_target
    before = list(app.simulation.commands)
    item._mobile_info.dispatch('on_release')
    pump_frames(10)
    assert app.simulation.commands == before


@pytest.mark.parametrize('scene', ['numeric', 'input', 'cmm', 'facing', 'probing'])
def test_enlarged_small_screen_keeps_the_editor_in_view(mobile, scene):
    from kivy.uix.textinput import TextInput

    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    if scene == 'numeric':
        from carveracontroller.ui.settings_fields import EditingSettingNumeric

        app.root.config_popup.open(animation=False)
        pump_frames(8)
        setting = next(item for item in app.root.config_popup._all_setting_items() if type(item) is EditingSettingNumeric)
        setting._create_popup(None)
        modal, field = setting.popup, setting.textinput
    elif scene == 'input':
        modal = app.root.input_popup
        modal.open(animation=False)
        field = modal.txt_content
    elif scene == 'cmm':
        modal = app.root._ensure_cmm_workbench_popup()
        field = modal.ids.t_manual_wx
        modal.open(animation=False)
    elif scene == 'facing':
        from carveracontroller.addons.facing.FacingWizardPopup import FacingWizardPopup

        modal = FacingWizardPopup()
        modal.open(animation=False)
        field = modal.ids.txt_w
    else:
        from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

        modal = ProbingPopup(app.root.controller)
        modal.open(animation=False)
        pump_frames(12)
        field = next(widget for widget in modal.ids.tabbedpanelid.current_tab.content.walk() if isinstance(widget, TextInput))
    pump_frames(12)
    geometry = tuple(modal.pos), tuple(modal.size)
    field.focus = True
    pump_frames(12)
    if scene != 'input':
        pad = field._number_pad
        assert pad._is_open
        assert app.android_keyboard_height == 0
        assert (tuple(modal.pos), tuple(modal.size)) == geometry
        assert pad.x >= 0 and pad.y >= 0
        assert pad.right <= Window.width and pad.top <= Window.height
        return
    app.android_keyboard_height = 240
    pump_frames(24, sleep=.02)
    viewport = field.parent
    while not isinstance(viewport, ScrollView):
        viewport = viewport.parent
    left, bottom = viewport.to_window(*viewport.pos)
    x, y = field.to_window(*field.pos)
    assert viewport.height >= field.height
    assert bottom - 1 <= y
    assert y + field.height <= bottom + viewport.height + 1
    assert y >= app.android_keyboard_height
    assert y + field.height <= Window.height


def test_cmm_number_pad_stays_in_view_after_late_form_reflow(mobile):
    app, layout = mobile
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    modal = app.root._ensure_cmm_workbench_popup()
    modal.open(animation=False)
    pump_frames(12)
    field = modal.ids.t_manual_wx
    viewport = field.parent
    while not isinstance(viewport, ScrollView):
        viewport = viewport.parent
    field.focus = True
    pump_frames(24, sleep=.02)
    pad = field._number_pad
    body = viewport.children[0]
    original = list(body.padding)
    before = list(app.simulation.commands)
    try:
        body.padding = [original[0], original[1] + dp(160), original[2], original[3]]
        pump_frames(8)
        assert pad._is_open
        assert pad.x >= 0 and pad.y >= 0
        assert pad.right <= Window.width and pad.top <= Window.height
        assert app.android_keyboard_height == 0
        assert app.simulation.commands == before
    finally:
        body.padding = original



@pytest.mark.parametrize('scene', ['wcs', 'filename', 'mdi', 'settings'])
def test_remaining_editors_fit_above_enlarged_keyboard(mobile, scene):
    from carveracontroller.ui.mobile_main import MobileMainLayout

    app, layout = mobile
    attempts = list(app.simulation.attempts)
    set_window_size((800, 480))
    Metrics.density, Metrics.fontscale = 1.5, 2
    app.touch_target = 72
    layout.update()
    main = MobileMainLayout(app)
    try:
        if scene == 'wcs':
            app.is_community_firmware = True
            modal = app.root.wcs_settings_popup
            modal.open(animation=False)
            pump_frames(12)
            modal.apply_error = 'Connection interrupted. Only 1/2 changes were sent. Review the remaining offsets before applying again.'
            modal.original_values = {'G54': dict.fromkeys(('X', 'Y', 'Z', 'A', 'R'), 0.0)}
            field = modal.ids.g54_x
            field.text = '12.5'
            modal.check_for_changes()
        elif scene == 'filename':
            from carveracontroller.ui.LocalFilePicker import open_local_file_picker
            open_local_file_picker(title='Save session', default_name='session.json', on_confirm=lambda *_: None)
            pump_frames(12)
            modal = next(widget for widget in Window.children if getattr(widget, 'title', '') == 'Save session')
            field = modal.content.ids.ti_filename
        elif scene == 'mdi':
            app.root.content.current = 'File'
            app.show_lines = True
            app.root.cmd_manager.current = 'manual_cmd_page'
            field = app.root.manual_cmd
        else:
            modal = app.root.config_popup
            modal.open(animation=False)
            pump_frames(12)
            modal._mobile_settings.toggle_search()
            field = modal._mobile_settings.search
            settings_parents = modal._mobile_settings.close_button.parent, modal.btn_apply.parent
        pump_frames(12)
        field.focus = True
        if scene == 'wcs':
            pump_frames(12)
            pad = field._number_pad
            assert pad._is_open
            assert app.android_keyboard_height == 0
            assert pad.x >= 0 and pad.y >= 0
            assert pad.right <= Window.width and pad.top <= Window.height
            viewport = field.parent
            while not isinstance(viewport, ScrollView):
                viewport = viewport.parent
            assert modal.ids.wcs_apply_error.parent == viewport.children[0]
            assert app.simulation.attempts == attempts
            return
        before_keyboard_y = field.to_window(*field.pos)[1]
        app.android_keyboard_height = 240
        pump_frames(28, sleep=.02)
        x, y = field.to_window(*field.pos)
        assert y >= 239, (scene, field.pos, field.size)
        assert y + field.height <= Window.height + 1, (scene, field.pos, field.size)
        assert x >= -1 and x + field.width <= Window.width + 1
        assert field.width >= app.touch_target
        if scene == 'settings':
            settings = modal._mobile_settings
            if before_keyboard_y >= 240 + dp(8):
                assert (settings.close_button.parent, modal.btn_apply.parent) == settings_parents
            else:
                assert settings.close_button.parent == modal.btn_apply.parent == settings.search_row
            app.android_keyboard_height = 0
            pump_frames(16)
            assert settings.close_button.parent == settings.navigation
            assert modal.btn_apply.parent != settings.search_row
        assert app.simulation.attempts == attempts
    finally:
        main.stop()


@pytest.mark.parametrize("size,native_density", [((800, 480), 1), ((1024, 600), 1), ((1920, 1080), 1.5), ((1600, 900), 1)])
@pytest.mark.parametrize("interface_scale", [1, 1.25, 1.5])
@pytest.mark.parametrize("font_scale", [1, 1.5, 2])
def test_landscape_size_matrix_keeps_motion_targets_in_their_panel(mobile, size, native_density, interface_scale, font_scale):
    from carveracontroller.ui.mobile_main import MobileMainLayout
    from carveracontroller.ui.touch import JogTouchButton

    app, layout = mobile
    set_window_size(size)
    Metrics.density = native_density * interface_scale
    Metrics.fontscale = font_scale
    app.touch_target = 48 * Metrics.density
    app.root.content.current = "Control"
    layout.update()
    main = MobileMainLayout(app)
    try:
        pump_frames(10)
        for button in (widget for widget in app.root.walk() if isinstance(widget, JogTouchButton)):
            x, y = button.to_window(*button.pos)
            assert button.width >= app.touch_target - 1
            assert button.height >= app.touch_target - 1
            assert x >= -1 and x + button.width <= Window.width + 1
            assert y >= app.root.ids.control_center.parent.y - 1
            assert y + button.height <= app.root.ids.main_top_bar.y + 1
        assert not any(isinstance(widget, ScrollView) for widget in app.root.ids.control_center.walk(restrict=True))
        for button in (widget for widget in app.root.walk() if isinstance(widget, JogTouchButton)):
            parent = button.parent
            while parent is not None and parent is not Window:
                assert parent is not getattr(app.root, "_mobile_control_scroll", None)
                parent = parent.parent
        if app.compact_layout:
            assert all(button.texture_size[1] <= button.height for button in main._context_row.children)
    finally:
        main.stop()
