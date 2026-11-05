"""Everyday System settings for images with the original recovery helper."""

import math
import time
from concurrent.futures import ThreadPoolExecutor

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.vkeyboard import VKeyboard

from carveracontroller.translation import tr

from . import theme
from .editing import EditingTextInput
from .kiosk_legacy import LegacySystem, validate_wifi
from .touch import Gesture, gesture_owners


class SystemAction(Button):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(52), **kwargs)
        self.gesture = None
        gesture_owners.add(self)
        self.bind(width=self._wrap, disabled=self._disabled, parent=self._disabled)

    def _wrap(self, *_args):
        self.text_size = (max(1, self.width - dp(16)), None)
        self.halign, self.valign = "center", "middle"

    def _disabled(self, *_args):
        if self.disabled or self.parent is None:
            self.cancel_gestures()

    def cancel_gestures(self):
        if self.gesture:
            self.gesture.touch.ungrab(self)
            self.gesture.cancel()
        self.gesture = None
        self.state = "normal"

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if self.disabled or self.gesture:
            return True
        if ("button" in touch.profile and touch.button != "left") or getattr(touch, "is_mouse_scrolling", False):
            return False
        self.gesture = Gesture(touch)
        touch.grab(self)
        FocusBehavior.ignored_touch.append(touch)
        self.state = "down"
        return True

    def on_touch_move(self, touch):
        if self.gesture and self.gesture.touch is touch:
            self.gesture.move()
            if not self.collide_point(*touch.pos):
                self.gesture.cancel()
            self.state = "normal" if self.gesture.cancelled else "down"
            return True
        return False

    def on_touch_up(self, touch):
        if not self.gesture or self.gesture.touch is not touch:
            return False
        accepted = (
            self.gesture.finish()
            and self.collide_point(*touch.pos)
            and not self.disabled
            and not touch.ud.get("carvera_native_cancelled")
        )
        self.cancel_gestures()
        if accepted:
            Clock.schedule_once(
                lambda _dt: self.dispatch("on_release") if self.get_root_window() and not self.disabled else None
            )
        return True


class SystemField(EditingTextInput):
    def __init__(self, **kwargs):
        super().__init__(
            multiline=False,
            use_bubble=False,
            use_handles=False,
            unfocus_on_touch=False,
            input_policy="text",
            size_hint_y=None,
            height=dp(52),
            **kwargs,
        )

    def on_touch_down(self, touch):
        if getattr(touch, "button", "left") in {"middle", "right"}:
            return False
        return super().on_touch_down(touch)


class SystemText(Label):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, halign="left", valign="middle", **kwargs)
        self.bind(width=self._fit, texture_size=self._fit)
        self._fit()

    def _fit(self, *_args):
        self.text_size = (max(1, self.width), None)
        self.height = max(dp(28), self.texture_size[1] + dp(8))


class SystemScroll(ScrollView):
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            touch.ud.setdefault("legacy_system_start", (touch.sx * Window.width, touch.sy * Window.height))
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        start = touch.ud.get("legacy_system_start")
        if start and math.dist(start, (touch.sx * Window.width, touch.sy * Window.height)) > dp(8):
            touch.ud["legacy_system_dragged"] = True
        return super().on_touch_move(touch)

    def _change_touch_mode(self, *_args):
        # Focus fields only after a completed tap, never during a slow scroll.
        return None

    def simulate_touch_down(self, touch):
        if (
            touch.ud.get("carvera_dragged")
            or touch.ud.get("carvera_touch_cancelled")
            or touch.ud.get("legacy_system_dragged")
        ):
            return False
        return super().simulate_touch_down(touch)


class KioskSystem(ModalView):
    def __init__(self, app, backend=None, **kwargs):
        super().__init__(size_hint=(0.96, 0.96), auto_dismiss=False, **kwargs)
        self.app = app
        self.backend = backend or LegacySystem()
        self.busy = False
        self._active = False
        self._reading = False
        self._generation = 0
        self._worker = None
        self._action_future = None
        self._saved_softinput_mode = None
        self._sheet = None
        self.section = "Overview"
        self.details = {}
        self.active_field = None
        self.actions = []
        self.column = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        self.add_widget(self.column)
        header = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(12))
        self.header = header
        header.add_widget(SystemText(text=tr._("System"), font_size=sp(24), bold=True))
        close = self.button(tr._("Close"), self.dismiss)
        close.size_hint_x, close.width = None, dp(140)
        header.add_widget(close)
        self.column.add_widget(header)
        self.navigation = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(12))
        self.nav = {}
        for name in ("Overview", "Network", "Controller"):
            self.nav[name] = self.button(tr._(name), lambda name=name: self.choose(name))
            self.navigation.add_widget(self.nav[name])
        self.column.add_widget(self.navigation)
        self.scroll = SystemScroll(do_scroll_x=False, always_overscroll=False, bar_width=dp(8))
        self.content = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12), padding=dp(8))
        self.content.bind(minimum_height=self.content.setter("height"))
        self.scroll.add_widget(self.content)
        self.column.add_widget(self.scroll)
        self.footer = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(12))
        self.paste = self.button(tr._("Paste"), self.paste_text)
        self.hide = self.button(tr._("Hide keyboard"), self.hide_keyboard)
        self.connect = self.button(tr._("Connect Wi-Fi"), lambda: self.confirm("wifi"))
        self.keep = self.button(tr._("Keep new network"), lambda: self.confirm("wifi-confirm"))
        self.stop = self.button(tr._("Emergency stop"), self.emergency_stop)
        for widget in (self.paste, self.hide, self.connect, self.keep, self.stop):
            self.footer.add_widget(widget)
        self.column.add_widget(self.footer)
        self.ssid = SystemField(hint_text=tr._("Network name (SSID)"))
        self.password = SystemField(password=True, hint_text=tr._("8–63 bytes"))
        for field in (self.ssid, self.password):
            field.bind(focus=self.focus_changed)
        self.status = SystemText(color=theme.SECONDARY)
        self.info = SystemText()
        self.notice = SystemText(color=theme.ACCENT)
        self._geometry = Clock.create_trigger(self.reflow, 0)
        self._reveal_signature = None
        self.bind(size=self._geometry)
        self.scroll.bind(size=self._geometry)
        self.choose("Overview")

    def button(self, text, callback):
        widget = SystemAction(text=text)
        widget.bind(on_release=lambda *_args: callback())
        return widget

    def on_pre_open(self):
        self._saved_softinput_mode = Window.softinput_mode
        # This modal reserves keyboard space itself; window panning would move it twice.
        Window.softinput_mode = ""
        self._generation += 1
        self._active = True
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legacy-system")
        self.app.bind(android_keyboard_height=self._geometry)
        Window.bind(on_focus=self.window_focus)
        self._poll = Clock.schedule_interval(lambda _dt: self.refresh(), 3)
        self._countdown = Clock.schedule_interval(lambda _dt: self.update_controls(), 0.5)
        self.refresh()
        self._geometry()

    def dismiss(self, *args, **kwargs):
        if self.busy and not kwargs.get("force"):
            self.show_status(tr._("A System action is still pending. Wait for its result before closing."))
            return None
        return super().dismiss(*args, **kwargs)

    def on_dismiss(self):
        self._active = False
        self._generation += 1
        self._reading = False
        self.hide_keyboard()
        if self._saved_softinput_mode is not None:
            Window.softinput_mode = self._saved_softinput_mode
            self._saved_softinput_mode = None
        self.app.unbind(android_keyboard_height=self._geometry)
        Window.unbind(on_focus=self.window_focus)
        self._geometry.cancel()
        for event in (self._poll, self._countdown):
            event.cancel()
        if self._sheet:
            self._sheet.dismiss()
        self._worker.shutdown(wait=False, cancel_futures=True)
        for widget in self.walk():
            if isinstance(widget, SystemAction):
                widget.cancel_gestures()

    def choose(self, name):
        if self.busy:
            return
        self.hide_keyboard()
        self.section = name
        self.content.clear_widgets()
        self.actions = []
        for key, widget in self.nav.items():
            widget.background_color = theme.SELECTED if key == name else theme.CONTROL
        self.content.add_widget(self.notice)
        if name == "Overview":
            self.content.add_widget(self.info)
            self.add_action(tr._("Refresh details"), self.refresh)
        elif name == "Network":
            self.content.add_widget(
                SystemText(
                    text=tr._(
                        "Enter a WPA-personal network or hidden SSID. Open, enterprise and WPA3-only networks are not supported here."
                    )
                )
            )
            for label, field in ((tr._("Wi-Fi network name"), self.ssid), (tr._("Wi-Fi password"), self.password)):
                if field.parent:
                    field.parent.remove_widget(field)
                group = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
                group.bind(minimum_height=group.setter("height"))
                group.add_widget(SystemText(text=label))
                group.add_widget(field)
                self.content.add_widget(group)
            self.add_action(tr._("Show / hide password"), self.toggle_password)
        else:
            self.content.add_widget(
                SystemText(
                    text=tr._(
                        "Restart closes the controller connection and this screen. The controller starts disconnected."
                    )
                )
            )
            self.restart = self.add_action(tr._("Restart controller"), lambda: self.confirm("restart"))
        self.content.add_widget(self.status)
        self.scroll.scroll_y = 1
        self.render()
        self.update_controls()

    def add_action(self, text, callback):
        widget = self.button(text, callback)
        self.content.add_widget(widget)
        self.actions.append(widget)
        return widget

    def focus_changed(self, field, focused):
        if focused:
            self.active_field = field
        self._geometry()

    def hide_keyboard(self):
        for field in (getattr(self, "ssid", None), getattr(self, "password", None)):
            if field:
                field.focus = False
        self.active_field = None

    def paste_text(self):
        if self.active_field and self.active_field.focus:
            self.active_field.paste()

    def toggle_password(self):
        self.password.password = not self.password.password

    def reflow(self, *_args):
        if not self._active:
            return
        editing = bool(self.active_field and self.active_field.focus)
        keyboards = [child for child in Window.children if isinstance(child, VKeyboard)]
        keyboard = max((child.to_window(0, child.height, initial=False)[1] for child in keyboards), default=0)
        if keyboards and self.app.android_keyboard_height != keyboard:
            self.app.android_keyboard_height = keyboard
        layout = getattr(self.app, "_touch_layout", None)
        state = layout.dialogs.get(self) if layout else None
        if keyboard and state and not state.get("keyboard_adapted"):
            state["keyboard_adapted"] = True
            layout._dialogs_update()
        self.navigation.height = 0 if keyboard else dp(52)
        self.header.height = dp(52)
        self.navigation.opacity = 0 if keyboard else 1
        self.navigation.disabled = bool(keyboard) or self.busy
        self.update_controls()
        signature = (tuple(self.scroll.size), self.active_field if editing else None)
        if signature != self._reveal_signature and editing:
            field = self.active_field
            Clock.schedule_once(lambda _dt: self.reveal(field))
        self._reveal_signature = signature

    def reveal(self, field):
        if not self._active or not field.focus or not field.parent:
            return
        group = field.parent
        top = self.content.to_widget(*group.to_window(group.x, group.top))[1]
        overflow = self.content.height - self.scroll.height
        if overflow > 0:
            self.scroll.scroll_y = max(0, min(1, (top + dp(8) - self.scroll.height) / overflow))
            self.scroll.update_from_scroll()

    def window_focus(self, _window, focused):
        if not focused:
            self.hide_keyboard()
            for widget in self.walk():
                if isinstance(widget, SystemAction):
                    widget.cancel_gestures()

    def raise_above_maintenance(self):
        if not self._is_open or not self.backend.wifi_attempted or self.backend.wifi_kept:
            return
        if self in Window.children:
            Window.remove_widget(self)
            Window.add_widget(self)
        if self._sheet and self._sheet in Window.children:
            Window.remove_widget(self._sheet)
            Window.add_widget(self._sheet)

    def emergency_stop(self):
        self.app.root.controller.estopCommand()

    def update_controls(self):
        if not hasattr(self, "ssid"):
            return
        for widget in (*self.actions, *self.nav.values()):
            widget.disabled = self.busy
        editing = bool(self.active_field and self.active_field.focus)
        visible = {
            self.paste: editing,
            self.hide: editing,
            self.connect: self.section == "Network",
            self.keep: self.backend.wifi_attempted and not self.backend.wifi_kept,
            self.stop: True,
        }
        for widget, shown in visible.items():
            widget.size_hint_x = 1 if shown else None
            if not shown:
                widget.width = 0
            widget.opacity = int(shown)
            widget.disabled = not shown or (self.busy and widget not in (self.hide, self.stop))
            if shown:
                widget.height = max(dp(52), widget.texture_size[1] + dp(16))
        self.footer.height = max(widget.height for widget, shown in visible.items() if shown)
        self.stop.background_color = theme.DANGER
        for widget, action in (
            (self.connect, "wifi"),
            (self.keep, "wifi-confirm"),
            (getattr(self, "restart", None), "restart"),
        ):
            if widget is None:
                continue
            try:
                self.backend.guard(action)
            except ValueError:
                widget.disabled = True
        self.ssid.disabled = self.password.disabled = self.busy
        if self.backend.uncertain:
            self.notice.text = tr._(
                "The previous request has an unknown outcome. Inspect and finish maintenance from the laptop. Closing this screen does not resolve it."
            )
        elif self.backend.wifi_attempted and not self.backend.wifi_kept:
            remaining = self.backend.remaining()
            if remaining:
                self.notice.text = tr._(
                    "Keep the network if it works. Confirmation closes in {seconds} seconds."
                ).format(seconds=remaining)
            else:
                self.notice.text = tr._(
                    "Wi-Fi confirmation has closed. The image should roll back an unconfirmed network. Maintenance may remain active; refresh status and use a deliberate controller restart or finish from the laptop. Closing this screen does not leave maintenance."
                )
        else:
            self.notice.text = tr._(
                "This image supports Wi-Fi and controller restart here. Independent emergency recovery is unchanged. Display, power and system-tool updates need newer installed tools."
            )

    def confirm(self, action):
        if self.busy or self._sheet:
            return
        try:
            self.backend.guard(action)
            if action == "wifi":
                validate_wifi(self.ssid.text, self.password.text)
        except ValueError as error:
            self.show_status(tr._(str(error)))
            return
        self.hide_keyboard()
        wording = {
            "wifi": tr._(
                "Connect to this Wi-Fi network? Keep it before confirmation closes or the image will restore the previous network."
            ),
            "wifi-confirm": tr._(
                "Keep this Wi-Fi network and finish its maintenance session? Confirm that this is the network you want to use."
            ),
            "restart": tr._(
                "Restart the controller? Its connection and this screen will close. It will start disconnected."
            ),
        }[action]
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        scroll = SystemScroll(do_scroll_x=False)
        scroll.add_widget(
            SystemText(
                text=wording
                + "\n\n"
                + tr._("The machine must be idle. This action cannot stop or make a running machine safe.")
            )
        )
        content.add_widget(scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(12))
        sheet = Popup(
            title=tr._("Confirm system change"),
            content=content,
            size_hint=(0.85, None),
            height=min(Window.height - dp(48), dp(340)),
            auto_dismiss=False,
        )
        actions.add_widget(self.button(tr._("Cancel"), sheet.dismiss))

        def proceed():
            sheet.dismiss()
            self.perform(action)

        actions.add_widget(self.button(tr._("Machine is idle — continue"), proceed))
        content.add_widget(actions)
        self._sheet = sheet
        sheet.bind(on_dismiss=lambda *_args: setattr(self, "_sheet", None))
        sheet.open()

    def perform(self, action):
        if self.busy or not self._active:
            return
        try:
            self.backend.guard(action)
        except ValueError as error:
            self.show_status(tr._(str(error)))
            return
        ssid, password = self.ssid.text, self.password.text
        self._generation += 1
        self._reading = False
        self.busy = True
        self.show_status(tr._("Applying the System action…"))
        self.update_controls()
        generation = self._generation
        future = self._worker.submit(self.backend.perform, action, confirmed_idle=True, ssid=ssid, password=password)
        self._action_future = future

        def completed(future):
            try:
                future.result()
                error = None
            except Exception as failure:
                error = str(failure)

            def apply(_dt):
                if self._action_future is future:
                    self.busy = False
                if not self._active or generation != self._generation:
                    return
                if error:
                    self.show_status(tr._(error))
                elif action == "restart":
                    self.show_status(tr._("Restart requested. Startup and completion have not been verified."))
                    self.dismiss()
                    return
                else:
                    self.show_status(tr._("Wi-Fi request completed. Check the network before continuing."))
                    self.password.text = ""
                self.update_controls()
                self.refresh()

            Clock.schedule_once(apply)

        future.add_done_callback(completed)

    def show_status(self, text):
        self.status.text = text
        self.scroll.scroll_y = 0

    def refresh(self):
        if not self._active or self.busy or self._reading:
            return
        self._reading = True
        generation = self._generation
        future = self._worker.submit(self.backend.overview)

        def completed(future):
            try:
                value, error = future.result(), None
            except Exception as failure:
                value, error = None, str(failure)

            def apply(_dt):
                if not self._active or generation != self._generation:
                    return
                self._reading = False
                if value is not None:
                    self.details = value
                    self.render()
                elif not self.busy:
                    self.show_status(tr._(error))
                self.update_controls()

            Clock.schedule_once(apply)

        future.add_done_callback(completed)

    def render(self):
        value = self.details
        controller = value.get("controller", {})
        fresh = bool(controller) and 0 <= time.monotonic() - controller.get("updated", 0) <= 3
        state = controller.get("state") if fresh else tr._("Unavailable or stale")
        self.info.text = tr._(
            "Application: {application}\nImage: {image}\nController: {state}\nMaintenance: {maintenance}\nTemperature: {temperature}\nStorage free / total: {storage}\n\nNetwork addresses: {addresses}\nLaptop login: {login}\nSSH identity: {identity}"
        ).format(
            state=state,
            maintenance=tr._("Active")
            if fresh and controller.get("maintenance")
            else tr._("Inactive")
            if fresh
            else tr._("Unknown"),
            **{
                key: value.get(key) or tr._("Unavailable")
                for key in ("application", "image", "temperature", "storage", "addresses", "login", "identity")
            },
        )
