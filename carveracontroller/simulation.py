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
            quiet = [None, 0]
            def settled(_dt):
                from kivy.core.window import Window
                from kivy.uix.modalview import ModalView

                transitions = (self.app.root.content.transition, self.app.root.cmd_manager.transition)
                surfaces = [self.app.root] + [widget for widget in Window.children if isinstance(widget, ModalView)]
                geometry = tuple((widget.uid, *(round(value, 1) for value in [*widget.pos, *widget.size]))
                                 for surface in surfaces for widget in surface.walk(restrict=True))
                quiet[1] = quiet[1] + 1 if geometry == quiet[0] else 0
                quiet[0] = geometry
                if any(transition.is_active for transition in transitions) or quiet[1] < 3:
                    if time.perf_counter() - started > 5:
                        self._response.write_text(json.dumps({"id": request.get("id"), "error": "Scene transition did not settle"}), encoding="utf-8")
                    else:
                        Clock.schedule_once(settled, .05)
                    return
                self._report(request, started)
            Clock.schedule_once(settled, .75)
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
            self._current_scene = name
            if name in ("control", "preview", "console"):
                root.content.current = "Control" if name == "control" else "File"
                self.app.show_lines = name == "console"
                self.app.show_preview = name != "console"
                if name == "console":
                    root.cmd_manager.current = "manual_cmd_page"
                return
            if name in ("actions", "jog-settings", "history", "local-files", "file-search"):
                if name in ("actions", "jog-settings"):
                    root.content.current = "Control"
                elif name == "history":
                    root.manual_cmd.past_mdi_commands = ["G0 X10 Y20", "G1 Z-1.25 F100"]
                    root.manual_cmd.show_touch_history()
                else:
                    from kivy.clock import Clock

                    folder = Path(self.app.user_data_dir) / "exports"
                    folder.mkdir(exist_ok=True)
                    (folder / "Fixture folders and saved programs").mkdir(exist_ok=True)
                    for filename in ("Fixture plate.cnc", "Fixture part with a long name in setup three.cnc"):
                        (folder / filename).write_text("G21 G90\nG0 X0 Y0\n", encoding="utf-8")
                    root.open_upload_local_file_popup()
                    root.file_popup.local_rv.child_dir(str(folder))
                    root.file_popup.open(animation=False)
                    if name == "file-search":
                        Clock.schedule_once(lambda _dt: root.file_popup._mobile_search_buttons["local"].dispatch("on_release"), .1)
                return
            if name == "picker":
                from .ui.LocalFilePicker import open_local_file_picker

                open_local_file_picker(title="Simulator save destination", default_name="retained-draft.json",
                                       on_confirm=lambda *_args: None)
                return
            mapping = {"input": root.input_popup, "unlock": root.unlock_popup, "job": root.coord_popup,
                       "files": root.file_popup, "settings": root.config_popup, "wcs": root.wcs_settings_popup,
                       "diagnostics": root.diagnose_popup, "updates": root.upgrade_popup,
                       "confirm": root.confirm_popup, "message": root.message_popup,
                       "reconnect": root.reconnection_popup, "progress": root.progress_popup,
                       "probe-choice": root.select_probe_popup}
            if name in ("color-editor", "macro-editor", "numeric-editor", "text-editor", "option-editor"):
                from .custom_widgets import SettingColorPicker, SettingGCodeSnippet
                from .ui.settings_fields import EditingSettingNumeric, EditingSettingOptions, EditingSettingString

                types = {"color-editor":SettingColorPicker, "macro-editor":SettingGCodeSnippet,
                         "numeric-editor":EditingSettingNumeric,"text-editor":EditingSettingString,
                         "option-editor":EditingSettingOptions}
                root.config_popup.open(animation=False)
                setting = next(item for item in root.config_popup._all_setting_items() if type(item) is types[name])
                self._editor = setting
                if name in ("color-editor", "macro-editor"):
                    setting.open_popup()
                else:
                    setting._create_popup(None)
                return
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
                       for container in surface.walk(restrict=True) for name, widget in container.ids.items()
                       if isinstance(widget, TextInput)}
            editor = getattr(self, "_editor", None)
            if editor is not None:
                for name, attribute in (("editor", "textinput"), ("macro_name", "name_input"), ("macro_gcode", "gcode_input")):
                    if hasattr(editor, attribute):
                        widgets[name] = getattr(editor, attribute)
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
            from kivy.config import Config

            density = float(os.environ.get("CARVERA_ANDROID_DENSITY", "1"))
            Config.set("carvera", "android_ui_scale", str(request["scale"]))
            Config.write()
            Metrics.density = density * float(request["scale"])
            self.app.touch_target = max(48 * density, 48 * Metrics.density)
            self.app._touch_layout.size_controls(root)
            self.app._touch_layout.update()
        elif op == "state":
            from .CNC import CNC

            state = request.get("state", "N/A")
            model = request.get("model", "CA1")
            if state not in ("Idle", "Run", "Pause", "Hold", "Tool", "Sleep", "Alarm", "N/A") or model not in ("CA1", "C1"):
                raise ValueError("Unsupported simulated state")
            self.app.root.config_loaded = True
            CNC.vars["state"] = state
            self.app.model = model
            self.app.state = state
            self.app.has_4axis = bool(request.get("rotary", False))
            if "atc" in request:
                self.app.has_atc = bool(request["atc"])
            if "community" in request:
                self.app.is_community_firmware = bool(request["community"])
                root.controller.is_community_firmware = self.app.is_community_firmware
            if "firmware" in request:
                from .Utils import digitize_v

                self.app.fw_version_digitized = digitize_v(request["firmware"])
            if "playing" in request:
                self.app.playing = bool(request["playing"])
            if "filename" in request:
                self.app.selected_remote_filename = request["filename"]
            if request.get("populate_wcs"):
                popup = self.app.root.wcs_settings_popup
                popup.original_values = {name:dict.fromkeys(("X","Y","Z","A","R"),0.0)
                                         for name in ("G54","G55","G56","G57","G58","G59","G59.1","G59.2","G59.3")}
                for key, field in popup.ids.items():
                    if key.startswith("g5") and not key.endswith("description") and hasattr(field,"text"):
                        field.disabled = False
                        field.text = "0"
        elif op == "populate_preview":
            import threading

            path = Path(self.app.user_data_dir) / "simulated-preview.cnc"
            path.write_text("G21 G90\n" + "".join(f"G1 X{i % 120} Y{(i // 120) % 80} F600\n" for i in range(2000)), encoding="utf-8")
            threading.Thread(target=root.load_gcode_file, args=(str(path),), daemon=True).start()
        elif op == "dismiss_keyboard":
            Window.release_all_keyboards()
        elif op != "inspect":
            raise ValueError("Unknown simulator inspection operation")

    def _report(self, request, started):
        from kivy.core.window import Window
        from kivy.metrics import Metrics
        from kivy.uix.button import Button
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
        report.update(scene=getattr(self, "_current_scene", None), page=self.app.root.content.current,
                      command_page=self.app.root.cmd_manager.current,
                      source_revision=os.environ.get("CARVERA_SOURCE_REVISION", "development"))
        report["visible_actions"] = []
        for surface in surfaces:
            for widget in surface.walk(restrict=True):
                if not isinstance(widget, Button) or not widget.width or not widget.height or widget.get_root_window() is not Window:
                    continue
                ancestor = widget
                visible = True
                while ancestor is not None and ancestor is not Window:
                    if not ancestor.opacity or not ancestor.width or not ancestor.height:
                        visible = False
                        break
                    ancestor = ancestor.parent
                if visible:
                    report["visible_actions"].append({"text":widget.text, "bounds":[*widget.to_window(*widget.pos), *widget.size],
                                                      "texture":list(widget.texture_size)})
        self._response.write_text(json.dumps(report), encoding="utf-8")

    def close(self):
        from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils

        if getattr(self, "_poll_event", None) is not None:
            self._poll_event.cancel()
        ConfigUtils.flush_saves()
        ConfigUtils._writer.submit(lambda: None).result(timeout=5)
        self._patches.close()
