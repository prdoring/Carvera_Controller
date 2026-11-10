"""Independent touchscreen system settings and controller recovery."""

import configparser
import json
import math
import os
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kiosk_touch import install as install_touch
from kiosk_touch import uninstall as uninstall_touch
from runtime_profile import configure, prepare
from admin_accounts import read_json, write_json

PRESENTATION = Path(__file__).resolve().parent.parent / "system-ui"
sys.path.insert(0, str(PRESENTATION if PRESENTATION.exists() else Path(__file__).resolve().parents[4]))
os.environ["KIVY_HOME"] = str(Path(os.environ.get("CARVERA_DATA_DIR", "/var/lib/carvera")) / "recovery")
prepare()
from kivy.config import Config

configure(Config)
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.metrics import Metrics, dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.popup import Popup
from system_ui import KeyboardLayout, Panel, Paragraph, SystemInput, SystemScrollView, button, install_style, paste_into

from carveracontroller.translation import LANGS, init, tr
from carveracontroller.ui import theme


def N_(text):
    return text


SECTIONS = (N_("Overview"), N_("Network"), N_("Display"), N_("Maintenance"), N_("Power"))
CONSEQUENCES = {
    "wifi": N_("Connect to this Wi-Fi network? Confirm it within 120 seconds or the previous network will return."),
    "display": N_("Preview this display mode? Keep it within 20 seconds or the previous mode will return."),
    "restart": N_("Restart the controller? Its current connection will close. It will start disconnected."),
    "reboot": N_("Restart the Raspberry Pi? The controller and network access will be interrupted."),
    "shutdown": N_(
        "Shut down the Raspberry Pi? Wait for the display to turn off and disk activity to stop before removing power."
    ),
    "update": N_(
        "Install this application bundle? The controller will restart. Failed startup restores the previous application and preferences."
    ),
    "rollback": N_(
        "Restore the previous application and its saved preferences? Current preferences will be backed up. The controller will restart disconnected."
    ),
    "restore": N_(
        "Restore these preferences? Current preferences will be backed up. The controller will restart disconnected."
    ),
}
PROGRESS = {
    "scan": N_("Finding Wi-Fi networks…"),
    "wifi": N_("Connecting to Wi-Fi…"),
    "display": N_("Applying display preview…"),
    "restart": N_("Restarting the controller and checking startup…"),
    "update": N_("Installing the application and checking startup…"),
    "rollback": N_("Restoring the previous application and checking startup…"),
    "restore": N_("Restoring preferences and checking startup…"),
    "backup": N_("Backing up preferences…"),
    "diagnose": N_("Exporting diagnostics…"),
    "logs": N_("Exporting logs…"),
}


def call_helper(request):
    result = subprocess.run(
        ["sudo", "-n", "/usr/local/sbin/carvera-recover"],
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
        timeout=900,
    )
    try:
        reply = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(
            "System helper did not return a result. Check that the matching kiosk image is installed."
        ) from error
    if result.returncode or not reply.get("ok"):
        raise RuntimeError(reply.get("error") or "The system operation failed. Refresh details before retrying.")
    return reply["result"]


class Recovery(App):
    def run(self):
        # A service stop must bypass the interactive Return to controller flow.
        signal.signal(signal.SIGTERM, self.stop_service)
        super().run()

    def stop_service(self, _signal, _frame):
        Clock.schedule_once(lambda _dt: self.stop())

    def build(self):
        self.title = "Carvera System"
        preferences = configparser.ConfigParser(interpolation=None)
        data = Path(os.environ.get("CARVERA_DATA_DIR", "/var/lib/carvera"))
        try:
            preferences.read(data / ".kivy/config.ini")
        except (OSError, configparser.Error):
            preferences = configparser.ConfigParser(interpolation=None)
        try:
            scale = preferences.getfloat("carvera", "android_ui_scale", fallback=1)
            if not math.isfinite(scale) or scale <= 0:
                scale = 1
        except ValueError:
            scale = 1
        Metrics.density = float(os.environ.get("CARVERA_ANDROID_DENSITY", "1.5")) * scale
        language = preferences.get("carvera", "language", fallback="en")
        init(language if language in LANGS else "en")
        install_style()
        self.touch = install_touch(Window)
        Window.softinput_mode = ""
        self.worker = ThreadPoolExecutor(max_workers=2, thread_name_prefix="kiosk-system")
        self.active_field = None
        self.network_draft = {"ssid": "", "password": ""}
        self.busy = False
        self.closed = False
        self.status_pending = False
        self.status_generation = 0
        self.details = {}
        self.ready_at = 0
        Window.bind(on_flip=self.ready_frame)
        self.section = "Overview"
        self.controls = []
        self.sheet = None
        self.result_text = ""
        self.last_operation = None
        self.last_error = None
        self.error_sheet = None
        self.poll = None
        root = FloatLayout()
        with root.canvas.before:
            Color(*theme.BACKGROUND)
            background = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda widget, value: setattr(background, "pos", value),
            size=lambda widget, value: setattr(background, "size", value),
        )
        self.shell = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        root.add_widget(self.shell)
        header = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(12))
        header.add_widget(Paragraph(text=tr._("System"), font_size=sp(24), bold=True))
        self.return_button = button(tr._("Return to controller"), self.close)
        self.return_button.size_hint_x = None
        self.return_button.width = dp(240)
        header.add_widget(self.return_button)
        self.shell.add_widget(header)
        body = BoxLayout(spacing=dp(16))
        self.shell.add_widget(body)
        navigation = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        navigation.bind(minimum_height=navigation.setter("height"))
        self.nav = {}
        for name in SECTIONS:
            widget = button(name, lambda name=name: self.choose(name))
            navigation.add_widget(widget)
            self.nav[name] = widget
        navigation_scroll = SystemScrollView(do_scroll_x=False, size_hint_x=None, width=dp(180))
        navigation_scroll.add_widget(navigation)
        body.add_widget(navigation_scroll)
        self.scroll = SystemScrollView(do_scroll_x=False, bar_width=dp(8), scroll_type=["content", "bars"])
        self.content = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None)
        self.content.bind(minimum_height=self.content.setter("height"))
        self.scroll.add_widget(self.content)
        body.add_widget(self.scroll)
        self.trial_actions = BoxLayout(size_hint_y=None, height=0, spacing=dp(12), opacity=0, disabled=True)
        self.trial_label = Paragraph(color=theme.ACCENT)
        self.trial_actions.add_widget(self.trial_label)
        self.trial_keep = button(
            tr._("Keep change"), lambda: self.request(self.trial_kind + "-confirm", confirmed_idle=True)
        )
        self.trial_revert = button(
            tr._("Revert now"), lambda: self.request(self.trial_kind + "-revert", confirmed_idle=True)
        )
        for widget in (self.trial_keep, self.trial_revert):
            widget.size_hint_x = None
            widget.width = dp(180)
            self.trial_actions.add_widget(widget)
        self.shell.add_widget(self.trial_actions)
        footer = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(12))
        self.status_label = Paragraph(
            text=tr._("Reading system details…"), color=theme.SECONDARY, shorten=True, max_lines=2
        )
        footer.add_widget(self.status_label)
        self.keyboard_actions = BoxLayout(size_hint_x=None, width=0, spacing=dp(8))
        self.keyboard_actions.add_widget(button(tr._("Paste"), lambda: paste_into(self.active_field)))
        self.keyboard_actions.add_widget(button(tr._("Hide keyboard"), self.dismiss_keyboard))
        self.keyboard_connect = button(tr._("Connect Wi-Fi"), self.connect_wifi)
        self.keyboard_connect.size_hint_x = None
        self.keyboard_actions.add_widget(self.keyboard_connect)
        footer.add_widget(self.keyboard_actions)
        self.shell.add_widget(footer)
        self.keyboard_layout = KeyboardLayout(self, self.shell)
        Window.bind(on_request_close=self.request_close)
        self.choose("Overview")
        self.refresh()
        self.poll = Clock.schedule_interval(lambda _dt: self.refresh(), 3)
        self.countdown = Clock.schedule_interval(lambda _dt: self.update_controls(), 0.5)
        return root

    def focus_field(self, field):
        self.active_field = field
        self.keyboard_layout.event()

    def dismiss_keyboard(self):
        for field in self.shell.walk():
            if isinstance(field, SystemInput):
                field.focus = False
        self.active_field = None
        Window.release_all_keyboards()

    def panel(self, title, description=""):
        surface = Panel()
        surface.add_widget(Paragraph(text=tr._(title), bold=True, font_size=sp(18)))
        if description:
            surface.add_widget(Paragraph(text=tr._(description), color=theme.SECONDARY))
        self.content.add_widget(surface)
        return surface

    def action(self, parent, text, callback, danger=False):
        widget = button(text, callback, danger)
        parent.add_widget(widget)
        self.controls.append(widget)
        return widget

    def field(self, parent, label, **kwargs):
        group = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        group.bind(minimum_height=group.setter("height"))
        group.add_widget(Paragraph(text=label))
        field = SystemInput(**kwargs)
        field.focus_region = group
        group.add_widget(field)
        parent.add_widget(group)
        return field

    def choose(self, name):
        self.dismiss_keyboard()
        self.section = name
        self.controls = []
        self.content.clear_widgets()
        self.scroll.scroll_y = 1
        for title, widget in self.nav.items():
            widget.background_color = theme.SELECTED if title == name else theme.CONTROL
        getattr(self, "build_" + name.lower())()
        self.update_controls()
        if name == "Display" and self.details.get("operation", {}).get("phase") not in {"queued", "running"}:
            self.request("display-modes", callback=self.show_modes)

    def build_overview(self):
        panel = self.panel(tr._("Kiosk status"))
        self.overview = Paragraph()
        panel.add_widget(self.overview)
        self.action(panel, tr._("Refresh details"), self.refresh)
        connection = self.panel(
            tr._("Laptop access"), tr._("Compare the SSH identity on your laptop before trusting a new connection.")
        )
        self.access = Paragraph()
        connection.add_widget(self.access)
        self.render_status()

    def build_network(self):
        panel = self.panel(
            tr._("Network"),
            tr._(
                "Select a WPA-personal network, or enter a hidden network name below. Open, enterprise and WPA3-only networks are not supported here."
            ),
        )
        self.network_info = Paragraph()
        panel.add_widget(self.network_info)
        self.action(panel, tr._("Find Wi-Fi networks"), lambda: self.request("scan", callback=self.show_networks))
        self.networks = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=0)
        self.networks.bind(minimum_height=self.networks.setter("height"))
        panel.add_widget(self.networks)
        self.ssid = self.field(
            panel, tr._("Wi-Fi network name"), hint_text=tr._("Network name (SSID)"), text=self.network_draft["ssid"]
        )
        self.ssid.bind(text=lambda _widget, text: self.network_draft.update(ssid=text))
        self.password = self.field(
            panel,
            tr._("Wi-Fi password"),
            password=True,
            hint_text=tr._("8–63 bytes"),
            text=self.network_draft["password"],
        )
        self.password.bind(text=lambda _widget, text: self.network_draft.update(password=text))
        self.action(panel, tr._("Show / hide password"), self.toggle_password)
        self.action(panel, tr._("Connect Wi-Fi"), self.connect_wifi)
        self.render_status()

    def toggle_password(self):
        self.password.password = not self.password.password

    def connect_wifi(self):
        ssid, password = self.ssid.text, self.password.text
        if (
            not 1 <= len(ssid.encode("utf-8")) <= 32
            or not 8 <= len(password.encode("utf-8")) <= 63
            or any(char in ssid + password for char in "\r\n\0")
        ):
            self.show_error(tr._("Use a network name of 1–32 bytes and a password of 8–63 bytes."))
            return
        self.confirm("wifi", wifi={"ssid": ssid, "password": password})

    def show_networks(self, value):
        self.networks.clear_widgets()
        networks = value.get("networks", [])
        if not networks:
            self.networks.add_widget(
                Paragraph(text=tr._("No Wi-Fi networks found. Try again or enter a hidden network."))
            )
        for network in networks:
            widget = button(
                "{ssid} · {signal}% · {security}".format(**network),
                lambda ssid=network["ssid"]: setattr(self.ssid, "text", ssid),
            )
            widget._system_available = network["supported"]
            widget.disabled = not network["supported"]
            self.networks.add_widget(widget)
            self.controls.append(widget)

    def build_display(self):
        panel = self.panel(
            tr._("Display"),
            tr._(
                "Only modes advertised by the connected screen near 60 Hz can be applied. A preview reverts after 20 seconds unless kept."
            ),
        )
        self.display_info = Paragraph()
        panel.add_widget(self.display_info)
        self.mode_buttons = {}
        for mode in ("1920x1200", "1920x1080"):
            widget = self.action(panel, mode, lambda mode=mode: self.confirm("display", value=mode))
            widget._system_available = False
            self.mode_buttons[mode] = widget
        self.display_modes = Paragraph(text=tr._("Checking the connected display…"), color=theme.SECONDARY)
        panel.add_widget(self.display_modes)
        self.render_status()

    def show_modes(self, value):
        modes = value.get("modes", [])
        for mode, widget in self.mode_buttons.items():
            widget._system_available = mode in modes
        self.display_modes.text = (
            tr._("Available modes: {modes}").format(modes=", ".join(modes))
            if modes
            else tr._("No supported display modes were reported. Check the display connection.")
        )

    def build_maintenance(self):
        panel = self.panel(
            tr._("Diagnostics and preferences"),
            tr._("Files are saved for laptop retrieval. Preferences backups exclude G-code and application files."),
        )
        for text, action in (
            (N_("Export diagnostics"), "diagnose"),
            (N_("Export logs"), "logs"),
            (N_("Back up preferences"), "backup"),
        ):
            self.action(panel, text, lambda action=action: self.request(action))
        self.action(panel, tr._("View technical details"), self.technical_details)
        panel = self.panel(
            tr._("Application and preferences"),
            tr._(
                "Use the laptop helper to stage application bundles or preferences. Application bundles update the controller. System tools use a separate administrator update; OS updates require a replacement image."
            ),
        )
        self.action(panel, tr._("Refresh staged files"), lambda: self.request("files", callback=self.show_files))
        self.staged = BoxLayout(orientation="vertical", spacing=dp(12), size_hint_y=None, height=0)
        self.staged.bind(minimum_height=self.staged.setter("height"))
        panel.add_widget(self.staged)
        self.rollback_button = self.action(
            panel, tr._("Restore previous application"), lambda: self.confirm("rollback"), danger=True
        )
        self.render_status()

    def show_files(self, value):
        self.staged.clear_widgets()
        if value.get("limited"):
            self.staged.add_widget(Paragraph(text=tr._("Showing the 20 most recently staged files.")))
        if not value.get("files"):
            self.staged.add_widget(
                Paragraph(
                    text=tr._(
                        "No staged files. Use the laptop helper to stage an application bundle or preferences backup."
                    )
                )
            )
        for item in value.get("files", []):
            surface = Panel()
            detail = "{name}\n{bytes:,} bytes".format(**item)
            if item["kind"] == "application":
                detail += "\n" + tr._("Application") + ": " + str(item.get("version"))
                detail += " · " + str(item.get("architecture")) + " · Python " + str(item.get("python"))
            surface.add_widget(Paragraph(text=detail))
            action = "update" if item["kind"] == "application" else "restore"
            widget = button(
                tr._("Review application") if action == "update" else tr._("Review preferences"),
                lambda item=item: self.request("inspect", value=item["name"], callback=self.review_file),
            )
            if action == "update":
                widget._system_available = item.get("architecture") == "aarch64" and item.get("python") == "3.13"
                widget.disabled = not widget._system_available
            surface.add_widget(widget)
            self.controls.append(widget)
            self.staged.add_widget(surface)

    def review_file(self, item):
        detail = "{name}\n{bytes:,} bytes\nSHA256: {sha256}".format(**item)
        if item["kind"] == "application":
            detail += "\n" + tr._("Application: {version}").format(version=item.get("version", "—"))
        self.confirm(
            "update" if item["kind"] == "application" else "restore",
            value={"name": item["name"], "sha256": item["sha256"]},
            detail=detail,
        )

    def build_power(self):
        panel = self.panel(
            tr._("Controller"),
            tr._("Restarting closes the machine connection. Reconnection is always a separate deliberate action."),
        )
        self.action(panel, tr._("Restart controller"), lambda: self.confirm("restart"))
        panel = self.panel(
            tr._("Raspberry Pi"), tr._("Confirm that the machine is idle and safe to leave without controller access.")
        )
        self.action(panel, tr._("Restart Pi"), lambda: self.confirm("reboot"), danger=True)
        self.action(panel, tr._("Shut down Pi"), lambda: self.confirm("shutdown"), danger=True)

    def technical_details(self):
        self.dismiss_keyboard()
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        scroll = SystemScrollView(do_scroll_x=False)
        scroll.add_widget(Paragraph(text=json.dumps(self.details, indent=2, ensure_ascii=False)))
        content.add_widget(scroll)
        sheet = Popup(title=tr._("Technical details"), content=content, size_hint=(0.88, 0.88))
        content.add_widget(button(tr._("Close"), sheet.dismiss))
        sheet.open()

    def confirm(self, action, detail="", **payload):
        if self.busy or self.sheet is not None:
            return
        self.dismiss_keyboard()
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(16))
        scroll = SystemScrollView(do_scroll_x=False)
        wording = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(16))
        wording.bind(minimum_height=wording.setter("height"))
        wording.add_widget(Paragraph(text=tr._(CONSEQUENCES[action]) + ("\n\n" + detail if detail else "")))
        wording.add_widget(
            Paragraph(
                text=tr._("The machine must be idle. This action cannot stop or make a running machine safe."),
                color=theme.SECONDARY,
            )
        )
        scroll.add_widget(wording)
        content.add_widget(scroll)
        actions = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(12))
        sheet = Popup(
            title=tr._("Confirm system change"),
            content=content,
            size_hint=(0.82, None),
            height=dp(320),
            auto_dismiss=False,
        )
        wording.bind(
            minimum_height=lambda *_args: setattr(
                sheet, "height", min(Window.height - dp(48), max(dp(280), wording.minimum_height + dp(156)))
            )
        )
        actions.add_widget(button(tr._("Cancel"), sheet.dismiss))

        def proceed():
            sheet.dismiss()
            if action == "wifi":
                self.password.text = ""
            self.request(action, confirmed_idle=True, **payload)

        actions.add_widget(
            button(
                tr._("Machine is idle — continue"),
                proceed,
                danger=action in {"shutdown", "reboot", "restore", "rollback"},
            )
        )
        content.add_widget(actions)
        self.sheet = sheet
        sheet.bind(on_dismiss=lambda *_args: setattr(self, "sheet", None))
        sheet.open()

    def refresh(self, *_args):
        if self.closed or self.status_pending:
            return
        self.status_pending = True
        generation = self.status_generation
        future = self.worker.submit(call_helper, {"action": "status", "id": uuid.uuid4().hex})

        def complete(future):
            try:
                value, error = future.result(), None
            except Exception as failure:
                value, error = None, str(failure)

            def apply(_dt):
                self.status_pending = False
                if self.closed:
                    return
                if generation != self.status_generation:
                    self.refresh()
                    return
                if error:
                    if not self.busy:
                        self.show_error(error)
                    return
                self.details = value
                operation = value.get("operation", {})
                if not self.busy and operation.get("id") != self.last_operation:
                    self.last_operation = operation.get("id")
                    if operation.get("phase") in {"failed", "interrupted"}:
                        self.show_error(operation.get("message", tr._("The previous operation did not finish.")))
                    elif operation.get("phase") == "complete":
                        self.status_label.text = self.result_message(
                            operation.get("action"), operation.get("result", {})
                        )
                        self.status_label.color = theme.SUCCESS
                self.render_status()
                self.update_controls()

            Clock.schedule_once(apply)

        future.add_done_callback(complete)

    def request(self, action, callback=None, **payload):
        if self.busy or self.closed:
            return
        self.dismiss_keyboard()
        self.busy = True
        self.status_generation += 1
        self.last_error = None
        self.status_label.text = tr._(PROGRESS.get(action, "Working…"))
        self.status_label.color = theme.ACCENT
        self.update_controls()
        request = {"action": action, "id": uuid.uuid4().hex, **payload}
        future = self.worker.submit(call_helper, request)

        def complete(future):
            try:
                value, error = future.result(), None
            except Exception as failure:
                value, error = None, str(failure)

            def apply(_dt):
                if self.closed:
                    return
                self.busy = False
                self.status_generation += 1
                self.last_operation = request["id"]
                if error:
                    self.show_error(error)
                else:
                    self.result_text = self.result_message(action, value)
                    self.status_label.text = self.result_text
                    self.status_label.color = theme.SUCCESS
                    if callback:
                        callback(value)
                if self.closed:
                    return
                self.update_controls()
                self.refresh()

            Clock.schedule_once(apply)

        future.add_done_callback(complete)

    def result_message(self, action, value):
        if "file" in value:
            return tr._("Saved for laptop retrieval: {file}").format(file=value["file"])
        if action in {"reboot", "shutdown"}:
            return tr._("Power operation requested. Wait for the Pi to finish.")
        if action in {"update", "rollback"} and "current" in value:
            return tr._("Application {version} is ready. The controller is disconnected.").format(
                version=Path(value["current"]).name
            )
        if action == "restore":
            return tr._("Preferences restored. Previous preferences saved as {file}.").format(
                file=value.get("backup", "—")
            )
        if action == "restart":
            return tr._("Controller restarted and ready. Reconnect the mill when you are ready.")
        if action in {"wifi", "display"}:
            return tr._("Keep or revert the change using the confirmation bar.")
        return tr._("Completed.")

    def show_error(self, message):
        self.status_label.text = tr._(message)
        self.status_label.color = theme.ERROR
        if message != self.last_error and self.error_sheet is None:
            self.last_error = message
            content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
            scroll = SystemScrollView(do_scroll_x=False)
            wording = Paragraph(text=tr._(message))
            scroll.add_widget(wording)
            content.add_widget(scroll)
            sheet = Popup(
                title=tr._("System operation could not finish"), content=content, size_hint=(0.8, None), height=dp(260)
            )
            wording.bind(
                height=lambda *_args: setattr(
                    sheet, "height", min(Window.height * 0.8, max(dp(220), wording.height + dp(148)))
                )
            )
            content.add_widget(button(tr._("Close"), sheet.dismiss))
            self.error_sheet = sheet
            sheet.bind(on_dismiss=lambda *_args: setattr(self, "error_sheet", None))
            sheet.open()

    def update_controls(self):
        for key in ("network", "display"):
            trial = self.details.get(key, {})
            if "expires" in trial:
                trial["remaining"] = max(0, math.ceil(trial["expires"] - time.monotonic()))
        running = self.details.get("operation", {}).get("phase") in {"queued", "running"}
        blocked = self.busy or running
        trial_pending = bool(self.details.get("network", {}).get("remaining", 0) or self.details.get("display"))
        for widget in self.controls:
            widget.disabled = blocked or trial_pending or not getattr(widget, "_system_available", True)
        for widget in self.nav.values():
            widget.disabled = self.busy
        self.return_button.disabled = blocked
        network = self.details.get("network", {})
        display = self.details.get("display", {})
        visible = bool(network.get("remaining", 0) or display)
        self.trial_kind = "wifi" if network.get("remaining", 0) else "display"
        trial = network if self.trial_kind == "wifi" else display
        self.trial_actions.height = dp(56) if visible else 0
        self.trial_actions.opacity = int(visible)
        self.trial_actions.disabled = blocked or not visible
        self.trial_keep.disabled = blocked or not trial.get("remaining", 0)
        self.trial_label.text = tr._("Keep or revert the change: {seconds} seconds remaining.").format(
            seconds=trial.get("remaining", 0)
        )
        if self.section == "Maintenance":
            self.rollback_button.disabled = blocked or not self.details.get("previous_version")
        if running and not self.busy:
            self.status_label.text = tr._(
                PROGRESS.get(
                    self.details.get("operation", {}).get("action"),
                    "A system operation is in progress. Waiting for its result…",
                )
            )

    def render_status(self):
        value = self.details
        controller = value.get("controller", {})
        if self.section == "Overview":
            state = controller.get("state", tr._("Unavailable"))
            self.overview.text = tr._(
                "Application: {app}\nImage: {image}\nController: {state}\nTemperature: {temperature}\nMemory: {memory}\nStorage: {storage}"
            ).format(
                app=value.get("version") or tr._("Unknown"),
                image=value.get("image_version") or tr._("Unknown"),
                state=state,
                temperature=value.get("temperature", "—"),
                memory=value.get("memory", "—"),
                storage=value.get("storage", "—"),
            )
            self.access.text = tr._(
                "Network addresses: {addresses}\nLaptop login: {login}\nSSH identity: {identity}"
            ).format(
                addresses=value.get("addresses") or tr._("Not connected"),
                login=value.get("login", "—"),
                identity=value.get("identity", "—"),
            )
        if self.section == "Network":
            lines = [
                tr._("Wi-Fi") + ": " + entry["connection"] + " — " + tr._(entry["state"])
                if entry["type"] == "wifi"
                else tr._("Ethernet") + ": " + tr._(entry["state"])
                for entry in value.get("interfaces", [])
            ]
            lines.append(value.get("addresses") or tr._("Not connected"))
            self.network_info.text = "\n".join(lines)
        if self.section == "Display":
            remaining = value.get("display", {}).get("remaining", 0)
            self.display_info.text = tr._("Saved mode: {mode}").format(mode=value.get("display_mode", "—"))
            if remaining:
                self.display_info.text += "\n" + tr._("Preview: {seconds} seconds remaining.").format(seconds=remaining)

    def close(self):
        self.dismiss_keyboard()
        if self.busy:
            return
        self.request("leave", callback=self.return_after_maintenance)

    def return_after_maintenance(self, value):
        if value.get("controller_available"):
            self.stop()
        else:
            self.show_error(tr._("The controller is unavailable. Use Power → Restart controller to recover it."))

    def request_close(self, *_args, **_kwargs):
        self.close()
        return True

    def ready_frame(self, *_args):
        if self.details and time.monotonic() - self.ready_at >= 1:
            manifest = read_json(PRESENTATION.parent / "system-bundle.json")
            if manifest.get("version"):
                write_json(Path(os.environ.get("CARVERA_RUNTIME_DIR", "/run/carvera")) / "system-ready.json",
                           {"pid": os.getpid(), "system_version": manifest["version"], "updated": time.monotonic()})
                self.ready_at = time.monotonic()

    def on_stop(self):
        self.closed = True
        Window.unbind(on_flip=self.ready_frame)
        ready = Path(os.environ.get("CARVERA_RUNTIME_DIR", "/run/carvera")) / "system-ready.json"
        if read_json(ready).get("pid") == os.getpid():
            ready.unlink(missing_ok=True)
        Window.unbind(on_request_close=self.request_close)
        if self.poll:
            self.poll.cancel()
        self.countdown.cancel()
        self.keyboard_layout.close()
        uninstall_touch(Window, self.touch)
        self.dismiss_keyboard()
        self.worker.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    import fcntl

    directory = Path(os.environ.get("CARVERA_DATA_DIR", "/var/lib/carvera")) / "recovery"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "system.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit(0)
        Recovery().run()
