"""Linux keyboard placement and a main-thread maintenance handshake."""

import os
import subprocess
import time
from pathlib import Path

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics.opengl import GL_RENDERER, glGetString
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.vkeyboard import VKeyboard

from . import runtime_profile
from .kiosk_state import activity, read_json, require_idle, write_json


class KioskRuntime:
    def __init__(self, app):
        self.app = app
        self.directory = Path(os.environ.get("CARVERA_RUNTIME_DIR", "/run/carvera"))
        self.maintenance = Path(os.environ.get("CARVERA_MAINT_DIR", "/run/carvera-maint"))
        self.token = None
        self.pending = None
        self.idle_since = None
        self.error = None
        self.rejected = None
        self._saved_controls = None
        self._keyboards = set()
        self._recovery_process = None
        self.panel = None
        self.renderer = glGetString(GL_RENDERER).decode("utf-8")
        Window.bind(children=self.keyboard_changed)
        self.event = Clock.schedule_interval(self.tick, 0.5)
        self.keyboard_changed()
        self.tick(0)

    def keyboard_changed(self, *_args):
        keyboards = {child for child in Window.children if isinstance(child, VKeyboard)}
        for keyboard in self._keyboards - keyboards:
            keyboard.unbind(size=self.keyboard_changed)
        for keyboard in keyboards - self._keyboards:
            keyboard.bind(size=self.keyboard_changed)
        self._keyboards = keyboards
        self.app.android_keyboard_height = max((keyboard.height for keyboard in keyboards), default=0)

    def open_recovery(self):
        if self._recovery_process is None or self._recovery_process.poll() is not None:
            self._recovery_process = subprocess.Popen([
                "/opt/carvera/recovery-venv/bin/python", "/opt/carvera/maintenance/recovery.py",
            ])

    def tick(self, _dt):
        status = activity(self.app)
        status["renderer"] = self.renderer
        status["display"] = list(Window.size)
        from .__version__ import __version__

        status["version"] = __version__
        request = read_json(self.maintenance / "maintenance.request")
        token = request.get("token")
        if (self.token or self.pending) and token != (self.token or self.pending):
            self.resume()
        if token and token != self.rejected and self.token is None:
            try:
                require_idle(status, confirmed=request.get("confirmed_idle") is True)
            except ValueError as error:
                self.rejected = token
                self.error = str(error)
                if self.pending:
                    self.resume()
            else:
                if self.pending != token:
                    from .ui.touch import cancel_all_touches

                    cancel_all_touches()
                    root = self.app.root
                    self._saved_controls = (root.disabled, root.keyboard_jog_control, root.pendant_jog_control)
                    root.keyboard_jog_control = root.pendant_jog_control = False
                    root.disabled = True
                    self.pending = token
                    self.idle_since = time.monotonic()
                    runtime_profile.maintenance_active = True
                    self.show_maintenance()
                elif time.monotonic() - self.idle_since >= 2:
                    self.token = token
                    self.pending = None
        elif not token and (self.token or self.pending):
            self.resume()
        if token == self.rejected:
            status["error"] = self.error
        status["maintenance"] = self.token is not None
        status["token"] = self.token
        write_json(self.directory / "status.json", status)

    def resume(self):
        root = self.app.root
        root.disabled, root.keyboard_jog_control, root.pendant_jog_control = self._saved_controls
        self.token = self.pending = None
        runtime_profile.maintenance_active = False
        self.panel.dismiss()
        self.panel = None

    def show_maintenance(self):
        self.panel = ModalView(size_hint=(0.65, None), height=dp(250), auto_dismiss=False)
        content = BoxLayout(orientation="vertical", spacing=dp(16), padding=dp(20))
        content.add_widget(Label(text="System maintenance\nMachine controls are paused.", halign="center"))
        stop = Button(text="Emergency stop", background_normal="", background_color=(0.75, 0.12, 0.1, 1))
        stop.bind(on_release=lambda *_: self.app.root.controller.estopCommand())
        content.add_widget(stop)
        system = Button(text="Network and controller recovery")
        system.bind(on_release=lambda *_: self.open_recovery())
        content.add_widget(system)
        self.panel.add_widget(content)
        self.panel.open()

    def stop(self):
        runtime_profile.maintenance_active = False
        self.event.cancel()
        if self.panel is not None:
            self.panel.dismiss()
        Window.unbind(children=self.keyboard_changed)
        for keyboard in self._keyboards:
            keyboard.unbind(size=self.keyboard_changed)
        if self._recovery_process is not None and self._recovery_process.poll() is None:
            self._recovery_process.terminate()
            try:
                self._recovery_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._recovery_process.kill()
                self._recovery_process.wait(timeout=2)
        (self.directory / "status.json").unlink(missing_ok=True)
