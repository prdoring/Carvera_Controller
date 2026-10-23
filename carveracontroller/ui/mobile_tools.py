"""Operation selection and optional panes for landscape tool dialogs."""

import re

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.tabbedpanel import TabbedPanel
from kivy.uix.togglebutton import ToggleButton

from carveracontroller.translation import tr

from . import theme
from .android_layout import (
    DialogActions,
    DialogLabel,
    DialogSurface,
    TouchActionRow,
    _text_width,
    control_height,
    fit_form_grid,
    fit_tabs,
    style_action,
)
from .touch import JogTouchButton, cancel_jog


def operation_selector(panel):
    if getattr(panel, "mobile_selector", None) is not None:
        return panel.parent
    app = App.get_running_app()
    parent = panel.parent
    index = parent.children.index(panel)
    column = BoxLayout(orientation="vertical", spacing=dp(6), size_hint=panel.size_hint)
    parent.remove_widget(panel)
    panel.size_hint = (1, 1)
    selector = Spinner(font_size=sp(16), size_hint_y=None)
    selector._mobile_keyboard_secondary = True
    tabs = list(reversed(panel.tab_list))
    selector.values = [tab.text for tab in tabs]
    def select(_spinner, text):
        for tab in tabs:
            if tab.text == text and panel.current_tab != tab:
                panel.switch_to(tab)
                break
    def sync(*_args):
        selector.text = panel.current_tab.text
        layout = getattr(app, "_touch_layout", None)
        if layout is not None:
            layout._update()
    selector.bind(text=select)
    panel.bind(current_tab=sync)
    original_height = panel.tab_height
    def reflow(*_args):
        compact = app.compact_layout or not fit_tabs(panel)
        selector.height = control_height() if compact else 0
        selector.opacity = 1 if compact else 0
        selector.disabled = not compact
        panel.tab_height = 0 if compact else control_height()
        panel._tab_layout.opacity = int(not compact)
        if not compact:
            panel.tab_width = max(dp(96), max(tab.texture_size[0] for tab in tabs) + dp(24))
    app.bind(compact_layout=reflow)
    panel.bind(width=reflow)
    Metrics.bind(density=reflow, fontscale=reflow)
    panel.mobile_selector = selector
    column.add_widget(selector)
    column.add_widget(panel)
    parent.add_widget(column, index=index)
    sync()
    reflow()
    return column


def adapt_probe_settings(settings):
    app = App.get_running_app()
    if app is None or not app.android_touch:
        return
    for widget in settings.walk(restrict=True):
        if isinstance(widget, GridLayout) and widget.row_force_default:
            widget.cols = 1
            widget.row_default_height = control_height()
            fit_form_grid(widget)
        if hasattr(widget, "label_text"):
            widget.cols = 1
            widget.size_hint_max_y = None
            label = widget.label_text.strip()
            label = label.replace("Tip Dia", "Probe tip diameter").replace("Btm Retract", "Bottom retraction")
            label = label.replace("FF Rate", "Fast feed rate").replace("Rpt", "Repeat")
            if label.startswith(("X :", "Y :", "Z :")):
                label = label[0] + " distance (mm)"
            elif re.search(r"feed|rapid", label, re.I):
                label += " mm/min"
            elif re.search(r"diameter|depth|retract|distance", label, re.I):
                label += " mm"
            elif "Angle" in label:
                label += " °"
            widget.label_text = tr._(label)
            for child in widget.children:
                if isinstance(child, Label):
                    child.font_size = sp(16)
                    child.size_hint_min_x = 0
                    child.halign = "left"
            row = widget.parent
            if isinstance(row, BoxLayout) and not getattr(row, "_mobile_parameter_bound", False):
                row._mobile_parameter_bound = True
                label_box = widget
                label = next(child for child in widget.children if isinstance(child, Label))
                fields = [child for child in row.children if child != widget]
                original = {child: tuple(child.size_hint) for child in row.children}
                def fit_parameter(*_args, row=row, label_box=label_box, label=label, fields=fields, original=original):
                    field_widths = {field: max(dp(144), _text_width(
                        getattr(field, "hint_text", ""), getattr(field, "font_name", theme.SANS), sp(16)
                    ) + dp(24)) for field in fields}
                    needed = _text_width(label.text, label.font_name, sp(16)) + dp(40) + sum(field_widths.values())
                    stacked = row.width < needed
                    row._mobile_stacked_form = stacked
                    row.orientation = "vertical" if stacked else "horizontal"
                    for child in row.children:
                        child.size_hint = (1, None) if stacked else original[child]
                    if not stacked:
                        label_box.size_hint_x = 1
                        for field in fields:
                            field.size_hint_x = None
                            field.width = field_widths[field]
                    if stacked:
                        label_box.height = max(control_height(), label.texture_size[1] + dp(12))
                        row.height = label_box.height + sum(field.height for field in fields) + row.spacing * len(fields) + sum(row.padding[1::2])
                    else:
                        row.height = max(control_height(), label.texture_size[1] + dp(12))
                row.bind(width=fit_parameter)
                label.bind(texture_size=fit_parameter)
                for field in fields:
                    field.bind(height=fit_parameter)
                Metrics.bind(density=fit_parameter, fontscale=fit_parameter)
                fit_parameter()
    layout = getattr(app, "_touch_layout", None)
    if layout is not None:
        layout.size_controls(settings)


def select_panes(parent, first, second, first_title, second_title, compact):
    """Keep at least one existing pane visible; retain its contents and state."""
    app = App.get_running_app()
    panel = next(widget for widget in first.walk(restrict=True) if isinstance(widget, TabbedPanel))
    operations = {tr._(first_title) + " · " + tab.text: tab for tab in reversed(panel.tab_list)}
    def capture_title():
        return next(name for name, tab in operations.items() if tab == panel.current_tab)
    selectors = Spinner(text=capture_title(), values=(*operations, tr._(second_title)),
                        size_hint_y=None, height=control_height())
    selectors._mobile_keyboard_secondary = True
    selectors.disabled = panel.disabled
    panel.bind(disabled=lambda _panel, value: setattr(selectors, "disabled", value))
    original_selector = panel.mobile_selector
    selector_parent = original_selector.parent
    selector_index = selector_parent.children.index(original_selector)
    hints = {first: tuple(first.size_hint), second: tuple(second.size_hint)}
    buttons = []
    def apply(_button=None):
        if _button is not None and _button.state == "down" and app.compact_layout:
            for button in buttons:
                if button is not _button:
                    button.state = "normal"
        if not any(button.state == "down" for button in buttons):
            (_button or buttons[0]).state = "down"
        cancel_jog()
        for button, pane in zip(buttons, (first, second)):
            visible = button.state == "down"
            pane.size_hint_x = hints[pane][0] if visible else None
            pane.width = dp(300) if visible else 0
            pane.size_hint_min_x = 0
            pane.opacity = 1 if visible else 0
            pane.disabled = not visible
    for pane, title in ((first, first_title), (second, second_title)):
        button = ToggleButton(text=tr._(title), state="down" if pane is first or not compact else "normal")
        button.bind(on_release=apply)
        buttons.append(button)
    def choose(_selector, text):
        selected = buttons[1] if text == tr._(second_title) else buttons[0]
        if text in operations and panel.current_tab != operations[text]:
            panel.switch_to(operations[text])
        selected.state = "down"
        apply(selected)
    selectors.bind(text=choose)
    def reflow(*_args):
        if not app.compact_layout:
            for button in buttons:
                button.state = "down"
        if app.compact_layout and sum(button.state == "down" for button in buttons) > 1:
            buttons[1].state = "normal"
        apply()
        selectors.height = control_height()
        selectors.text = capture_title() if buttons[0].state == "down" else tr._(second_title)
        if app.compact_layout and original_selector.parent is not None:
            original_selector.parent.remove_widget(original_selector)
        elif not app.compact_layout and original_selector.parent is None:
            selector_parent.add_widget(original_selector, index=selector_index)
        if app.compact_layout and selectors.parent is None:
            parent.add_widget(selectors, index=len(parent.children))
        elif not app.compact_layout and selectors.parent is not None:
            parent.remove_widget(selectors)
    app.bind(compact_layout=reflow)
    panel.bind(current_tab=lambda *_: setattr(selectors, "text", capture_title()) if buttons[0].state == "down" else None)
    Metrics.bind(density=reflow, fontscale=reflow)
    reflow()
    return selectors


def prepare_tool_dialog(modal, app):
    if getattr(modal, "_mobile_tool_prepared", False):
        return
    modal._mobile_tool_prepared = True
    panels = [w for w in modal.walk(restrict=True) if isinstance(w, TabbedPanel)]
    name = type(modal).__name__
    if name == "CoordPopup":
        for widget in modal.walk(restrict=True):
            if isinstance(widget, Label) and widget.text == tr._("Config and Run"):
                widget.parent._mobile_keyboard_secondary = True
        toggle = modal.ids.show_illustration
        toggle.parent.remove_widget(toggle)
        scroll = next(widget for widget in modal.walk(restrict=True) if isinstance(widget, ScrollView))
        options = scroll.children[0]
        secondary = list(reversed(options.children))[:3]
        for widget in secondary:
            options.remove_widget(widget)
        for widget in secondary:
            options.add_widget(widget)
        options.add_widget(toggle)
        for key, title in (("btn_origin", "Set work origin"), ("btn_zprobe", "Configure Z probing"), ("btn_leveling", "Configure leveling")):
            if key in modal.ids:
                modal.ids[key].text = tr._(title)
        from .mobile_forms import prepare_job_options

        prepare_job_options(modal)
        for widget in modal.walk(restrict=True):
            if isinstance(widget, Button) and widget.text in (tr._("Run"), tr._("Do ") + modal.mode):
                style_action(widget, "primary")
        return
    if name == "JogCMMWorkbenchPopup":
        prepare_jog_overlay(modal, app)
        return
    if name == "UpgradePopup":
        prepare_updates(modal)
        return
    if name not in ("ProbingPopup", "CMMWorkbenchPopup", "FacingWizardPopup"):
        return
    for panel in panels:
        operation_selector(panel)
    if name == "ProbingPopup":
        prepare_probing_jog(modal, app)
        outer = modal.ids.btn_close.parent.parent
        primary = modal.ids.tabbedpanelid
        while primary.parent != outer:
            primary = primary.parent
        for row in outer.children:
            if row != primary and row != modal.ids.btn_close.parent:
                row._mobile_keyboard_secondary = True
                help_button = next((child for child in row.children if type(child).__name__ == "HelpButton"), None)
                if help_button is not None:
                    warning = next(child for child in row.children if isinstance(child, Label))
                    wording = warning.text
                    row.remove_widget(help_button)
                    for prop in ("height", "opacity", "disabled"):
                        Builder.unbind_property(row, prop)
                    row.height, row.opacity, row.disabled = 0, 0, True
                    surface = DialogSurface(orientation="vertical", padding=dp(8))
                    surface.add_widget(DialogLabel(text=wording))
                    actions = DialogActions()
                    actions.add_widget(help_button)
                    close = Button(text=tr._("Close"))
                    actions.add_widget(close)
                    surface.add_widget(actions)
                    sheet = Popup(title=tr._("Probe requirements"), content=surface)
                    close.bind(on_release=lambda *_, target=sheet: target.dismiss())
                    info = Button(text=tr._("Probe info"))
                    info._mobile_keyboard_secondary = True
                    info.bind(on_release=lambda *_, text=wording, docs=help_button: app._touch_layout.show_help(
                        modal.ids.tabbedpanelid.current_tab.content, introduction=text, documentation=docs))
                    modal.ids.btn_close.parent.add_widget(info, index=1)
                    modal._mobile_requirements = sheet
                    modal.bind(on_dismiss=lambda *_, target=sheet: target.dismiss())
    if name == "CMMWorkbenchPopup":
        style_action(modal.ids.cmm_save, "primary")
        left = panels[0].parent
        pair = left.parent
        right = next(w for w in pair.children if w is not left)
        select_panes(pair.parent, left, right, "Capture", "Sketch / features", app.compact_layout)
        compact_features(modal, right, app)
        compact_actions(modal, modal.ids.cmm_actions, lambda button: button in
                        (modal.ids.cmm_save, modal.ids.cmm_cancel_probe, modal.ids.cmm_close), app)
        for panel in panels:
            for tab in panel.tab_list:
                for grid in tab.content.walk(restrict=True):
                    if isinstance(grid, GridLayout) and grid.cols == 2 and any(hasattr(child, "input_policy") for child in grid.children):
                        fit_form_grid(grid)
        for widget in modal.walk(restrict=True):
            if isinstance(widget, GridLayout) and widget.cols == 4:
                widget.cols = max(1, int(widget.width / dp(160)))
                widget.rows = None
                widget.row_force_default = True
                widget.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
                widget.size_hint_y = None
                widget.bind(minimum_height=widget.setter("height"))
    elif name == "FacingWizardPopup":
        style_action(modal.ids.btn_generate_program, "primary")
        optional = modal.ids.get("optional_panes")
        if optional is not None:
            optional.parent.remove_widget(optional)
            modal._optional_panes = optional
        row = modal.ids.btn_generate_program.parent
        row.parent._mobile_keyboard_padding = True
        preview_button = Button(text=tr._("Views"))
        def show_views(*_args):
            surface = DialogSurface(orientation="vertical", padding=dp(8))
            choices = TouchActionRow(stacked=True)
            for button in list(reversed(modal._optional_panes.children)):
                modal._optional_panes.remove_widget(button)
                choices.add_widget(button)
            surface.add_widget(choices)
            footer = DialogActions()
            close = Button(text=tr._("Close"))
            footer.add_widget(close)
            surface.add_widget(footer)
            sheet = Popup(title=tr._("Optional views"), content=surface)
            close.bind(on_release=lambda *_: sheet.dismiss())
            sheet.bind(on_dismiss=lambda *_: restore_views(choices))
            sheet.open()
        def restore_views(choices):
            for button in list(reversed(choices.children)):
                choices.remove_widget(button)
                modal._optional_panes.add_widget(button)
        preview_button.bind(on_release=show_views)
        row.add_widget(preview_button)
        compact_actions(modal, row, lambda button: button == modal.ids.btn_generate_program or getattr(button, "text", "") == tr._("Close"), app)
        modal.ids.facing_program_status._mobile_keyboard_secondary = True
        for panel in panels:
            for tab in panel.tab_list:
                for widget in tab.content.walk(restrict=True):
                    if isinstance(widget, GridLayout) and widget.cols == 2:
                        widget.row_force_default = True
                        widget.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
                        fit_form_grid(widget)
        prepare_facing_preview(modal, panels[0])
        # Put each existing field grid above its supporting help paragraph.
        for panel in panels:
            for tab in panel.tab_list:
                for column in list(tab.content.walk(restrict=True)):
                    if isinstance(column, BoxLayout) and column.orientation == "vertical" and len(column.children) == 2:
                        first, second = reversed(column.children)
                        if isinstance(first, Label) and isinstance(second, GridLayout):
                            column.remove_widget(second)
                            column.add_widget(second, index=len(column.children))


def prepare_updates(modal):
    outer = modal.children[0]
    header, introduction, tabs_row, footer = reversed(outer.children)
    panel = next(widget for widget in tabs_row.children if isinstance(widget, TabbedPanel))
    tabs_row.remove_widget(panel)
    outer.clear_widgets()
    modal.remove_widget(outer)
    surface = DialogSurface(presentation="workspace", orientation="vertical", padding=dp(12))
    surface.add_widget(header)
    surface.add_widget(introduction)
    actions = DialogActions(spacing=dp(8))
    for button in list(reversed(footer.children)):
        footer.remove_widget(button)
        actions.add_widget(button)
    surface.add_widget(actions)
    surface.prepare()
    holder = BoxLayout(orientation="vertical")
    holder.add_widget(panel)
    selector_column = operation_selector(panel)
    holder.remove_widget(selector_column)
    selector_column.size_hint_y = None
    panel.size_hint_y = None
    surface.body.add_widget(selector_column)
    modal.add_widget(surface)
    modal._mobile_workspace = True

    for tab in panel.tab_list:
        content = tab.content
        toolbar, log = reversed(content.children)
        widgets = list(reversed(toolbar.children))
        toolbar.clear_widgets()
        content.clear_widgets()
        content.spacing = dp(8)
        content.padding = dp(4)
        content.size_hint_y = None
        content.bind(minimum_height=content.setter("height"))
        title = next(widget for widget in widgets if isinstance(widget, Label) and widget.text.strip())
        version = next(widget for widget in widgets if widget in (modal.fw_version_txt, modal.ctl_version_txt))
        for label in (version, title):
            Builder.unbind_property(label, "text_size")
            Builder.unbind_property(label, "height")
            label.size_hint = (1, None)
            label.text_size = (max(1, content.width - dp(16)), None)
            label.halign = "left"
            label.bind(width=lambda item, width: setattr(item, "text_size", (max(1, width - dp(16)), None)))
            label.bind(texture_size=lambda item, size: setattr(item, "height", size[1] + dp(8) if item.text else 0))
            label.height = label.texture_size[1] + dp(8) if label.text else 0
        content.add_widget(version)
        buttons = TouchActionRow(spacing=dp(8))
        for widget in widgets:
            if isinstance(widget, Button):
                widget.size_hint_x = 1
                buttons.add_widget(widget)
        content.add_widget(buttons)
        content.add_widget(title)
        log.size_hint_y = None
        log.height = max(dp(200), control_height() * 4)
        content.add_widget(log)
        content.bind(height=lambda *_: fit())

    def fit(*_args):
        current = panel.current_tab.content
        panel.height = current.height + panel.tab_height + sum(panel.padding[1::2])
        selector_column.height = panel.height + panel.mobile_selector.height + selector_column.spacing
        header.height = max([control_height()] + [child.texture_size[1] + dp(8)
                            for child in header.children if isinstance(child, Label)])

    panel.bind(current_tab=fit, tab_height=fit)
    panel.mobile_selector.bind(height=fit)
    header.bind(width=fit)
    Metrics.bind(density=fit, fontscale=fit)
    fit()


def prepare_facing_preview(modal, panel):
    form = panel.parent
    column = form.parent
    parent = column.parent
    index = parent.children.index(column)
    viewport = ScrollView(do_scroll_x=False, bar_width=dp(6), size_hint=column.size_hint)
    parent.remove_widget(column)
    column.size_hint = (1, None)
    viewport.add_widget(column)
    parent.add_widget(viewport, index=index)
    form.size_hint_y = None
    sketch = modal.ids.facing_sketch_pane

    def fit(*_args):
        form.height = max(control_height() * 4, viewport.height - sketch.height - column.spacing)
        column.height = max(viewport.height, column.minimum_height)
        viewport.do_scroll_y = column.height > viewport.height + 1

    def reveal(*_args):
        Clock.schedule_once(lambda _dt: setattr(viewport, "scroll_y", 0 if modal.show_sketch else 1), 0)

    viewport.bind(height=fit)
    column.bind(minimum_height=fit)
    sketch.bind(height=fit)
    Metrics.bind(density=fit, fontscale=fit)
    modal.bind(show_sketch=reveal)
    modal._mobile_facing_preview = viewport
    fit()


def compact_features(modal, column, app):
    original = list(reversed(column.children))
    sketch = next(w for w in original if isinstance(w, FloatLayout))
    construct = next(w for w in original if isinstance(w, GridLayout))
    construct.row_force_default = True
    construct.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
    construct.bind(minimum_height=construct.setter("height"))
    construct.height = construct.minimum_height
    construct.rows = None

    def fit_construct(*_args):
        gap = construct.spacing[0]
        needed = max(_text_width(button.text, button.font_name, sp(16), button.bold) + dp(24)
                     for button in construct.children if isinstance(button, Button))
        available = max(1, construct.width - sum(construct.padding[::2]))
        construct.cols = min(4, max(1, int((available + gap) / (needed + gap))))
        construct._content_row_height = max(control_height(), sp(16) * 1.25 + dp(16))
        construct.row_default_height = construct._content_row_height

    construct.bind(width=fit_construct)
    Metrics.bind(density=fit_construct, fontscale=fit_construct)
    fit_construct()
    listing = next(w for w in original if isinstance(w, ScrollView))
    sheets = []
    toolbar = TouchActionRow(spacing=dp(6))
    sketch_button = Button(text=tr._("XY sketch"))
    construct_button = Button(text=tr._("Construct…"))
    toolbar.add_widget(sketch_button)
    toolbar.add_widget(construct_button)
    def show(widget, title, description=""):
        if widget.parent is not None:
            widget.parent.remove_widget(widget)
        if widget is sketch:
            sheet = Popup(title=title, content=widget, size_hint=(.95, .9))
        else:
            surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
            surface.add_widget(DialogLabel(text=description))
            surface.add_widget(widget)
            actions = DialogActions()
            close = Button(text=tr._("Close"))
            actions.add_widget(close)
            surface.add_widget(actions)
            sheet = Popup(title=title, content=surface, size_hint=(.95, .9))
            close.bind(on_release=lambda *_: sheet.dismiss())
        sheets.append(sheet)
        sheet.open()
    sketch_button.bind(on_release=lambda *_: show(sketch, tr._("XY sketch")))
    construct_button.bind(on_release=lambda *_: show(construct, tr._("Construct features"),
                          tr._("Select features in the list or sketch first. Segment and midpoint need two points; a circumcircle needs three. Available actions are enabled below.")))
    state = [None]
    def reflow(*_args):
        compact = app.compact_layout
        if state[0] == compact:
            return
        state[0] = compact
        for sheet in sheets:
            sheet.dismiss()
        column.clear_widgets()
        for widget in original:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
        if compact:
            column.add_widget(toolbar)
            column.add_widget(listing)
        else:
            for widget in original:
                column.add_widget(widget)
    app.bind(compact_layout=reflow)
    modal.bind(on_dismiss=lambda *_: [sheet.dismiss() for sheet in sheets])
    reflow()


def prepare_probing_jog(modal, app):
    panel = modal.ids.jog_panel
    buttons = {
        widget.text: widget for widget in panel.walk(restrict=True)
        if isinstance(widget, JogTouchButton)
    }
    steps = [modal.ids[name].__self__ for name in ("step_xy", "step_a", "step_z")]
    settings = [modal.ids[name].__self__ for name in (
        "jog_speed_btn_probing", "jog_mode_btn_probing",
        "kb_jog_btn_probing", "pendant_jogging_en_btn_probing",
    )]
    for widget in list(buttons.values()) + steps + settings:
        widget.parent.remove_widget(widget)
        widget.size_hint = (1, 1)
    panel.clear_widgets()
    panel.padding = dp(8)
    panel.spacing = dp(12)
    panel.size_hint_min_y = 0
    axes = GridLayout(cols=5, rows=3, spacing=dp(4))
    axes.disabled = not app.jog_controls_enabled
    app.bind(jog_controls_enabled=lambda _app, enabled: setattr(axes, "disabled", not enabled))
    top = "Y+" if app.invert_y_axis_jogging else "Y-"
    bottom = "Y-" if app.invert_y_axis_jogging else "Y+"
    entries = [None, buttons[top], None, buttons["A+"], buttons["Z+"],
               buttons["X-"], steps[0], buttons["X+"], steps[1], steps[2],
               None, buttons[bottom], None, buttons["A-"], buttons["Z-"]]
    for widget in entries:
        axes.add_widget(widget if widget is not None else BoxLayout())
    panel.add_widget(axes)
    viewport = ScrollView(do_scroll_x=False, size_hint_x=None, bar_width=dp(4))
    viewport.always_overscroll = False
    column = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
    column._mobile_form_fitted = True
    column.bind(minimum_height=column.setter("height"))
    for widget in settings:
        Builder.unbind_property(widget, "height")
        widget.size_hint_y = None
        widget.halign = "center"
        widget.valign = "middle"
        column.add_widget(widget)
    viewport.add_widget(column)
    panel.add_widget(viewport)
    Builder.unbind_property(panel, "height")

    def fit(*_args):
        needed = max(_text_width(button.text, button.font_name, sp(16), button.bold)
                     + dp(28) for button in settings)
        viewport.width = min(max(dp(200), needed), max(dp(160), panel.width * .42))
        for button in settings:
            button.text_size = (max(1, viewport.width - dp(16)), None)
            button.height = max(control_height(), button.texture_size[1] + dp(16))
        visible = not app.android_keyboard_height and (not app.compact_layout or modal.jog_expanded)
        if not visible:
            panel.height = 0
        elif app.compact_layout:
            outer = panel.parent
            panel.height = max(0, modal.height - 2 * control_height() - sum(outer.padding[1::2]))
        else:
            panel.height = min(modal.height * .45, max(
                control_height() * 3 + dp(24), column.minimum_height + dp(16)))
        viewport.do_scroll_y = column.height > viewport.height + 1

    panel.bind(width=fit)
    viewport.bind(height=fit)
    modal.bind(height=fit, jog_expanded=fit)
    app.bind(compact_layout=fit, android_keyboard_height=fit)
    Metrics.bind(density=fit, fontscale=fit)
    column.bind(minimum_height=fit)
    for button in settings:
        button.bind(text=fit, texture_size=fit)
    modal._mobile_jog_axes = axes
    modal._mobile_jog_settings = viewport
    fit()


def prepare_jog_overlay(modal, app):
    modal._mobile_jog_ready = True
    buttons = {widget.text: widget for widget in modal.walk(restrict=True) if isinstance(widget, JogTouchButton)}
    # KV ids are weak proxies; retain the controls while replacing their parents.
    step_xy, step_a, step_z = (modal.ids[name].__self__ for name in ("scan_jog_step_xy", "scan_jog_step_a", "scan_jog_step_z"))
    settings = [modal.ids[name].__self__ for name in ("jog_speed_btn_scan", "jog_mode_btn_scan", "kb_jog_btn_scan", "pendant_jog_btn_scan")]
    for widget in list(buttons.values()) + [step_xy, step_a, step_z] + settings:
        widget.parent.remove_widget(widget)
        widget.size_hint = (1, 1)
    modal.clear_widgets()
    body = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
    axes = GridLayout(cols=5, rows=3, spacing=dp(4))
    top = "Y+" if app.invert_y_axis_jogging else "Y-"
    bottom = "Y-" if app.invert_y_axis_jogging else "Y+"
    entries = [None, buttons[top], None, buttons["A+"], buttons["Z+"],
               buttons["X-"], step_xy, buttons["X+"], step_a, step_z,
               None, buttons[bottom], None, buttons["A-"], buttons["Z-"]]
    for widget in entries:
        axes.add_widget(widget if widget is not None else BoxLayout())
    body.add_widget(axes)
    actions = DialogActions(spacing=dp(8))
    configure, close = Button(text=tr._("Jog settings")), Button(text=tr._("Close"))
    actions.add_widget(configure)
    actions.add_widget(close)
    body.add_widget(actions)
    modal.add_widget(body)
    modal.size_hint_y = None
    modal.height = min(Window.height * .9, dp(420))
    close.bind(on_release=lambda *_: modal.dismiss())
    def show_settings(*_args):
        cancel_jog()
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        choices = TouchActionRow(stacked=True, spacing=dp(8))
        for widget in settings:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
            choices.add_widget(widget)
        surface.add_widget(choices)
        footer = DialogActions()
        done = Button(text=tr._("Close"))
        footer.add_widget(done)
        surface.add_widget(footer)
        sheet = Popup(title=tr._("Jog settings"), content=surface, size_hint=(.85, .9))
        done.bind(on_release=lambda *_: sheet.dismiss())
        sheet.open()
    configure.bind(on_release=show_settings)


def compact_actions(modal, row, keep, app):
    original = list(reversed(row.children))
    more = Button(text=tr._("More…"))
    more._mobile_keyboard_secondary = True
    secondary = [widget for widget in original if widget.is_event_type("on_release") and not keep(widget)]
    current = [None]
    def dismiss_sheet(*_args):
        if current[0] is not None:
            current[0].dismiss()
    for widget in secondary:
        widget.bind(on_release=dismiss_sheet)
    def show(*_args):
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        choices = TouchActionRow(stacked=True, spacing=dp(8))
        for widget in secondary:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
            widget.size_hint_x = 1
            choices.add_widget(widget)
        surface.add_widget(choices)
        footer = DialogActions()
        close = Button(text=tr._("Close"))
        close.bind(on_release=dismiss_sheet)
        footer.add_widget(close)
        surface.add_widget(footer)
        current[0] = Popup(title=tr._("Actions"), content=surface, size_hint=(.85, .9))
        current[0].open()
    more.bind(on_release=show)
    def reflow(*_args):
        dismiss_sheet()
        row.clear_widgets()
        for widget in original:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
            if widget == modal.ids.get("cmm_cancel_probe") and not modal.is_probing:
                continue
            if not app.compact_layout or widget not in secondary:
                row.add_widget(widget)
        if app.compact_layout:
            row.add_widget(more)
    app.bind(compact_layout=reflow)
    if "cmm_cancel_probe" in modal.ids:
        modal.bind(is_probing=reflow)
    modal.bind(on_dismiss=dismiss_sheet)
    reflow()
    return more
