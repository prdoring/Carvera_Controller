"""Android main-page arrangements that retain the existing controls and views."""

from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView

from carveracontroller.translation import tr

from .android_layout import DialogLabel, DialogSurface, TouchActionRow


class MobileMainLayout:
    def __init__(self, app):
        self.app, self.root = app, app.root
        self.bar = self.root.ids.main_top_bar
        self.original = list(reversed(self.bar.children))
        self.geometry = {widget: (tuple(widget.size_hint), widget.width, widget.height,
                                  widget.size_hint_min_x, widget.size_hint_max_x) for widget in self.original}
        self.compact = None
        self.details = None
        self._control_prepared = False
        app.bind(compact_layout=self.update, state=self.refresh, machine_units=self.refresh,
                 has_4axis=self.update)
        self.root.coord_system_data_view.bind(main_text=self.refresh)
        self.root.content.bind(current=self.refresh)
        app.bind(android_keyboard_height=self._keyboard)
        self.update()

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
            self.bar.orientation = "horizontal"
            self.bar.height = max(dp(50), self.app.touch_target)
            for widget in self.original:
                hint, width, height, minimum, maximum = self.geometry[widget]
                widget.size_hint = hint
                widget.width, widget.height = width, height
                widget.size_hint_min_x, widget.size_hint_max_x = minimum, maximum
                self.bar.add_widget(widget)
            return
        self._prepare_control()
        self.bar.orientation = "vertical"
        coord_height = max(dp(64), sp(18) * 2 + dp(20))
        context = TouchActionRow(spacing=dp(6))
        context.bind(height=lambda _widget, height: setattr(self.bar, "height", coord_height + height + dp(12)))
        self.context_label = Button(font_size=sp(16))
        self.context_label.bind(on_release=lambda button: self.root.status_drop_down.open(button))
        details = Button(text=tr._("Machine / overrides"))
        details.bind(on_release=self.show_details)
        page = Button(text=tr._("Control / Files"))
        page.bind(on_release=lambda *_: setattr(self.root.content, "current", "File" if self.root.content.current == "Control" else "Control"))
        context.add_widget(self.context_label)
        context.add_widget(details)
        context.add_widget(page)
        self.page_button = page
        self.root.ids.main_menu.size_hint_x = 1
        self.root.ids.main_menu.width = dp(144)
        context.add_widget(self.root.ids.main_menu)
        self.bar.add_widget(context)
        self.bar.height = coord_height + context.height + dp(12)
        coords = GridLayout(cols=4 if self.app.has_4axis else 3, spacing=dp(6))
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

    def _keyboard(self, *_args):
        if not self.compact or not hasattr(self, "coordinate_row"):
            return
        visible = not self.app.android_keyboard_height
        self.coordinate_row.size_hint_y = None
        self.coordinate_row.height = self._coordinate_height if visible else 0
        self.coordinate_row.opacity = 1 if visible else 0
        self.coordinate_row.disabled = not visible
        self.bar.height = self.coordinate_row.height + self._context_row.height + dp(12)

    def refresh(self, *_args):
        if self.compact:
            self.context_label.text = f"{self.app.state} · {tr._('Work')} {self.app.machine_units}\n{self.root.coord_system_data_view.main_text}"
            self.page_button.text = tr._("Files ›") if self.root.content.current == "Control" else tr._("‹ Control")

    def show_details(self, *_args):
        if self.details is None:
            surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
            surface.add_widget(DialogLabel(text=tr._("Machine coordinates, active WCS and overrides"), bold=True))
            self.machine_position = DialogLabel()
            surface.add_widget(self.machine_position)
            for widget in (self.root.coord_system_data_view, self.root.feed_data_view,
                           self.root.spindle_laser_data_view, self.root.tool_data_view):
                widget.size_hint = (1, None)
                widget.size_hint_max_x = None
                widget.height = max(dp(64), sp(18) * 2 + dp(16))
                surface.add_widget(widget)
            footer = TouchActionRow()
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
        if self.details._is_open and not getattr(self, "_position_event", None):
            self._position_event = Clock.schedule_interval(self._refresh_machine_position, .25)

    def _stop_refresh(self, *_args):
        if getattr(self, "_position_event", None):
            self._position_event.cancel()
            self._position_event = None

    def _prepare_control(self):
        if getattr(self.root, "_mobile_control_prepared", False):
            return
        self.root._mobile_control_prepared = True
        center = self.root.ids.control_center
        groups = [child for child in reversed(center.children) if isinstance(child, BoxLayout)]
        center.clear_widgets()
        content = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        content.bind(minimum_height=content.setter("height"))
        scroll = ScrollView(do_scroll_x=False)
        for group, rows in zip(groups[:-1], (1, 4)):
            group.size_hint_y = None
            group.size_hint_min_y = 0
            group.height = rows * (self.app.touch_target + dp(12)) + dp(24)
            content.add_widget(group)
        scroll.add_widget(content)
        center.add_widget(scroll)
        jog = groups[-1]
        jog.size_hint_y = None
        jog.size_hint_min_y = 0
        jog.height = 2 * (self.app.touch_target + dp(12)) + dp(12)
        center.add_widget(jog)

    def stop(self):
        self._stop_refresh()
        self.app.unbind(compact_layout=self.update, state=self.refresh, machine_units=self.refresh,
                        has_4axis=self.update)
        self.root.coord_system_data_view.unbind(main_text=self.refresh)
        self.root.content.unbind(current=self.refresh)
        self.app.unbind(android_keyboard_height=self._keyboard)
