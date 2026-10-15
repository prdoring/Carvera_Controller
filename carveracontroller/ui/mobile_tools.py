"""Operation selection and optional panes for landscape tool dialogs."""

import re

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp, sp
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

from .android_layout import DialogLabel, DialogSurface, TouchActionRow
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
    tabs = list(reversed(panel.tab_list))
    selector.values = [tab.text for tab in tabs]
    def select(_spinner, text):
        for tab in tabs:
            if tab.text == text and panel.current_tab is not tab:
                panel.switch_to(tab)
                break
    def sync(*_args):
        selector.text = panel.current_tab.text
    selector.bind(text=select)
    panel.bind(current_tab=sync)
    original_height = panel.tab_height
    def reflow(*_args):
        compact = app.compact_layout
        selector.height = max(app.touch_target, sp(16) * 2 + dp(16)) if compact else 0
        selector.opacity = 1 if compact else 0
        selector.disabled = not compact
        panel.tab_height = 0 if compact else max(app.touch_target, original_height)
    app.bind(compact_layout=reflow)
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
    for widget in settings.walk():
        if isinstance(widget, GridLayout) and widget.row_force_default:
            widget.cols = 1
            widget.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
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


def select_panes(parent, first, second, first_title, second_title, compact):
    """Keep at least one existing pane visible; retain its contents and state."""
    app = App.get_running_app()
    selectors = TouchActionRow(spacing=dp(6))
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
        selectors.add_widget(button)
        buttons.append(button)
    parent.add_widget(selectors, index=max(0, len(parent.children) - 1))
    def reflow(*_args):
        if app.compact_layout and sum(button.state == "down" for button in buttons) > 1:
            buttons[1].state = "normal"
        apply()
    app.bind(compact_layout=reflow)
    apply()
    return selectors


def prepare_tool_dialog(modal, app):
    if getattr(modal, "_mobile_tool_prepared", False):
        return
    modal._mobile_tool_prepared = True
    panels = [w for w in modal.walk() if isinstance(w, TabbedPanel)]
    name = type(modal).__name__
    if name == "JogCMMWorkbenchPopup":
        prepare_jog_overlay(modal, app)
        return
    if name not in ("ProbingPopup", "CMMWorkbenchPopup", "FacingWizardPopup"):
        return
    for panel in panels:
        operation_selector(panel)
    if name == "CMMWorkbenchPopup":
        left = panels[0].parent
        pair = left.parent
        right = next(w for w in pair.children if w is not left)
        select_panes(pair.parent, left, right, "Capture", "Sketch / features", app.compact_layout)
        compact_features(modal, right, app)
        compact_actions(modal, modal.ids.cmm_actions, lambda button: button in
                        (modal.ids.cmm_save, modal.ids.cmm_cancel_probe, modal.ids.cmm_close), app)
        for widget in modal.walk():
            if isinstance(widget, GridLayout) and widget.cols == 4:
                widget.cols = max(1, int(widget.width / dp(160)))
                widget.rows = None
                widget.row_force_default = True
                widget.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
                widget.size_hint_y = None
                widget.bind(minimum_height=widget.setter("height"))
    elif name == "FacingWizardPopup":
        row = modal.ids.btn_generate_program.parent
        compact_actions(modal, row, lambda button: button == modal.ids.btn_generate_program or getattr(button, "text", "") == tr._("Close"), app)
        for panel in panels:
            for tab in panel.tab_list:
                for widget in tab.content.walk():
                    if isinstance(widget, GridLayout) and widget.cols == 2:
                        widget.row_force_default = True
                        widget.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
        # Put each existing field grid above its supporting help paragraph.
        for panel in panels:
            for tab in panel.tab_list:
                for column in list(tab.content.walk()):
                    if isinstance(column, BoxLayout) and column.orientation == "vertical" and len(column.children) == 2:
                        first, second = reversed(column.children)
                        if isinstance(first, Label) and isinstance(second, GridLayout):
                            column.remove_widget(second)
                            column.add_widget(second, index=len(column.children))


def compact_features(modal, column, app):
    original = list(reversed(column.children))
    sketch = next(w for w in original if isinstance(w, FloatLayout))
    construct = next(w for w in original if isinstance(w, GridLayout))
    construct.row_force_default = True
    construct.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16))
    construct.bind(minimum_height=construct.setter("height"))
    construct.height = construct.minimum_height
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
            actions = TouchActionRow()
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


def prepare_jog_overlay(modal, app):
    modal._mobile_jog_ready = True
    buttons = {widget.text: widget for widget in modal.walk() if isinstance(widget, JogTouchButton)}
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
    actions = TouchActionRow(spacing=dp(8))
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
        footer = TouchActionRow()
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
        footer = TouchActionRow()
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
            if not app.compact_layout or widget not in secondary:
                row.add_widget(widget)
        if app.compact_layout:
            row.add_widget(more)
    app.bind(compact_layout=reflow)
    modal.bind(on_dismiss=dismiss_sheet)
    reflow()
