"""Compact forms reuse their editors, values, focus and callbacks."""

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label

from carveracontroller.translation import tr

from .android_layout import (
    DialogLabel,
    TouchActionRow,
    _text_width,
    control_height,
    style_action,
)


class WorkspaceLayout:
    def __init__(self, popup):
        self.popup = popup
        self.grid = popup.ids.wcs_grid
        self.original = list(reversed(self.grid.children))
        self.geometry = {w: (w.size_hint, w.width, w.height) for w in self.original}
        self.activation_names = {self.original[index]: self.original[index].text for index in range(8, len(self.original), 8)}
        self.cards = None
        self.compact = None

    def update(self, *_args):
        app = App.get_running_app()
        if app.android_touch and not hasattr(self, '_error_body'):
            scroll = self.grid.parent
            grid = next(widget for widget in scroll.children if widget == self.grid)
            error = self.popup.ids.wcs_apply_error
            error = next(widget for widget in error.parent.children if widget == error)
            error.parent.remove_widget(error)
            # ScrollView retains viewport size callbacks after removal.
            grid.unbind(size=scroll._set_viewport_size)
            grid.unbind(size=scroll._trigger_update_from_scroll,
                        size_hint_min=scroll._trigger_update_from_scroll)
            scroll.remove_widget(grid)
            body = BoxLayout(orientation='vertical', spacing=dp(8), size_hint_y=None)
            body.bind(minimum_height=body.setter('height'))
            body.add_widget(error)
            body.add_widget(grid)
            scroll.add_widget(body)
            self._error_body = body
            def initialize_scroll(*_args):
                self.popup.unbind(on_open=initialize_scroll)
                def position_first_card(_dt):
                    scroll.scroll_y = 1
                    scroll._update_effect_y_bounds()
                Clock.schedule_once(position_first_card, .15)
            self.popup.bind(on_open=initialize_scroll)
            if self.popup._is_open:
                initialize_scroll()
            footer = self.popup.ids.btn_ok.parent
            parent, index = footer.parent, footer.parent.children.index(footer)
            help_button = next(widget for widget in self.popup.walk(restrict=True) if type(widget).__name__ == 'HelpButton')
            help_row = help_button.parent
            help_row.remove_widget(help_button)
            help_row.parent.remove_widget(help_row)
            index = parent.children.index(footer)
            buttons = list(reversed(footer.children))
            footer.clear_widgets()
            parent.remove_widget(footer)
            actions = TouchActionRow(spacing=dp(8))
            for widget in [*buttons, help_button]:
                actions.add_widget(widget)
            parent.add_widget(actions, index=min(index, len(parent.children)))
            from .mobile_tools import compact_actions
            more = compact_actions(self.popup, actions, lambda button: button in (self.popup.ids.btn_ok, self.popup.ids.btn_close), app)
            more.text = tr._('More')
        compact = app.android_touch and app.compact_layout
        if compact == self.compact:
            return
        self.compact = compact
        if app.android_touch:
            self.popup.ids.btn_ok.text = tr._("Apply offsets")
            style_action(self.popup.ids.btn_ok, "primary")
        self.grid.clear_widgets()
        for button, name in self.activation_names.items():
            button.text = tr._("Activate immediately") + " · " + name if compact else name
        if compact:
            self.grid.cols = 1
            if self.cards is None:
                self.cards = []
                for offset in range(8, len(self.original), 8):
                    items = self.original[offset:offset + 8]
                    if len(items) != 8:
                        continue
                    card = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8), padding=dp(8))
                    card.bind(minimum_height=card.setter("height"))
                    activate, *fields, clear, description = items
                    for widget in items:
                        widget.size_hint = (1, None)
                        widget.height = max(app.touch_target, dp(56))
                    card.add_widget(DialogLabel(text=self.activation_names[activate] + " — " + tr._("Numeric offsets apply together"), bold=True))
                    card.add_widget(activate)
                    values = GridLayout(cols=2, size_hint_y=None, spacing=dp(8))
                    values.bind(minimum_height=values.setter("height"))
                    for name, field in zip((f"X ({app.machine_units})", f"Y ({app.machine_units})", f"Z ({app.machine_units})", "A (degrees)", "Rotation (degrees)"), fields):
                        values.add_widget(DialogLabel(text=tr._(name)))
                        values.add_widget(field)
                    card.add_widget(values)
                    card.add_widget(clear)
                    card.add_widget(DialogLabel(text=tr._("Description — saved automatically on this device")))
                    card.add_widget(description)
                    self.cards.append(card)
            else:
                # Editors move back from the expanded grid into the existing cards.
                for card in self.cards:
                    for container, index, widget in sorted(card._editor_slots, key=lambda slot: slot[1]):
                        container.add_widget(widget, index=index)
            for widget in self.original[8:]:
                widget.size_hint = (1, None)
                widget.height = max(app.touch_target, dp(56))
            for card in self.cards:
                self.grid.add_widget(card)
        else:
            if self.cards:
                for card in self.cards:
                    slots = []
                    for widget in self.original:
                        if widget.parent is not None:
                            parent = widget.parent
                            slots.append((parent, parent.children.index(widget), widget))
                    card._editor_slots = [slot for slot in slots if slot[0] is card or slot[0].parent is card]
                for widget in self.original:
                    if widget.parent is not None:
                        widget.parent.remove_widget(widget)
            self.grid.cols = 8
            for widget in self.original:
                widget.size_hint, widget.width, widget.height = self.geometry[widget]
                self.grid.add_widget(widget)


def prepare_job_options(popup):
    """Keep each job summary beside its existing configuration action."""
    if getattr(popup, "_mobile_job_options", False):
        return
    popup._mobile_job_options = True
    popup.ids.txt_startline._mobile_width_text = popup.ids.txt_startline.hint_text
    origin = popup.ids.lb_origin
    options = origin.parent
    ordered = list(reversed(options.children))
    heading = ordered[ordered.index(origin) - 1]
    groups = []
    for label_name, button_name in (("lb_origin", "btn_origin"),
                                    ("lb_zprobe", "btn_zprobe"),
                                    ("lb_leveling", "btn_leveling")):
        label, button = popup.ids[label_name], popup.ids[button_name]
        row = button.parent
        for prop in ("height", "padding"):
            Builder.unbind_property(row, prop)
        row.padding = 0
        row.spacing = dp(12)
        row._mobile_form_fitted = True
        for filler in row.children:
            if filler is not button:
                filler.size_hint_x = None
                filler.width = 0
        options.remove_widget(label)
        for prop in ("height", "text_size", "font_size"):
            Builder.unbind_property(label, prop)
        label.size_hint = (1, None)
        label.font_size = sp(16)
        label.text_size = (max(1, label.width - dp(8)), None)
        label.bind(width=lambda item, width: setattr(
            item, "text_size", (max(1, width - dp(8)), None)))
        if label is origin:
            options.remove_widget(heading)
            Builder.unbind_property(heading, "height")
            heading._mobile_form_fitted = True
            for title in heading.children:
                if type(title) is Label:
                    Builder.unbind_property(title, "font_size")
                    title.font_size = sp(16)
                    title.bold = True
            summary = BoxLayout(orientation="vertical", size_hint_y=None)
            summary.bind(minimum_height=summary.setter("height"))
            summary.add_widget(heading)
            summary.add_widget(label)
            row.add_widget(summary, index=len(row.children))
        else:
            summary = label
            row.add_widget(label, index=len(row.children))
        button.size_hint = (None, None)
        button.pos_hint = {"center_y": .5}
        groups.append((row, summary, label, button))
    for item in options.children:
        if type(item) is Label and not item.text:
            Builder.unbind_property(item, "height")
            item.size_hint_y = None
            item.height = 0
    def fit(*_args):
        heading.height = max(dp(24), sp(16) * 1.3)
        for row, summary, label, button in groups:
            label.height = label.texture_size[1] + dp(8)
            button.width = min(max(dp(160), row.width * .43),
                               _text_width(button.text, button.font_name,
                                           button.font_size, button.bold) + dp(28))
            button.height = max(control_height(), button.texture_size[1] + dp(16))
            row.height = max(button.height, summary.height) + dp(8)
    for row, _summary, label, button in groups:
        row.bind(width=fit)
        _summary.bind(height=fit)
        label.bind(texture_size=fit)
        button.bind(texture_size=fit, font_size=fit)
    Metrics.bind(density=fit, fontscale=fit)
    fit()
