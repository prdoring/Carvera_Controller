"""Android main-page arrangements that retain the existing controls and views."""

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.togglebutton import ToggleButton

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
            self.root._mobile_top_geometry = {
                widget: (
                    tuple(widget.size_hint),
                    widget.width,
                    widget.height,
                    widget.size_hint_min_x,
                    widget.size_hint_max_x,
                )
                for widget in self.root._mobile_top_original
            }
        self.original = self.root._mobile_top_original
        self.geometry = self.root._mobile_top_geometry
        self._stopped = False
        self.compact = None
        self.details = None
        self._control_sizes = Clock.create_trigger(self._size_control_groups, 0)
        self._control_buttons = []

        app.bind(
            compact_layout=self.update,
            state=self.refresh,
            machine_units=self.refresh,
            has_4axis=self.update,
            jog_mode_text=self.refresh,
            jog_speed_text=self.refresh,
            jog_controls_enabled=self.refresh,
            playing=self.refresh,
            selected_remote_filename=self.refresh,
        )
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
        controls = ToggleButton(text=tr._("Viewer controls"), size_hint_y=None, height=control_height())
        controls.state = "down" if self.app.show_gcode_ctl_bar else "normal"
        controls.bind(on_release=lambda button: setattr(self.app, "show_gcode_ctl_bar", button.state == "down"))
        self.app.bind(show_gcode_ctl_bar=lambda _app, visible: setattr(controls, "state", "down" if visible else "normal"))
        options.add_widget(controls)
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
        if self._stopped:
            return
        key = (self.app.compact_layout, self.app.has_4axis)
        if getattr(self, "_key", None) == key:
            return
        self._key = key
        self.compact = self.app.compact_layout
        self._sync_view_toggle()
        if getattr(self, "_context_row", None) is not None:
            self._context_row.unbind(height=self._keyboard)
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
            self.bar.height = max(dp(60), self.app.touch_target)
            self.root.ids.main_menu.icon = "data/list.png"
            for widget in self.original:
                hint, width, height, minimum, maximum = self.geometry[widget]
                widget.size_hint = hint
                widget.width, widget.height = width, height
                widget.size_hint_min_x, widget.size_hint_max_x = minimum, maximum
                self.bar.add_widget(widget)
            self._sync_view_toggle()
            self._restore_desktop_control()
            return
        self._prepare_control()
        self.bar.orientation = "vertical"
        coord_height = max(control_height(), dp(52))
        context = TouchActionRow(spacing=dp(6))
        self.context_label = self.root.ids.status_data_view
        for widget in (
            self.context_label,
            self.root.tool_data_view,
            self.root.feed_data_view,
            self.root.spindle_laser_data_view,
            self.root.ids.main_menu,
        ):
            widget.size_hint = (1, 1)
            widget.size_hint_min_x = 0
            widget.size_hint_max_x = None
            context.add_widget(widget)
        self.root.ids.main_menu.icon = ""
        self.bar.add_widget(context)
        coords = BoxLayout(spacing=dp(6) if self.root.ids.viewer_panes_toggle.opacity else 0)
        axes = GridLayout(cols=5 if self.app.has_4axis else 4, spacing=dp(6))
        coords.add_widget(axes)
        self.workspace_button = self.root.coord_system_data_view
        self.workspace_button.size_hint = (1, 1)
        self.workspace_button.size_hint_max_x = None
        self.workspace_button.size_hint_min_x = 0
        axes.add_widget(self.workspace_button)
        for widget in (self.root.x_data_view, self.root.y_data_view, self.root.z_data_view, self.root.a_data_view):
            if widget is self.root.a_data_view and not self.app.has_4axis:
                continue
            widget.size_hint_max_x = None
            widget.size_hint_min_x = 0
            axes.add_widget(widget)
        coords.add_widget(self.root.ids.viewer_panes_toggle)
        self.bar.add_widget(coords)
        self.coordinate_row = coords
        self._context_row = context
        context.bind(height=self._keyboard)
        self._coordinate_height = coord_height
        self._keyboard()
        self.refresh()

    def _metrics(self, *_args):
        self._key = None
        self.update()
        if hasattr(self.root, "_mobile_action_groups"):
            self._size_control_groups()

    def _keyboard(self, *_args):
        if self._stopped or not self.compact or not hasattr(self, "coordinate_row"):
            return
        visible = not self.app.android_keyboard_height
        available = (
            Window.height
            - max(self.app.android_keyboard_height, self.app.safe_area_padding[3])
            - self.app.safe_area_padding[1]
        )
        context_visible = visible or available >= control_height() * 3 + dp(60)
        self._context_row.height = max(self._context_row.minimum_height, control_height()) if context_visible else 0
        self._context_row.opacity = int(context_visible)
        self._context_row.disabled = not context_visible
        self.bar.opacity = int(context_visible)
        self.bar.disabled = not context_visible
        self.coordinate_row.size_hint_y = None
        self.coordinate_row.height = self._coordinate_height if visible else 0
        self.coordinate_row.opacity = 1 if visible else 0
        self.coordinate_row.disabled = not visible
        self.bar.height = self.coordinate_row.height + self._context_row.height + (dp(6) if context_visible else 0)

    def _sync_view_toggle(self):
        button = self.root.ids.viewer_panes_toggle
        visible = self.app.android_touch and self.root.content.current == "File" and not self.app.android_keyboard_height
        button.size_hint = (None, 1)
        button.size_hint_min_x = self.app.touch_target if visible else 0
        button.width = self.app.touch_target if visible else 0
        button.opacity = int(visible)
        button.disabled = not visible
        if getattr(self, "coordinate_row", None) is not None:
            self.coordinate_row.spacing = dp(6) if visible else 0

    def refresh(self, *_args):
        if self._stopped:
            return
        self._sync_view_toggle()
        layout = getattr(self.app, "_touch_layout", None)
        if layout is not None:
            layout._update()
        if self.compact:
            self._keyboard()
            self._context_row._columns()

    def show_details(self, *_args):
        if self.details is None:
            surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
            surface.add_widget(DialogLabel(text=tr._("Machine and work coordinates"), bold=True))
            self.machine_position = DialogLabel()
            surface.add_widget(self.machine_position)
            self.working_position = DialogLabel()
            surface.add_widget(self.working_position)
            footer = DialogActions()
            close = Button(text=tr._("Close"))
            footer.add_widget(close)
            surface.add_widget(footer)
            self.details = Popup(title=tr._("Machine details"), content=surface, size_hint=(0.9, 0.9))
            close.bind(on_release=lambda *_: self.details.dismiss())
            self.details.bind(on_open=self._refresh_machine_position, on_dismiss=self._stop_refresh)
        self.details.open()

    def _refresh_machine_position(self, *_args):
        from carveracontroller.CNC import CNC

        self.machine_position.text = (
            tr._("Machine")
            + " "
            + self.app.machine_units
            + "\n"
            + "   ".join(f"{axis.upper()} {float(CNC.vars.get('m' + axis, 0)):+.3f}" for axis in ("x", "y", "z"))
        )
        self.working_position.text = (
            tr._("Work position")
            + " "
            + self.app.machine_units
            + "\n"
            + "   ".join(f"{axis.upper()} {float(CNC.vars.get('w' + axis, 0)):+.3f}" for axis in ("x", "y", "z"))
        )
        if self.details._is_open and not getattr(self, "_position_event", None):
            self._position_event = Clock.schedule_interval(self._refresh_machine_position, 0.25)

    def _stop_refresh(self, *_args):
        if getattr(self, "_position_event", None):
            self._position_event.cancel()
            self._position_event = None

    def _prepare_control(self):
        center = self.root.ids.control_center
        if not hasattr(self.root, "_mobile_action_groups"):
            self.root._mobile_control_original = list(reversed(center.children))
            self.root._mobile_action_groups = [
                self.root.ids[key] for key in ("control_macros", "control_actions", "control_modes")
            ]
        if not hasattr(self.root, "_mobile_group_geometry"):
            self.root._mobile_group_geometry = {}
            for group in self.root._mobile_action_groups:
                self.root._mobile_group_geometry[group] = {
                    name: list(value) if isinstance(value, (list, tuple)) else value
                    for name in ("size_hint", "padding", "size_hint_min_y", "height")
                    for value in (getattr(group, name),)
                }
                for grid in (widget for widget in group.walk(restrict=True) if isinstance(widget, GridLayout)):
                    self.root._mobile_group_geometry[grid] = {
                        name: list(value) if isinstance(value, (list, tuple)) else value
                        for name in ("cols", "rows", "padding", "spacing", "row_force_default", "row_default_height")
                        for value in (getattr(grid, name),)
                    }
        self._place_input_toggles(True)
        quick_grid = next(
            item for item in self.root._mobile_action_groups[1].walk(restrict=True) if isinstance(item, GridLayout)
        )
        if not hasattr(self.root, "_mobile_quick_cells"):
            self.root._mobile_quick_cells = list(reversed(quick_grid.children))
        cells = [
            self.root.ids[key].parent
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
            )
        ]
        quick_grid.clear_widgets()
        for cell in cells:
            quick_grid.add_widget(cell)
        self._prepare_control_host()
        center.clear_widgets()
        center.padding = dp(4)
        center.spacing = dp(6)
        center.size_hint = (1, None)
        for group in (
            self.root._mobile_action_groups[2],
            self.root._mobile_action_groups[1],
            self.root._mobile_action_groups[0],
        ):
            if group.parent is not None:
                group.parent.remove_widget(group)
            group.size_hint_y = None
            group.size_hint_min_y = 0
            group.padding = 0
            center.add_widget(group)
        self.root.ids.control_center.bind(width=self._control_sizes)
        self._bind_control_sizes()

    def _prepare_control_host(self):
        center = self.root.ids.control_center
        if not hasattr(self.root, "_mobile_control_host"):
            parent = center.parent
            self.root._mobile_control_host = (parent, parent.children.index(center))
            self.root._mobile_jog_panels = [item for item in parent.children if item is not center]
            self.root._mobile_jog_minimums = [item.size_hint_min_x for item in self.root._mobile_jog_panels]
            self.root._mobile_control_scroll = ScrollView(do_scroll_x=False, size_hint_x=1.9, bar_width=dp(3))
        scroll = self.root._mobile_control_scroll
        for panel in self.root._mobile_jog_panels:
            panel.size_hint_min_x = self.app.touch_target * 3 + dp(4)
        if center.parent is not scroll:
            parent, index = self.root._mobile_control_host
            if center.parent is not None:
                center.parent.remove_widget(center)
            if scroll.parent is None:
                parent.add_widget(scroll, index=min(index, len(parent.children)))
            scroll.add_widget(center)
            center.bind(minimum_height=self._fit_control_height)
            scroll.bind(height=self._fit_control_height)
        self._fit_control_height()

    def _fit_control_height(self, *_args):
        if self.compact and hasattr(self.root, "_mobile_control_scroll"):
            center = self.root.ids.control_center
            center.height = max(center.minimum_height, self.root._mobile_control_scroll.height)

    def _restore_control_host(self):
        if not hasattr(self.root, "_mobile_control_host"):
            return
        center = self.root.ids.control_center
        scroll = self.root._mobile_control_scroll
        parent, index = self.root._mobile_control_host
        center.unbind(minimum_height=self._fit_control_height)
        scroll.unbind(height=self._fit_control_height)
        if center.parent is scroll:
            scroll.remove_widget(center)
            parent.remove_widget(scroll)
            parent.add_widget(center, index=min(index, len(parent.children)))
        for panel, minimum in zip(self.root._mobile_jog_panels, self.root._mobile_jog_minimums):
            panel.size_hint_min_x = minimum
        center.size_hint = (1, 1)
        center.padding = dp(16)
        center.spacing = dp(12)

    def _restore_desktop_control(self):
        if not hasattr(self.root, "_mobile_action_groups"):
            return
        self._restore_control_host()
        self._place_input_toggles(False)
        center = self.root.ids.control_center
        center.clear_widgets()
        for widget in self.root._mobile_control_original:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
            center.add_widget(widget)
        for widget, geometry in self.root._mobile_group_geometry.items():
            if isinstance(widget, GridLayout):
                widget.rows = None
            for name, value in geometry.items():
                setattr(widget, name, value)
            if hasattr(widget, "_content_row_height"):
                del widget._content_row_height
        for button in self._control_buttons:
            button._compact_auxiliary = False
            button.bold = True
            button.font_size = sp(16)
            button._mobile_text_sp = 16
        style_action(self.root.ids.jog_mode_btn, "primary")

    def _place_input_toggles(self, compact):
        groups = self.root._mobile_action_groups
        grids = [
            next(item for item in group.walk(restrict=True) if isinstance(item, GridLayout))
            for group in (groups[0], groups[-1])
        ]
        if not hasattr(self.root, "_mobile_input_cells"):
            self.root._mobile_input_cells = list(reversed(grids[1].children))[2:]
        for grid in grids:
            grid.rows = None
        grids[0].cols = 5 if compact else 3
        grids[1].cols = 2
        if not compact and hasattr(self.root, "_mobile_quick_cells"):
            quick_grid = next(item for item in groups[1].walk(restrict=True) if isinstance(item, GridLayout))
            quick_grid.clear_widgets()
            for cell in self.root._mobile_quick_cells:
                quick_grid.add_widget(cell)
        destination = grids[0] if compact else grids[1]
        for cell in self.root._mobile_input_cells:
            if cell.parent is not None:
                cell.parent.remove_widget(cell)
            destination.add_widget(cell)

    def _bind_control_sizes(self):
        for group in self.root._mobile_action_groups:
            for button in group.walk(restrict=True):
                if isinstance(button, Button) and button not in self._control_buttons:
                    button.bind(text=self._control_sizes, texture_size=self._control_sizes)
                    self._control_buttons.append(button)
        self._control_sizes()

    def _size_control_groups(self, *_args):
        if self._stopped or not self.compact:
            return
        target = control_height()
        groups = self.root._mobile_action_groups
        for group, rows in zip(groups, (1, 3, 2)):
            grids = [item for item in group.walk(restrict=True) if isinstance(item, GridLayout)]
            if grids:
                grid = grids[0]
                grid.padding = 0
                grid.spacing = dp(4)
                preferred = 5 if group is groups[0] else 4 if group is groups[1] else 2
                size = sp(14 if group is groups[0] else 16)
                words = [
                    _text_width(word, button.font_name, size, group is not groups[0])
                    for button in grid.walk(restrict=True)
                    if isinstance(button, Button)
                    for word in button.text.split()
                ]
                minimum = max([target] + words) + dp(8 if group is groups[0] else 12)
                grid.cols = max(1, min(preferred, int((grid.width + dp(4)) / (minimum + dp(4)))))
                grid.rows = None
                grid.row_force_default = True
                for cell in grid.children:
                    cell.padding = 0
                    for button in cell.walk(restrict=True):
                        if isinstance(button, Button):
                            button._compact_auxiliary = self.compact and group is groups[0]
                            button.font_size = sp(14 if button._compact_auxiliary else 16)
                            button.bold = group is not groups[0]
                            button.text_size = (
                                max(
                                    dp(24),
                                    (grid.width - grid.spacing[0] * (grid.cols - 1)) / grid.cols
                                    - dp(4 if group is groups[0] else 12),
                                ),
                                None,
                            )
                            button.halign = "center"
                            button.valign = "middle"
                            button.texture_update()
                grid.row_default_height = max(
                    [target]
                    + [
                        button.texture_size[1] + dp(10)
                        for button in grid.walk(restrict=True)
                        if isinstance(button, Button)
                    ]
                )
                grid._content_row_height = grid.row_default_height
                rows = (len(grid.children) + grid.cols - 1) // grid.cols
                natural = grid.row_default_height
            else:
                natural = target
            group.height = rows * natural + max(0, rows - 1) * dp(4) + dp(4)
        for button in self._control_buttons:
            button.size_hint_y = 1
        style_action(self.root.ids.jog_mode_btn, "primary")
        self._fit_control_height()

    def stop(self):
        if self._stopped:
            return
        self._stopped = True
        if getattr(self, "_context_row", None) is not None:
            self._context_row.unbind(height=self._keyboard)
        self._control_sizes.cancel()
        self.root.ids.control_center.unbind(width=self._control_sizes)
        for group in getattr(self.root, "_mobile_action_groups", []):
            group.unbind(width=self._control_sizes)
        for button in self._control_buttons:
            button.unbind(text=self._control_sizes, texture_size=self._control_sizes)
        self._stop_refresh()
        self._restore_desktop_control()
        for widget in self.original:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)
        self.bar.clear_widgets()
        self.bar.orientation = "horizontal"
        self.bar.height = max(dp(60), self.app.touch_target)
        for widget in self.original:
            hint, width, height, minimum, maximum = self.geometry[widget]
            widget.size_hint = hint
            widget.width, widget.height = width, height
            widget.size_hint_min_x, widget.size_hint_max_x = minimum, maximum
            self.bar.add_widget(widget)
        self.app.unbind(
            compact_layout=self.update,
            state=self.refresh,
            machine_units=self.refresh,
            has_4axis=self.update,
            jog_mode_text=self.refresh,
            jog_speed_text=self.refresh,
            jog_controls_enabled=self.refresh,
            playing=self.refresh,
            selected_remote_filename=self.refresh,
        )
        self.root.coord_system_data_view.unbind(main_text=self.refresh)
        self.root.content.unbind(current=self.refresh)
        self.app.unbind(android_keyboard_height=self._keyboard)
        Metrics.unbind(density=self._metrics, fontscale=self._metrics)
