"""Direct machine controls remain reachable after main-page reflow."""

import pytest
from kivy.core.window import Window
from kivy.metrics import sp
from kivy.uix.button import Button

from carveracontroller.CNC import CNC
from carveracontroller.ui.mobile_main import MobileMainLayout
from carveracontroller.Utils import digitize_v
from tests.integration.conftest import pump_frames, set_window_size


@pytest.fixture
def main_layout(mobile, monkeypatch):
    app, layout = mobile
    set_window_size((800, 480))
    monkeypatch.setattr(app, "state", "Idle")
    monkeypatch.setattr(app, "is_community_firmware", True)
    monkeypatch.setattr(app.root.controller, "is_community_firmware", True)
    monkeypatch.setattr(app, "fw_version_digitized", digitize_v("2.1.0"))
    monkeypatch.setattr(app, "has_4axis", False)
    main = MobileMainLayout(app)
    pump_frames(10)
    try:
        yield app, layout, main
    finally:
        for dropdown in (
            app.root.tool_drop_down,
            app.root.feed_drop_down,
            app.root.spindle_drop_down,
            app.root.coordinate_system_drop_down,
            app.root.x_drop_down,
            app.root.y_drop_down,
            app.root.z_drop_down,
        ):
            dropdown.dismiss()
        app.compact_layout = False
        main.stop()


@pytest.mark.parametrize("page", ["Control", "File"])
def test_header_machine_controls_are_direct_on_both_pages(main_layout, page):
    app, _, main = main_layout
    root = app.root
    root.content.current = page
    pump_frames(8)
    headers = [
        root.tool_data_view,
        root.feed_data_view,
        root.spindle_laser_data_view,
        root.coord_system_data_view,
        root.x_data_view,
        root.y_data_view,
        root.z_data_view,
    ]
    before = list(app.simulation.commands)
    for button in headers:
        x, y = button.to_window(*button.pos)
        assert button.get_root_window() is Window
        assert button.width >= app.touch_target
        assert button.height >= app.touch_target
        assert 0 <= x <= Window.width - button.width + 1
        assert 0 <= y <= Window.height - button.height + 1
    assert root.ids.main_file_button not in list(main.bar.walk(restrict=True))
    root.tool_data_view.dispatch("on_release")
    pump_frames(5)
    assert root.tool_drop_down.parent is not None
    assert root.tool_drop_down.change_dropdown.get_root_window() is Window
    root.tool_drop_down.dismiss()
    root.feed_data_view.dispatch("on_release")
    pump_frames(3)
    assert root.feed_drop_down.parent is not None
    root.feed_drop_down.dismiss()
    assert app.simulation.commands == before


def test_control_page_keeps_quick_actions_and_jog_mode(main_layout, monkeypatch):
    app, _, _ = main_layout
    root = app.root
    root.content.current = "Control"
    pump_frames(6)
    keys = (
        "home_btn",
        "goto_btn",
        "set_origin_btn",
        "probing_btn",
        "margin_btn",
        "zprobe_btn",
        "autolevel_btn",
        "tools_btn",
        "unlock_btn",
        "reset_btn",
        "light_toggle",
        "external_control_btn",
        "jog_mode_btn",
        "jog_speed_btn",
        "kb_jog_btn",
        "pendant_jogging_en_btn",
    )
    footer_top = root.ids.main_file_button.top
    for key in keys:
        button = root.ids[key]
        x, y = button.to_window(*button.pos)
        assert button.get_root_window() is Window, key
        assert button.width >= app.touch_target, key
        assert button.height >= app.touch_target, key
        assert 0 <= x <= Window.width - button.width + 1, key
        assert footer_top <= y <= main_layout[2].bar.y - button.height + 1, key
    calls = []
    monkeypatch.setattr(root.controller, "home", lambda: calls.append("home"))
    root.ids.home_btn.dispatch("on_release")
    assert calls == ["home"]
    before = root.controller.jog_mode
    root.ids.jog_mode_btn.dispatch("on_release")
    assert root.controller.jog_mode != before
    root.ids.jog_mode_btn.dispatch("on_release")
    assert root.controller.jog_mode == before


def test_reflow_keeps_control_objects_values_and_bindings(main_layout):
    app, _, main = main_layout
    root = app.root
    saved = {key: root.ids[key] for key in ("jog_mode_btn", "home_btn", "kb_jog_btn", "pendant_jogging_en_btn")}
    draft = root.manual_cmd
    draft.text = "G0 X-12.5"
    before = list(app.simulation.commands)
    for compact in (False, True, False, True):
        app.compact_layout = compact
        main.update()
        pump_frames(6)
        assert all(root.ids[key] is value and value.get_root_window() is Window for key, value in saved.items())
        assert root.manual_cmd is draft
        assert draft.text == "G0 X-12.5"
        if not compact:
            macro = root.ids.touch_macro_1_btn
            assert macro.bold
            assert macro.font_size == pytest.approx(sp(16))
    for size in ((1920, 1080), (800, 480)):
        set_window_size(size)
        pump_frames(12)
        jog = next(
            widget for widget in root.walk() if type(widget).__name__ == "JogTouchButton" and widget.text == "X-"
        )
        pad = jog.parent.parent
        expected_height = pad.parent.height if app.compact_layout else min(pad.parent.width, pad.parent.height)
        assert pad.height == pytest.approx(expected_height, abs=1)
        modes = root.ids.control_modes
        actions = root.ids.control_actions
        if not app.compact_layout:
            assert modes.y >= actions.top
            assert root.ids.kb_jog_btn.y >= modes.y
    assert app.simulation.commands == before


def test_detailed_help_images_load_only_in_the_visible_viewport(kivy_app):
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.scrollview import ScrollView

    from carveracontroller.ui.help_images import ViewportHelpImage

    viewport = ScrollView(size_hint=(None, None), size=(200, 200), pos=(40, 40), do_scroll_x=False)
    body = BoxLayout(orientation="vertical", size_hint_y=None, height=600)
    pictures = [
        ViewportHelpImage(viewport, image_path="addons/probing/data/icons_1024x768/single_axis/X+.png")
        for _ in range(3)
    ]
    for picture in pictures:
        body.add_widget(picture)
    viewport.add_widget(body)
    Window.add_widget(viewport)
    try:
        pump_frames(8)
        assert pictures[0].source.endswith("/details/single_axis/X+.png")
        assert pictures[2].source == ""
        assert pictures[0].height == pictures[0].width
        viewport.scroll_y = 0
        pump_frames(8)
        assert pictures[0].source == ""
        assert pictures[2].source.endswith("/details/single_axis/X+.png")
        for picture in pictures:
            picture.close()
            assert picture.source == ""
            assert picture.texture is None
    finally:
        for picture in pictures:
            picture.close()
        Window.remove_widget(viewport)


def test_file_tooltip_releases_detailed_image_after_dismissal(kivy_app, monkeypatch):
    from carveracontroller.addons.tooltips.Tooltips import ToolTipButton

    widget = ToolTipButton(
        tooltip_txt="X positive",
        tooltip_image="addons/probing/data/icons_1024x768/single_axis/X+.png",
        show_tooltips=True,
        size_hint=(None, None),
        size=(100, 50),
        pos=(100, 100),
    )
    Window.add_widget(widget)
    monkeypatch.setattr(widget, "_is_blocked_by_modal", lambda: False)
    try:
        widget.on_mouse_pos(Window, (120, 120))
        assert widget._tooltip.ids.tooltip_image.source == ""
        widget.display_tooltip()
        picture = widget._tooltip.ids.tooltip_image
        assert picture.source.endswith("/details/single_axis/X+.png")
        assert picture.texture is not None
        widget.close_tooltip()
        assert picture.source == ""
        assert picture.texture is None
    finally:
        widget.show_tooltips = False
        widget.close_tooltip()
        Window.remove_widget(widget)


@pytest.mark.parametrize("key", ["active_color", "gcode_color_coordinate"])
def test_color_editor_reset_uses_themed_default_without_saving(mobile, key):
    from carveracontroller.ui import theme

    app, _ = mobile
    app.root.config_popup.open()
    pump_frames(5)
    setting = next(item for item in app.root.config_popup._all_setting_items() if getattr(item, "key", "") == key)
    original = setting.value
    setting.open_popup()
    try:
        pump_frames(8)
        setting.picker.color = (0.1, 0.2, 0.3, 1)
        setting._reset_to_default()
        expected = [int(part) / 255 for part in theme.STOCK_COLORS[key][1].split(",")]
        assert list(setting.picker.color) == pytest.approx(expected)
        assert setting.value == original
        assert list(setting.picker.foreground_color) == list(theme.TEXT)
    finally:
        setting._popup.dismiss()
        app.root.config_popup.dismiss()


def test_normal_scale_restores_all_quick_actions(main_layout):
    from kivy.metrics import Metrics

    app, _, _ = main_layout
    app.root.content.current = "Control"
    Metrics.fontscale = 1.5
    pump_frames(12)
    Metrics.fontscale = 1
    pump_frames(12)
    footer = app.root.ids.main_file_button.top
    for key in (
        "home_btn",
        "goto_btn",
        "set_origin_btn",
        "probing_btn",
        "margin_btn",
        "zprobe_btn",
        "autolevel_btn",
        "tools_btn",
        "unlock_btn",
        "reset_btn",
        "light_toggle",
        "external_control_btn",
        "jog_mode_btn",
        "jog_speed_btn",
        "kb_jog_btn",
        "pendant_jogging_en_btn",
    ):
        button = app.root.ids[key]
        _x, y = button.to_window(*button.pos)
        assert y >= footer, key
        assert y + button.height <= main_layout[2].bar.y + 1, key


def test_illustrated_help_uses_the_available_screen_height(mobile):
    from kivy.uix.boxlayout import BoxLayout

    from carveracontroller.addons.tooltips.Tooltips import ToolTipButton
    from carveracontroller.ui.help_images import ViewportHelpImage

    _, layout = mobile
    set_window_size((800, 480))
    source = BoxLayout()
    source.add_widget(
        ToolTipButton(
            tooltip_txt="Search toward X+",
            tooltip_image="addons/probing/data/icons_1024x768/single_axis/X+.png",
        )
    )
    popup = layout.show_help(source)
    try:
        pump_frames(12)
        picture = next(widget for widget in popup.walk() if isinstance(widget, ViewportHelpImage))
        assert popup.height >= Window.height * 0.85
        assert picture.viewport.height >= Window.height * 0.4
        assert picture.height == picture.width
        assert picture.source.endswith("/details/single_axis/X+.png")
    finally:
        popup.dismiss()


@pytest.mark.parametrize("font_scale", [1, 2])
@pytest.mark.parametrize("name", ["tool", "feed", "spindle_laser", "status"])
def test_header_dropdowns_fit_large_text_and_keep_stop_clear(main_layout, font_scale, name):
    from kivy.metrics import Metrics

    app, _, _ = main_layout
    Metrics.fontscale = font_scale
    pump_frames(10)
    root = app.root
    before = list(app.simulation.commands)
    button = root.ids[name + "_data_view"]
    button.dispatch("on_release")
    pump_frames(12)
    dropdown = {
        "tool": root.tool_drop_down,
        "feed": root.feed_drop_down,
        "spindle_laser": root.spindle_drop_down,
        "status": root.status_drop_down,
    }[name]
    try:
        footer = (
            root.ids.main_file_button.to_window(*root.ids.main_file_button.pos)[1] + root.ids.main_file_button.height
        )
        assert dropdown.y >= footer - 1
        assert dropdown.top <= Window.height + 1
        assert dropdown.right <= Window.width + 1
        if name == "tool":
            change = dropdown.change_dropdown
            _x, y = change.to_window(*change.pos)
            assert y >= dropdown.y - 1
            assert y + change.height <= dropdown.top + 1
        assert app.simulation.commands == before
    finally:
        dropdown.dismiss()


@pytest.mark.parametrize("font_scale", [1, 2])
def test_jog_destination_menu_stays_readable_and_dispatches_once(main_layout, monkeypatch, font_scale):
    from kivy.metrics import Metrics

    app, _, _ = main_layout
    Metrics.fontscale = font_scale
    pump_frames(10)
    button = app.root.ids.goto_btn
    calls = []
    monkeypatch.setattr(app.root.controller, "gotoPosition", lambda destination: calls.append(destination))
    button.dispatch("on_release")
    pump_frames(10)
    dropdown = button._dropdown
    try:
        footer = app.root.ids.main_file_button.top
        assert dropdown.y >= footer - 1
        assert dropdown.top <= Window.height + 1
        option = next(child for child in dropdown.container.children if child.text == "Work Origin")
        assert option.height >= app.touch_target
        option.dispatch("on_release")
        pump_frames(5)
        assert calls == ["Work Origin"]
        assert button.text == "Goto"
    finally:
        dropdown.dismiss()


def test_desktop_editor_reflow_keeps_draft_focus_and_action(kivy_app, monkeypatch):
    from kivy.uix.popup import Popup

    from carveracontroller.ui.android_layout import DialogActions, DialogLabel, DialogSurface
    from carveracontroller.ui.editing import EditingTextInput

    app = kivy_app
    monkeypatch.setattr(app, "android_touch", False)
    set_window_size((1920, 1080))
    surface = DialogSurface(orientation="vertical")
    surface.add_widget(DialogLabel(text="Name this saved position"))
    field = EditingTextInput(text="Fixture origin", multiline=False)
    surface.add_widget(field)
    footer = DialogActions()
    save = Button(text="Save")
    calls = []
    save.bind(on_release=lambda *_: calls.append(field.text))
    footer.add_widget(save)
    surface.add_widget(footer)
    modal = Popup(title="Saved position", content=surface)
    before = list(app.simulation.commands)
    try:
        modal.open(animation=False)
        field.focus = True
        pump_frames(12)
        assert modal.width < Window.width * .6
        for size in ((1280, 720), (1920, 1080)):
            set_window_size(size)
            pump_frames(12)
            assert field.text == "Fixture origin"
            assert field.focus
            assert modal.x >= 0 and modal.right <= Window.width
            assert modal.y >= 0 and modal.top <= Window.height
            assert save.height >= 48
        save.dispatch("on_release")
        assert calls == ["Fixture origin"]
        assert app.simulation.commands == before
    finally:
        modal.dismiss(force=True, animation=False)


def test_folder_information_opens_and_tracks_navigation_without_commands(mobile):
    from kivy.uix.label import Label
    from kivy.uix.popup import Popup

    app, _layout = mobile
    set_window_size((800, 480))
    popup = app.root.file_popup
    popup.open(animation=False)
    pump_frames(12)
    page = popup._mobile_file_pages["remote"]
    view = page["rv"]
    original = view.curr_dir, list(view.curr_path_list)
    before = list(app.simulation.commands)
    folder = None
    try:
        page["path"].dispatch("on_release")
        pump_frames(12)
        folder = next(w for w in Window.children if isinstance(w, Popup) and w.title == "Current folder")
        view.curr_dir = "/sd/gcodes/fixtures"
        view.curr_path_list = ["gcodes", "fixtures"]
        pump_frames(8)
        assert any(isinstance(w, Label) and w.text == view.curr_dir for w in folder.walk())
        assert app.simulation.commands == before
    finally:
        if folder is not None:
            folder.dismiss(force=True, animation=False)
        view.curr_dir, view.curr_path_list = original
        popup.dismiss(force=True, animation=False)


def test_compact_operation_selector_keeps_manual_capture_usable(mobile, monkeypatch):
    from kivy.uix.tabbedpanel import TabbedPanel

    app, _layout = mobile
    set_window_size((800, 480))
    monkeypatch.setattr(app, "state", "Idle")
    popup = app.root._ensure_cmm_workbench_popup()
    popup.open(animation=False)
    pump_frames(12)
    panel = next(w for w in popup.walk() if isinstance(w, TabbedPanel))
    manual = next(tab for tab in panel.tab_list if tab.text == "Manual")
    try:
        panel.switch_to(manual)
        pump_frames(10)
        assert not manual.content.disabled
        field = popup.ids.t_manual_wx
        field.text = "12.5"
        assert not field.disabled
        add = next(w for w in manual.content.walk() if isinstance(w, Button) and w.text == "Add point")
        assert not add.disabled
        before = len(popup.session.features)
        add.dispatch("on_release")
        pump_frames(8)
        assert len(popup.session.features) == before + 1
        assert popup.session.features[-1].payload["x"] == pytest.approx(12.5)
        popup.is_probing = True
        pump_frames(6)
        assert field.disabled
        popup.is_probing = False
        pump_frames(6)
        assert not field.disabled
    finally:
        popup.is_probing = False
        popup.dismiss(force=True, animation=False)


def test_compact_probe_parameters_remain_editable_after_tab_switch(mobile, monkeypatch):
    from kivy.uix.tabbedpanel import TabbedPanel

    from carveracontroller.addons.probing.ProbingPopup import ProbingPopup

    app, _layout = mobile
    set_window_size((800, 480))
    monkeypatch.setattr(app, "state", "Idle")
    popup = ProbingPopup(app.root.controller)
    popup.open(animation=False)
    pump_frames(12)
    panel = next(w for w in popup.walk() if isinstance(w, TabbedPanel))
    tab = next(w for w in panel.tab_list if w.text == "Single Axis")
    before = list(app.simulation.commands)
    try:
        panel.mobile_selector.text = tab.text
        pump_frames(12)
        field = next(w for w in tab.content.walk() if hasattr(w, "input_policy") and w.opacity and w.width)
        assert not tab.content.disabled
        assert not field.disabled
        field.text = "12.5"
        panel.mobile_selector.text = "Outside Corners"
        pump_frames(8)
        panel.mobile_selector.text = tab.text
        pump_frames(8)
        assert field.text == "12.5"
        assert not field.disabled
        assert app.simulation.commands == before
    finally:
        popup.dismiss(force=True, animation=False)


def test_compact_footer_switches_pages_without_machine_commands(main_layout):
    app, _, _ = main_layout
    app.root.content.current = "Control"
    pump_frames(10)
    before = list(app.simulation.commands)
    button = app.root.ids.main_page_button
    assert button.width >= app.touch_target
    assert not button.disabled
    button.dispatch("on_release")
    pump_frames(8)
    assert app.root.content.current == "File"
    button.dispatch("on_release")
    pump_frames(8)
    assert app.root.content.current == "Control"
    assert app.simulation.commands == before


def test_short_confirm_fits_content_after_enlarged_text_settles(mobile):
    from kivy.metrics import Metrics

    app, _layout = mobile
    set_window_size((800, 480))
    Metrics.fontscale = 1.5
    popup = app.root.confirm_popup
    popup.lb_title.text = "Confirm"
    popup.lb_content.text = "Continue with this change?"
    try:
        popup.open(animation=False)
        pump_frames(30)
        assert popup.height < Window.height * .7
        assert popup.ids.confirm_actions.top <= popup.top
        assert popup.ids.confirm_actions.y >= popup.y
    finally:
        popup.dismiss(force=True, animation=False)


def test_keyboard_option_labels_keep_existing_stored_values(mobile):
    from kivy.uix.label import Label

    app, _layout = mobile
    app.root.config_popup.open(animation=False)
    pump_frames(10)
    setting = next(item for item in app.root.config_popup._all_setting_items()
                   if getattr(item, "key", "") == "keyboard_mode")
    original = setting.value
    try:
        setting._create_popup(None)
        pump_frames(12)
        buttons = [w for w in setting.popup.walk() if isinstance(w, Button)]
        assert any(w.text == "Automatic" for w in buttons)
        assert not any(isinstance(w, Label) and w.text == "systemanddock" for w in buttons)
        next(w for w in buttons if w.text == "System and docked virtual keyboard").dispatch("on_release")
        assert setting.value == "systemanddock"
    finally:
        setting.popup.dismiss(force=True, animation=False)
        setting.value = original
        app.root.config_popup.dismiss(force=True, animation=False)


def _check_probe_preview_layout(app):
    from carveracontroller.addons.probing.preview.ProbingPreviewPopup import ProbingPreviewPopup

    popup = ProbingPreviewPopup(app.root.controller)
    popup.probe_preview_label = (
        "M469.6 R1.5 C2 D3.175 Y30 I1\n"
        "Make sure the fourth axis and 3-axis probe are installed, and the probe is above "
        "the reference artifact used for calibration."
    )
    popup.gcode = "M469.6 R1.5 C2 D3.175 Y30 I1"
    before = list(app.simulation.commands)
    try:
        popup.open(animation=False)
        pump_frames(24)
        close = next(w for w in popup.walk() if isinstance(w, Button) and w.text == "Close")
        start = next(w for w in popup.walk() if isinstance(w, Button) and w.text == "Start")
        help_button = next(w for w in popup.walk() if type(w).__name__ == "HelpButton")
        for button in (close, start, help_button):
            assert button.height >= 48
            x, y = button.to_window(*button.pos)
            assert x >= popup.x and x + button.width <= popup.right + 1
            assert y >= popup.y and y + button.height <= popup.top + 1
        title, preview = popup.ids.lb_title, popup.ids.lb_preview
        assert title.y >= preview.top - 1
        assert app.simulation.commands == before
    finally:
        popup.dismiss(force=True, animation=False)


def test_desktop_probe_preview_contains_long_warning_and_actions(kivy_app, monkeypatch):
    monkeypatch.setattr(kivy_app, "android_touch", False)
    monkeypatch.setattr(kivy_app, "state", "Idle")
    set_window_size((1920, 1080))
    _check_probe_preview_layout(kivy_app)


@pytest.mark.parametrize("font_scale", [1, 1.5])
def test_touch_probe_preview_contains_long_warning_and_actions(mobile, monkeypatch, font_scale):
    from kivy.metrics import Metrics

    app, _layout = mobile
    monkeypatch.setattr(app, "state", "Idle")
    Metrics.fontscale = font_scale
    set_window_size((800, 480))
    _check_probe_preview_layout(app)


@pytest.mark.parametrize("size,font_scale", [((800, 480), 1), ((800, 480), 1.5), ((1920, 1080), 1)])
def test_step_selectors_fill_their_jog_cells(main_layout, size, font_scale):
    from kivy.metrics import Metrics

    app, _layout, main = main_layout
    before = list(app.simulation.commands)
    Metrics.fontscale = font_scale
    set_window_size(size)
    main.update()
    pump_frames(16)
    for name in ("step_xy", "step_a", "step_z"):
        step = app.root.ids[name]
        cell = step.parent
        assert step.height == pytest.approx(cell.height - sum(cell.padding[1::2]), abs=1)
        assert step.width == pytest.approx(cell.width - sum(cell.padding[::2]), abs=1)
        original = step.text
        try:
            for value in step.values:
                from kivy.core.text import Label as CoreLabel

                step.text = value
                pump_frames(2)
                label = CoreLabel(text=value, font_name=step.font_name, font_size=step.font_size, bold=step.bold)
                label.refresh()
                assert label.texture.size[0] <= step.width - 10
        finally:
            step.text = original
    assert app.simulation.commands == before


def test_native_rotation_help_stays_inside_its_surface(kivy_app, monkeypatch):
    app = kivy_app
    monkeypatch.setattr(app, "android_touch", False)
    set_window_size((1920, 1080))
    before = list(app.simulation.commands)
    popup = app.root.set_rotation_popup
    try:
        popup.open(animation=False)
        pump_frames(24)
        help_button = next(w for w in popup.walk(restrict=True) if type(w).__name__ == "HelpButton")
        x, y = help_button.to_window(*help_button.pos)
        assert x >= popup.x
        assert x + help_button.width <= popup.right + 1
        assert y >= popup.y
        assert y + help_button.height <= popup.top + 1
        assert app.simulation.commands == before
    finally:
        popup.dismiss(force=True, animation=False)


@pytest.mark.parametrize("size,density,font_scale", [((1920, 1080), 1.5, 1), ((800, 480), 1, 1), ((800, 480), 1, 2)])
def test_job_resume_field_fits_hint_and_retains_line(mobile, size, density, font_scale):
    from kivy.core.text import Label as CoreLabel
    from kivy.metrics import Metrics

    app, _layout = mobile
    Metrics.density, Metrics.fontscale = density, font_scale
    app.touch_target = 48 * density
    set_window_size(size)
    popup = app.root.coord_popup
    field = popup.txt_startline
    original = field.text
    before = list(app.simulation.commands)
    try:
        popup.open(animation=False)
        pump_frames(24)
        hint = CoreLabel(text=field.hint_text, font_name=field.font_name, font_size=field.font_size)
        hint.refresh()
        assert field.width - sum(field.padding[::2]) >= hint.texture.size[0]
        field.text = "123456"
        popup.dismiss(force=True, animation=False)
        popup.open(animation=False)
        pump_frames(12)
        assert field.text == "123456"
        assert app.simulation.commands == before
    finally:
        field.text = original
        popup.dismiss(force=True, animation=False)


@pytest.mark.parametrize(
    "size,density,font_scale,native",
    [((1920, 1080), 1, 1, True), ((1920, 1080), 1.5, 1, False),
     ((800, 480), 1, 1, False), ((800, 480), 1, 1.5, False),
     ((800, 480), 1, 2, False)],
)
def test_header_live_values_fit_beside_their_icons(request, monkeypatch, size, density, font_scale, native):
    from kivy.metrics import Metrics, dp

    from carveracontroller.custom_widgets import ScrollingLabel

    if native:
        app = request.getfixturevalue("kivy_app")
        monkeypatch.setattr(app, "android_touch", False)
    else:
        app, _layout = request.getfixturevalue("mobile")
    previous_metrics = Metrics.density, Metrics.fontscale
    Metrics.density, Metrics.fontscale = density, font_scale
    monkeypatch.setattr(app, "touch_target", 48 * density)
    monkeypatch.setattr(app, "has_4axis", True)
    main = None if native else MobileMainLayout(app)
    values = {"spindle_laser": "15000", "feed": "15000", "tool": "T12",
              "x": "-123.456", "y": "-123.456", "z": "-123.456", "a": "-180.000"}
    headers = {name: app.root.ids[name + "_data_view"] for name in values}
    original = {name: widget.main_text for name, widget in headers.items()}
    before = list(app.simulation.commands)
    try:
        set_window_size(size)
        for name, value in values.items():
            headers[name].main_text = value
        pump_frames(24, sleep=.01)
        for name, header in headers.items():
            value = next(w for w in header.walk(restrict=True) if isinstance(w, ScrollingLabel))
            label = value.ids.scroll_label
            label.texture_update()
            assert label.texture_size[0] <= value.width + 1, name
            assert value.text == values[name]
            if header.data_icon:
                icon = next(w for w in header.children if w is not value.parent)
                assert icon.width >= dp(28), name
                assert icon.right <= value.x + 1, name
        assert app.simulation.commands == before
    finally:
        for name, value in original.items():
            headers[name].main_text = value
        if main:
            main.stop()
            app.compact_layout = False
        Metrics.density, Metrics.fontscale = previous_metrics


@pytest.mark.parametrize(
    "size,density,font_scale,native",
    [((1920, 1080), 1, 1, True), ((1920, 1080), 1.5, 1, False),
     ((800, 480), 1, 1, False), ((800, 480), 1, 1.5, False),
     ((800, 480), 1, 2, False)],
)
@pytest.mark.parametrize("split", [False, True])
def test_viewer_controls_keep_separate_usable_bounds(request, monkeypatch, size, density, font_scale, native, split):
    from kivy.metrics import Metrics, dp

    if native:
        app = request.getfixturevalue("kivy_app")
        monkeypatch.setattr(app, "android_touch", False)
    else:
        app, _layout = request.getfixturevalue("mobile")
    previous_metrics = Metrics.density, Metrics.fontscale
    Metrics.density, Metrics.fontscale = density, font_scale
    monkeypatch.setattr(app, "touch_target", 48 * density)
    for name, value in {"show_lines": split, "show_preview": True, "show_legend": True,
                        "show_gcode_ctl_bar": True, "selected_local_filename": "Fixture.cnc"}.items():
        monkeypatch.setattr(app, name, value)
    root = app.root
    old_page = root.content.current
    before = list(app.simulation.commands)
    root.content.current = "File"
    try:
        set_window_size(size)
        pump_frames(24, sleep=.01)
        assert "viewer_controls_toggle" not in root.ids
        toolbar = root.ids.viewer_toolbar_scroll
        playback = root.ids.gcode_ctl_bar
        legend = root.ids.color_scheme_panel
        def bounds(w):
            x, y = w.to_window(*w.pos)
            return x, y, x + w.width, y + w.height
        def overlaps(a, b):
            ax, ay, ar, at = bounds(a)
            bx, by, br, bt = bounds(b)
            return min(ar, br) > max(ax, bx) + 1 and min(at, bt) > max(ay, by) + 1
        assert not overlaps(toolbar, legend)
        assert legend.y >= playback.top - 1, {"legend": list(legend.pos) + list(legend.size), "max_height": legend.max_height, "scroll": legend.ids.legend_scroll.height, "header": legend.ids.legend_header.height, "float": list(root.ids.float_layout.pos) + list(root.ids.float_layout.size), "playback": list(playback.pos) + list(playback.size)}
        assert legend.top <= root.ids.float_layout.top + 1
        assert playback.height >= 2 * app.touch_target if not native else playback.height >= dp(88)
        for button in playback.walk(restrict=True):
            if isinstance(button, Button):
                assert button.height >= (app.touch_target if not native else dp(24)) - 1
                assert bounds(button)[1] >= bounds(playback)[1] - 1
                assert bounds(button)[3] <= bounds(playback)[3] + 1
        actions = list(reversed(root.ids.tool_bar.children))
        assert len(actions) == 7
        for scroll, action in ((0, actions[0]), (1, actions[-1])):
            toolbar.scroll_x = scroll
            pump_frames(8)
            assert bounds(action)[0] >= bounds(toolbar)[0] - 1
            assert bounds(action)[2] <= bounds(toolbar)[2] + 1
        assert app.simulation.commands == before
    finally:
        root.ids.viewer_toolbar_scroll.scroll_x = 0
        root.content.current = old_page
        Metrics.density, Metrics.fontscale = previous_metrics


@pytest.mark.parametrize("size,density,font_scale", [((800, 480), 1, 1), ((800, 480), 1, 1.5),
                                                       ((800, 480), 1, 2), ((1920, 1080), 1.5, 1)])
def test_view_disclosure_menu_help_and_integrated_navigation(main_layout, monkeypatch, size, density, font_scale):
    from kivy.metrics import Metrics
    from kivy.uix.popup import Popup

    app, _layout, main = main_layout
    Metrics.density, Metrics.fontscale = density, font_scale
    app.touch_target = 48 * density
    monkeypatch.setattr(app, "viewer_panes_expanded", False)
    root = app.root
    before = list(app.simulation.commands)
    root.content.current = "File"
    set_window_size(size)
    pump_frames(20)
    toggle = root.ids.viewer_panes_toggle
    host = root.ids.viewer_panes_host
    assert host.height == 0
    assert not host.opacity
    assert toggle.get_root_window() is Window
    assert toggle.width >= app.touch_target
    assert toggle.height >= app.touch_target
    toggle.dispatch("on_release")
    pump_frames(12)
    assert host.height >= app.touch_target
    assert host.opacity == 1
    toggle.dispatch("on_release")
    pump_frames(12)
    assert host.height == 0
    assert "main_help_button" not in root.ids
    assert root.ids.main_page_button.get_root_window() is Window
    root.ids.main_page_button.dispatch("on_release")
    pump_frames(12)
    assert root.content.current == "Control"
    assert toggle.width == 0
    root.ids.main_page_button.dispatch("on_release")
    pump_frames(12)
    assert root.content.current == "File"
    assert toggle.width >= app.touch_target
    root.ids.main_menu.dispatch("on_release")
    pump_frames(12)
    dropdown = root.func_drop_down
    dropdown.scroll_y = 0
    pump_frames(8)
    help_button = dropdown.ids.main_menu_help
    assert help_button.get_root_window() is Window
    help_button.dispatch("on_release")
    pump_frames(12)
    popup = next(w for w in Window.children if isinstance(w, Popup))
    assert popup.title == "Control help"
    popup.dismiss(force=True, animation=False)
    dropdown.dismiss()
    assert app.simulation.commands == before


@pytest.mark.parametrize("native", [False, True])
def test_viewer_visibility_toggle_lives_in_options(request, monkeypatch, native):
    app = request.getfixturevalue("kivy_app") if native else request.getfixturevalue("main_layout")[0]
    monkeypatch.setattr(app, "android_touch", not native)
    monkeypatch.setattr(app, "show_gcode_ctl_bar", False)
    before = list(app.simulation.commands)
    assert "viewer_controls_toggle" not in app.root.ids
    if native:
        app.root.ids.main_menu.dispatch("on_release")
        pump_frames(8)
        app.root.func_drop_down.ids.main_menu_viewer_controls.dispatch("on_release")
    else:
        sheet = app.root._mobile_view_options
        sheet.open(animation=False)
        pump_frames(8)
        controls = next(w for w in sheet.walk(restrict=True) if getattr(w, "text", "") == "Viewer controls")
        controls.trigger_action(duration=0)
        pump_frames(8)
        sheet.dismiss(force=True, animation=False)
    assert app.show_gcode_ctl_bar
    assert app.simulation.commands == before


@pytest.mark.parametrize("size,density,font_scale", [((800, 480), 1, 1), ((800, 480), 1, 1.5),
                                                       ((800, 480), 1, 2), ((1920, 1080), 1.5, 1)])
def test_offline_caption_and_footer_switch_fit(main_layout, monkeypatch, size, density, font_scale):
    from kivy.core.text import Label as CoreLabel
    from kivy.metrics import Metrics
    from kivy.uix.label import Label

    app, _layout, main = main_layout
    Metrics.density, Metrics.fontscale = density, font_scale
    app.touch_target = 48 * density
    monkeypatch.setattr(app, "state", "N/A")
    app.root.ids.status_data_view.minr_text = "disconnect"
    before = list(app.simulation.commands)
    set_window_size(size)
    for page in ("Control", "File"):
        app.root.content.current = page
        pump_frames(16)
        status = next(w for w in app.root.ids.status_data_view.walk(restrict=True)
                      if isinstance(w, Label) and w.text.startswith("Offline"))
        caption = next(w for w in app.root.ids.main_page_button.walk(restrict=True)
                       if isinstance(w, Label) and w.text in ("View", "Jog"))
        for label in (status, caption):
            text = CoreLabel(text=label.text, font_name=label.font_name, font_size=label.font_size)
            text.refresh()
            assert text.texture.size[0] <= label.width + 1, (page, label.text)
        assert app.machine_units in status.text
        assert app.root.ids.main_page_button.parent is app.root.ids.main_file_button.parent
    assert app.simulation.commands == before


@pytest.mark.parametrize("dismissal", ["close", "back"])
@pytest.mark.parametrize("size,density", [((800, 480), 1), ((1920, 1080), 1.5)])
def test_illustrated_help_dismisses_and_releases_images(main_layout, monkeypatch, dismissal, size, density):
    from kivy.metrics import Metrics

    from carveracontroller.ui.help_images import ViewportHelpImage

    app, layout, _main = main_layout
    Metrics.density = density
    app.touch_target = 48 * density
    monkeypatch.setattr(app, "playing", False)
    app.root.content.current = "Control"
    set_window_size(size)
    pump_frames(12)
    before = list(app.simulation.commands)
    for _ in range(2):
        popup = layout.show_help(app.root)
        pump_frames(15, sleep=.02)
        pictures = [w for w in popup.walk(restrict=True) if isinstance(w, ViewportHelpImage)]
        assert pictures
        assert any(picture.source and picture.texture is not None for picture in pictures)
        if dismissal == "back":
            assert layout.back()
        else:
            close = next(w for w in popup.walk(restrict=True) if isinstance(w, Button) and w.text == "Close")
            close.dispatch("on_release")
        pump_frames(15, sleep=.02)
        assert popup.parent is None
        assert not popup._is_open
        assert all(picture.source == "" and picture.texture is None for picture in pictures)
    assert app.simulation.commands == before


@pytest.mark.parametrize("size,density", [((800, 480), 1), ((1920, 1080), 1.5)])
def test_view_disclosure_handles_pointer_press(main_layout, monkeypatch, size, density):
    from kivy.metrics import Metrics

    from tests.unit.test_touch import dispatch, finger

    app, _layout, _main = main_layout
    Metrics.density = density
    app.touch_target = 48 * density
    monkeypatch.setattr(app, "viewer_panes_expanded", False)
    app.root.content.current = "File"
    set_window_size(size)
    pump_frames(20)
    toggle = app.root.ids.viewer_panes_toggle
    before = list(app.simulation.commands)
    for expanded in (True, False):
        x, y = toggle.to_window(*toggle.center)
        motion = finger(x, y)
        dispatch("begin", motion)
        pump_frames(3, sleep=.02)
        dispatch("end", motion)
        pump_frames(12, sleep=.02)
        assert app.viewer_panes_expanded is expanded, (toggle.pos, toggle.size, toggle.disabled, toggle.state)
        assert bool(app.root.ids.viewer_panes_host.height) is expanded
        splitter = app.root.cmd_manager.parent.parent
        assert splitter.top <= app.root.ids.viewer_panes_host.y + 1
        assert splitter._strip.top <= splitter.top + 1
        strokes = [instruction for group in (splitter._strip.canvas.before, splitter._strip.canvas.after)
                   for instruction in group.children if type(instruction).__name__ == "Line"
                   and len(instruction.points) == 4 and instruction.points[0] == instruction.points[2]]
        assert len(strokes) == 1
        for instruction in strokes:
            assert min(instruction.points[1::2]) >= splitter.y - 1
            assert max(instruction.points[1::2]) <= splitter.y + splitter.height + 1
    assert app.simulation.commands == before


@pytest.mark.parametrize("size,density", [((800, 480), 1), ((1920, 1080), 1.5)])
def test_collapsed_viewer_strip_keeps_header_pointer_access(main_layout, monkeypatch, size, density):
    from kivy.metrics import Metrics

    from tests.unit.test_touch import dispatch, finger

    app, _layout, _main = main_layout
    Metrics.density = density
    app.touch_target = 48 * density
    monkeypatch.setattr(app, "viewer_panes_expanded", False)
    root = app.root
    root.content.current = "File"
    set_window_size(size)
    pump_frames(20)
    opened = []
    targets = [
        (root.tool_data_view, root.tool_drop_down),
        (root.feed_data_view, root.feed_drop_down),
        (root.coord_system_data_view, root.coordinate_system_drop_down),
        (root.x_data_view, root.x_drop_down),
        (root.y_data_view, root.y_drop_down),
        (root.z_data_view, root.z_drop_down),
    ]
    for _button, dropdown in targets:
        monkeypatch.setattr(dropdown, "open", lambda button: opened.append(button))
    monkeypatch.setattr(root, "open_spindle_or_laser_drop_down", lambda button: opened.append(button))
    buttons = [button for button, _dropdown in targets] + [root.spindle_laser_data_view]
    before = list(app.simulation.commands)
    for button in buttons:
        motion = finger(*button.to_window(*button.center))
        dispatch("begin", motion)
        pump_frames(3, sleep=.02)
        dispatch("end", motion)
        pump_frames(6, sleep=.02)
        assert opened == [button]
        opened.clear()
    assert app.simulation.commands == before
