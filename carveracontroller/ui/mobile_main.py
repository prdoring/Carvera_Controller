"""Android main-page arrangements that retain the existing controls and views."""

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.popup import Popup

from carveracontroller.translation import tr

from .android_layout import (
    DialogActions,
    DialogLabel,
    DialogSurface,
    TouchActionRow,
    _text_width,
    control_height,
    style_action,
)


class MobileMainLayout:
    def __init__(self, app):
        self.app, self.root = app, app.root
        self.bar = self.root.ids.main_top_bar
        if not hasattr(self.root, "_mobile_top_original"):
            self.root._mobile_top_original = list(reversed(self.bar.children))
            self.root._mobile_top_geometry = {widget: (tuple(widget.size_hint), widget.width, widget.height,
                widget.size_hint_min_x, widget.size_hint_max_x) for widget in self.root._mobile_top_original}
        self.original = self.root._mobile_top_original
        self.geometry = self.root._mobile_top_geometry
        self.compact = None
        self.details = None
        self._control_prepared = False
        self._control_sizes = Clock.create_trigger(self._size_control_groups, 0)
        self._control_buttons = []
        app.bind(compact_layout=self.update, state=self.refresh, machine_units=self.refresh,
                 has_4axis=self.update, jog_mode_text=self.refresh, jog_speed_text=self.refresh,
                 jog_controls_enabled=self.refresh, playing=self.refresh, selected_remote_filename=self.refresh)
        self.root.coord_system_data_view.bind(main_text=self.refresh)
        self.root.content.bind(current=self.refresh)
        app.bind(android_keyboard_height=self._keyboard)
        Metrics.bind(density=self._metrics, fontscale=self._metrics)
        self._prepare_view_options()
        self.update()

    def _prepare_view_options(self):
        if hasattr(self.root, "_mobile_view_options"):
            return
        row = self.root.ids.viewer_panes
        options = DialogSurface(orientation="vertical", padding=dp(8))
        for proxy in (self.root.ids.viewer_legend, self.root.ids.viewer_camera):
            widget = next(child for child in row.children if child == proxy)
            row.remove_widget(widget)
            widget.size_hint_y = None
            widget.height = control_height()
            options.add_widget(widget)
        footer = DialogActions()
        close = Button(text=tr._("Close"))
        footer.add_widget(close)
        options.add_widget(footer)
        sheet = Popup(title=tr._("Preview options"), content=options)
        close.bind(on_release=lambda *_: sheet.dismiss())
        button = Button(text=tr._("Views"))
        button.bind(on_release=lambda *_: sheet.open())
        row.add_widget(button)
        self.root._mobile_view_options = sheet

    def update(self, *_args):
        key = (self.app.compact_layout, self.app.has_4axis)
        if getattr(self, "_key", None) == key:
            return
        self._key = key
        self.compact = self.app.compact_layout
        if self.details is not None:
            self.details.dismiss()
            self.details = None
        for widget in self.original:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
        self.bar.clear_widgets()
        if not self.compact:
            self.bar.opacity = 1
            self.bar.disabled = False
            self.bar.orientation = "horizontal"
            self.bar.height = max(dp(50), self.app.touch_target)
            self.root.ids.main_menu.icon = "data/list.png"
            for widget in self.original:
                hint, width, height, minimum, maximum = self.geometry[widget]
                widget.size_hint = hint
                widget.width, widget.height = width, height
                widget.size_hint_min_x, widget.size_hint_max_x = minimum, maximum
                self.bar.add_widget(widget)
            if hasattr(self.root, "_mobile_action_groups"):
                center = self.root.ids.control_center
                center.clear_widgets()
                for group in self.root._mobile_action_groups[:-1]:
                    if group.parent is not None:
                        group.parent.remove_widget(group)
                    center.add_widget(group)
                center.add_widget(self.root._mobile_jog_summary)
                self._control_sizes()
            return
        self._prepare_control()
        self.bar.orientation = "vertical"
        coord_height = control_height()
        context = BoxLayout(size_hint_y=None, height=control_height(), spacing=dp(6))
        context.bind(height=self._keyboard)
        self.context_label = Button(font_size=sp(16))
        self.context_label.bind(on_release=lambda button: self.root.status_drop_down.open(button))
        details = Button(text=tr._("Actions"))
        details.bind(on_release=lambda *_: self.show_details() if self._positions_folded else self.show_machine_actions())
        self.actions_button = details
        page = Button(text=tr._("Control / Files"))
        page.bind(on_release=lambda *_: setattr(self.root.content, "current", "File" if self.root.content.current == "Control" else "Control"))
        context.add_widget(self.context_label)
        context.add_widget(details)
        context.add_widget(page)
        self.page_button = page
        self.root.ids.main_menu.size_hint_x = 1
        self.root.ids.main_menu.width = dp(144)
        self.root.ids.main_menu.icon = ""
        context.add_widget(self.root.ids.main_menu)
        self.bar.add_widget(context)
        self.bar.height = coord_height + context.height + dp(6)
        coords = GridLayout(cols=5 if self.app.has_4axis else 4, spacing=dp(6))
        self.workspace_button = Button(text=self.root.coord_system_data_view.main_text)
        self.workspace_button.bind(on_release=lambda *_: self.root.wcs_settings_popup.open())
        coords.add_widget(self.workspace_button)
        for widget in (self.root.x_data_view, self.root.y_data_view, self.root.z_data_view, self.root.a_data_view):
            if widget is self.root.a_data_view and not self.app.has_4axis:
                continue
            widget.size_hint_max_x = None
            widget.size_hint_min_x = 0
            coords.add_widget(widget)
        self.bar.add_widget(coords)
        self.coordinate_row = coords
        self._context_row = context
        self._coordinate_height = coord_height
        self._keyboard()
        self.refresh()

    def _metrics(self, *_args):
        self._key = None
        self.update()
        if hasattr(self.root, "_mobile_action_groups"):
            self._size_control_groups()

    def _keyboard(self, *_args):
        if not self.compact or not hasattr(self, "coordinate_row"):
            return
        visible = not self.app.android_keyboard_height
        available = Window.height - max(self.app.android_keyboard_height, self.app.safe_area_padding[3]) - self.app.safe_area_padding[1]
        self._positions_folded = self.root.content.current == "File" and available < control_height() * 7
        visible = visible and not self._positions_folded
        self.actions_button.text = self.root.coord_system_data_view.main_text if self._positions_folded else tr._("Actions")
        context_visible = visible or available >= control_height() * 3 + dp(60)
        self._context_row.height = control_height() if context_visible else 0
        self._context_row.opacity = int(context_visible)
        self._context_row.disabled = not context_visible
        self.bar.opacity = int(context_visible)
        self.bar.disabled = not context_visible
        self.coordinate_row.size_hint_y = None
        self.coordinate_row.height = self._coordinate_height if visible else 0
        self.coordinate_row.opacity = 1 if visible else 0
        self.coordinate_row.disabled = not visible
        self.bar.height = self.coordinate_row.height + self._context_row.height + (dp(6) if context_visible else 0)

    def refresh(self, *_args):
        layout = getattr(self.app, "_touch_layout", None)
        if layout is not None:
            layout._update()
        if hasattr(self.root, "_mobile_jog_summary"):
            mode = self.app.jog_mode_text.replace(tr._("Jog Mode:"), "")
            speed = self.app.jog_speed_text.replace(tr._("Jog Speed:"), "")
            self.root._mobile_jog_summary.text = tr._("Jog") + f"\n{mode} · {speed}"
            self.root._mobile_jog_summary.disabled = not self.app.jog_controls_enabled
        if self.compact:
            self._keyboard()
            self.context_label.text = f"{self.app.state} {self.app.machine_units}"
            self.workspace_button.text = self.root.coord_system_data_view.main_text
            self.page_button.text = tr._("Files ›") if self.root.content.current == "Control" else tr._("‹ Control")
            for button in self._context_row.children:
                button.size_hint_x = _text_width(button.text, button.font_name, sp(16)) + dp(24)

    def show_details(self, *_args):
        if self.details is None:
            surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
            surface.add_widget(DialogLabel(text=tr._("Machine coordinates, active WCS and overrides"), bold=True))
            self.machine_position = DialogLabel()
            surface.add_widget(self.machine_position)
            self.working_position = DialogLabel()
            surface.add_widget(self.working_position)
            for widget in (self.root.coord_system_data_view, self.root.feed_data_view,
                           self.root.spindle_laser_data_view, self.root.tool_data_view):
                widget.size_hint = (1, None)
                widget.size_hint_max_x = None
                widget.height = max(dp(64), sp(18) * 2 + dp(16))
                surface.add_widget(widget)
            footer = DialogActions()
            close = Button(text=tr._("Close"))
            footer.add_widget(close)
            surface.add_widget(footer)
            self.details = Popup(title=tr._("Machine details"), content=surface, size_hint=(.9, .9))
            close.bind(on_release=lambda *_: self.details.dismiss())
            self.details.bind(on_open=self._refresh_machine_position, on_dismiss=self._stop_refresh)
        self.details.open()

    def _refresh_machine_position(self, *_args):
        from carveracontroller.CNC import CNC

        self.machine_position.text = tr._("Machine") + " " + self.app.machine_units + "\n" + "   ".join(
            f"{axis.upper()} {float(CNC.vars.get('m' + axis, 0)):+.3f}" for axis in ("x", "y", "z"))
        self.working_position.text = tr._("Work position") + " " + self.app.machine_units + "\n" + "   ".join(
            f"{axis.upper()} {float(CNC.vars.get('w' + axis, 0)):+.3f}" for axis in ("x", "y", "z"))
        if self.details._is_open and not getattr(self, "_position_event", None):
            self._position_event = Clock.schedule_interval(self._refresh_machine_position, .25)

    def _stop_refresh(self, *_args):
        if getattr(self, "_position_event", None):
            self._position_event.cancel()
            self._position_event = None

    def _prepare_control(self):
        if getattr(self.root, "_mobile_control_prepared", False):
            center = self.root.ids.control_center
            center.clear_widgets()
            center.add_widget(BoxLayout())
            center.add_widget(self.root._mobile_jog_summary)
            center.add_widget(BoxLayout())
            self._bind_control_sizes()
            return
        self.root._mobile_control_prepared = True
        center = self.root.ids.control_center
        groups = [child for child in reversed(center.children) if isinstance(child, BoxLayout)]
        center.clear_widgets()
        center.add_widget(BoxLayout())
        self.root._mobile_jog_buttons = [w for w in groups[-1].walk(restrict=True) if isinstance(w, Button)]
        for button in self.root._mobile_jog_buttons:
            button.parent.remove_widget(button)
        summary = Button(size_hint_y=None, font_size=sp(16))
        summary.bind(on_release=self.show_jog_settings, texture_size=self._control_sizes)
        self.root._mobile_jog_summary = summary
        center.add_widget(summary)
        center.add_widget(BoxLayout())
        self.root._mobile_action_groups = groups
        self._bind_control_sizes()
        self._size_control_groups()

    def show_machine_actions(self, *_args):
        from .touch import cancel_jog

        cancel_jog()
        surface = DialogSurface(orientation="vertical", padding=dp(8), presentation="workspace")
        details = Button(text=tr._("Machine details and overrides"), size_hint_y=None, height=control_height())
        style_action(details)
        sheet = Popup(title=tr._("Machine actions"), content=surface, size_hint=(.9, .9))
        details.bind(on_release=lambda *_: (sheet.dismiss(), self.show_details()))
        surface.add_widget(details)
        help_button = Button(text=tr._("Control help"), size_hint_y=None, height=control_height())
        help_button.bind(on_release=lambda *_: self.app._touch_layout.show_help(self.root))
        surface.add_widget(help_button)
        file_button = self.root.ids.main_file_button
        browse = Button(text=tr._("Browse files"), size_hint_y=None, height=control_height(), disabled=file_button.disabled)
        browse.bind(on_release=lambda *_: (sheet.dismiss(), file_button.dispatch("on_release")))
        def availability(_button, disabled):
            browse.disabled = disabled
        file_button.bind(disabled=availability)
        sheet.bind(on_dismiss=lambda *_: file_button.unbind(disabled=availability))
        surface.add_widget(browse)
        for group in self.root._mobile_action_groups[:-1]:
            if group.parent is not None:
                group.parent.remove_widget(group)
            group.size_hint_y = None
            group.size_hint_min_y = 0
            group.bind(width=self._control_sizes)
            surface.add_widget(group)
        footer = DialogActions()
        close = Button(text=tr._("Close"))
        close.bind(on_release=lambda *_: sheet.dismiss())
        footer.add_widget(close)
        surface.add_widget(footer)
        sheet.open()
        self._control_sizes()

    def _bind_control_sizes(self):
        self.root._mobile_jog_summary.bind(on_release=self.show_jog_settings, texture_size=self._control_sizes)
        for group in self.root._mobile_action_groups:
            for button in group.walk(restrict=True):
                if isinstance(button, Button) and button not in self._control_buttons:
                    button.bind(text=self._control_sizes, texture_size=self._control_sizes)
                    self._control_buttons.append(button)
        self._control_sizes()

    def show_jog_settings(self, *_args):
        from .touch import cancel_jog

        cancel_jog()
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        choices = TouchActionRow(stacked=True, spacing=dp(8))
        def availability(*_args):
            choices.disabled = not self.app.jog_controls_enabled
        availability()
        self.app.bind(jog_controls_enabled=availability)
        for button in self.root._mobile_jog_buttons:
            if button.parent is not None:
                button.parent.remove_widget(button)
            choices.add_widget(button)
        surface.add_widget(choices)
        footer = DialogActions()
        close = Button(text=tr._("Close"))
        footer.add_widget(close)
        surface.add_widget(footer)
        sheet = Popup(title=tr._("Jog settings"), content=surface, size_hint=(.85, .9))
        sheet.bind(on_dismiss=lambda *_: self.app.unbind(jog_controls_enabled=availability))
        close.bind(on_release=lambda *_: sheet.dismiss())
        sheet.open()

    def _size_control_groups(self, *_args):
        target = control_height()
        groups = self.root._mobile_action_groups
        for group, rows in zip(groups[:-1], (1, 4)):
            grids = [item for item in group.walk(restrict=True) if isinstance(item, GridLayout)]
            if grids:
                grid = grids[0]
                needed = max([target] + [_text_width(button.text, button.font_name, sp(16)) + dp(32)
                                        for button in group.walk(restrict=True) if isinstance(button, Button)])
                grid.cols = max(1, min(3, int(max(1, group.width - dp(32)) / needed)))
                grid.rows = None
                grid.row_force_default = True
                grid.row_default_height = max([target] + [button.texture_size[1] + dp(16) for button in grid.children if isinstance(button, Button)])
                rows = (len(grid.children) + grid.cols - 1) // grid.cols
                natural = grid.row_default_height
            else:
                natural = target
            group.height = rows * (natural + dp(8)) + dp(32)
        self.root._mobile_jog_summary.height = max(target, self.root._mobile_jog_summary.texture_size[1] + dp(16))
        for button in self._control_buttons:
            button.size_hint_y = 1

    def stop(self):
        self._control_sizes.cancel()
        for group in getattr(self.root, "_mobile_action_groups", []):
            group.unbind(width=self._control_sizes)
        if hasattr(self.root, "_mobile_jog_summary"):
            self.root._mobile_jog_summary.unbind(on_release=self.show_jog_settings, texture_size=self._control_sizes)
        for button in self._control_buttons:
            button.unbind(text=self._control_sizes, texture_size=self._control_sizes)
        self._stop_refresh()
        self.app.unbind(compact_layout=self.update, state=self.refresh, machine_units=self.refresh,
                        has_4axis=self.update, jog_mode_text=self.refresh, jog_speed_text=self.refresh,
                        jog_controls_enabled=self.refresh, playing=self.refresh, selected_remote_filename=self.refresh)
        self.root.coord_system_data_view.unbind(main_text=self.refresh)
        self.root.content.unbind(current=self.refresh)
        self.app.unbind(android_keyboard_height=self._keyboard)
        Metrics.unbind(density=self._metrics, fontscale=self._metrics)
