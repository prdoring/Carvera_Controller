"""Isolated UI development with recorded commands and no physical transports."""

import json
import os
import socket
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


class Simulation:
    def __init__(self):
        self.commands = []
        self.attempts = []
        self._patches = ExitStack()

    def blocked(self, *args, **kwargs):
        self.attempts.append((args, kwargs))
        raise RuntimeError("Physical connections are disabled in the UI simulator")

    def install(self):
        import serial

        from carveracontroller import main
        from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
        from carveracontroller.Controller import Controller
        from carveracontroller.USBStream import USBStream
        from carveracontroller.WIFIStream import MachineDetector, WIFIStream

        for owner, name in ((Controller, "open"), (USBStream, "open"), (USBStream, "_serial_for_address"),
                            (WIFIStream, "open"), (MachineDetector, "query_for_machines"),
                            (MachineDetector, "is_machine_busy"), (serial, "Serial")):
            self._patches.enter_context(patch.object(owner, name, self.blocked))
        self._patches.enter_context(patch.object(main.Makera, "setup_pendant", lambda root: None))
        self._patches.enter_context(patch.object(main.Makera, "attempt_reconnect", self.blocked))
        self._patches.enter_context(patch.object(main, "UrlRequest", self.blocked))
        self._patches.enter_context(patch.object(main.Utils, "comports", lambda *a, **k: []))
        self._patches.enter_context(patch.object(main.Utils, "list_identifiable_usb_serial_ports", lambda *a, **k: []))
        self._patches.enter_context(patch.object(ConfigUtils, "CONFIG_DIR", os.environ["KIVY_HOME"]))
        self._patches.enter_context(patch.object(socket, "create_connection", self.blocked))
        self._patches.enter_context(patch.object(socket.socket, "connect", self.blocked))
        self._patches.enter_context(patch.object(socket.socket, "sendto", self.blocked))
        self._patches.enter_context(patch.object(Controller, "executeCommand", self.record))
        self._patches.enter_context(patch.object(Controller, "executeFileCommand", self.record))
        self._patches.enter_context(patch.object(Controller, "executeRealtimeSequence", self.record))
        return self

    def record(self, *commands):
        self.commands.extend(commands)
        return True

    def configure(self):
        from kivy.config import Config

        for key, value in {"show_update": "0", "address": "", "pendant_type": "None",
                           "last_connection_method": "", "auto_reconnect_enabled": "0"}.items():
            Config.set("carvera", key, value)

    def attach(self, app):
        """File-based inspection is available only in an explicit simulator run."""
        if os.environ.get("CARVERA_SIMULATION") != "1":
            return
        from kivy.clock import Clock

        self.app = app
        self._request = Path(app.user_data_dir) / "ui-test-request.json"
        self._response = Path(app.user_data_dir) / "ui-test-response.json"
        self._scenes = {}
        self._last_request = None
        self._poll_event = Clock.schedule_interval(self._poll, .15)

    def _poll(self, _dt):
        from kivy.clock import Clock

        try:
            request = json.loads(self._request.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if request.get("id") == self._last_request:
            return
        self._last_request = request.get("id")
        started = time.perf_counter()
        try:
            self._action(request)
            Clock.schedule_once(lambda _dt: self._report(request, started), .25)
        except Exception as error:
            self._response.write_text(json.dumps({"id": request.get("id"), "error": str(error)}), encoding="utf-8")

    def _action(self, request):
        from kivy.core.window import Window
        from kivy.metrics import Metrics
        from kivy.uix.modalview import ModalView
        from kivy.uix.textinput import TextInput

        root = self.app.root
        op = request.get("op", "inspect")
        if op == "show":
            for modal in list(Window.children):
                if isinstance(modal, ModalView):
                    modal.dismiss(force=True, animation=False)
            name = request["scene"]
            if name in ("control", "preview", "console"):
                root.content.current = "Control" if name == "control" else "File"
                self.app.show_lines = name == "console"
                self.app.show_preview = name != "console"
                if name == "console":
                    root.cmd_manager.current = "manual_cmd_page"
                return
            if name == "picker":
                from .ui.LocalFilePicker import open_local_file_picker

                open_local_file_picker(title="Simulator save destination", default_name="retained-draft.json",
                                       on_confirm=lambda *_args: None)
                return
            mapping = {"input": root.input_popup, "unlock": root.unlock_popup, "job": root.coord_popup,
                       "files": root.file_popup, "settings": root.config_popup, "wcs": root.wcs_settings_popup,
                       "diagnostics": root.diagnose_popup, "updates": root.upgrade_popup}
            if name not in mapping and name not in self._scenes:
                if name == "probing":
                    from .addons.probing.ProbingPopup import ProbingPopup

                    self._scenes[name] = ProbingPopup(root.controller)
                elif name == "cmm":
                    self._scenes[name] = root._ensure_cmm_workbench_popup()
                elif name == "facing":
                    from .addons.facing.FacingWizardPopup import FacingWizardPopup

                    self._scenes[name] = FacingWizardPopup()
                else:
                    raise ValueError("Unknown simulator scene")
            modal = mapping.get(name) or self._scenes[name]
            if name == "input":
                modal.lb_title.text = "Simulator keyboard test"
                modal.confirm = lambda: True
            if name == "job":
                modal.cnc_workspace.load_config(root.coord_config)
            modal.open(animation=False)
        elif op == "field":
            widgets = {name: widget for surface in [root] + list(Window.children)
                       for name, widget in surface.ids.items() if isinstance(widget, TextInput)}
            field = widgets[request["field"]]
            if "text" in request:
                field.text = str(request["text"])
            if "policy" in request:
                field.input_policy = request["policy"]
            field.focus = bool(request.get("focus", True))
            if request.get("cursor_end"):
                field.cancel_selection()
                field.cursor = field.get_cursor_from_index(len(field.text))
        elif op == "scale":
            density = float(os.environ.get("CARVERA_ANDROID_DENSITY", "1"))
            Metrics.density = density * float(request["scale"])
            self.app.touch_target = max(48 * density, 48 * Metrics.density)
            self.app._touch_layout.size_controls(root)
            self.app._touch_layout.update()
        elif op == "dismiss_keyboard":
            Window.release_all_keyboards()
        elif op != "inspect":
            raise ValueError("Unknown simulator inspection operation")

    def _report(self, request, started):
        from kivy.core.window import Window
        from kivy.metrics import Metrics
        from kivy.uix.modalview import ModalView
        from kivy.uix.textinput import TextInput

        widgets = {}
        surfaces = [self.app.root] + [w for w in Window.children if isinstance(w, ModalView)]
        for surface in surfaces:
            for name, widget in surface.ids.items():
                x, y = widget.to_window(*widget.pos)
                widgets[name] = {"bounds": [x, y, widget.width, widget.height],
                                 "text": str(getattr(widget, "text", "")), "disabled": widget.disabled,
                                 "focus": isinstance(widget, TextInput) and widget.focus}
        modals = [{"type": type(modal).__name__, "bounds": list(modal.pos) + list(modal.size)}
                  for modal in Window.children if isinstance(modal, ModalView)]
        report = {"id": request.get("id"), "window": list(Window.size), "density": Metrics.density,
                  "fontscale": Metrics.fontscale, "keyboard_height": self.app.android_keyboard_height,
                  "user_data_dir": self.app.user_data_dir, "widgets": widgets,
                  "modals": modals,
                  "commands": [str(command) for command in self.commands], "blocked_attempts": len(self.attempts),
                  "settle_ms": (time.perf_counter() - started) * 1000}
        self._response.write_text(json.dumps(report), encoding="utf-8")

    def close(self):
        from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils

        if getattr(self, "_poll_event", None) is not None:
            self._poll_event.cancel()
        ConfigUtils.flush_saves()
        ConfigUtils._writer.submit(lambda: None).result(timeout=5)
        self._patches.close()
