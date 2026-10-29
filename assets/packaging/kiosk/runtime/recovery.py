"""Independent touchscreen networking and controller recovery."""

import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime_profile import configure, prepare

os.environ["KIVY_HOME"] = str(Path(os.environ.get("CARVERA_DATA_DIR", "/var/lib/carvera")) / "recovery")
prepare()
from kivy.config import Config

configure(Config)
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.vkeyboard import VKeyboard


class Recovery(App):
    def build(self):
        Window.softinput_mode = "pan"
        self.title = "Carvera system maintenance"
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kiosk-recovery")
        root = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        root.add_widget(Label(text=self.title, size_hint_y=None, height=dp(48), font_size=dp(24)))
        self.status = Label(text="Reading connection details…", halign="left", valign="top")
        self.status.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        root.add_widget(self.status)
        self.ssid = TextInput(hint_text="Wi-Fi network name", multiline=False, size_hint_y=None, height=dp(48))
        self.password = TextInput(hint_text="Wi-Fi password", password=True, multiline=False, size_hint_y=None, height=dp(48))
        root.add_widget(self.ssid)
        root.add_widget(self.password)
        confirmation = BoxLayout(size_hint_y=None, height=dp(48))
        self.idle = CheckBox(size_hint_x=None, width=dp(48))
        confirmation.add_widget(self.idle)
        confirmation.add_widget(Label(text="I confirm the machine is idle before changing networking or restarting."))
        root.add_widget(confirmation)
        buttons = BoxLayout(spacing=dp(8), size_hint_y=None, height=dp(56))
        for title, action in (
            ("Refresh", self.refresh), ("Connect Wi-Fi", lambda: self.perform("wifi")),
            ("Keep new network", lambda: self.perform("wifi-confirm")),
            ("Restart controller", lambda: self.perform("restart")), ("Close", self.close),
        ):
            button = Button(text=title, font_size=dp(16))
            button.bind(on_release=lambda _button, callback=action: callback())
            buttons.add_widget(button)
        root.add_widget(buttons)
        self.refresh()
        self.keyboard_event = Clock.schedule_interval(self.place_keyboard, 0.2)
        return root

    def place_keyboard(self, _dt):
        height = max((child.height for child in Window.children if isinstance(child, VKeyboard)), default=0)
        if self.root is not None:
            self.root.padding = (dp(24), dp(24), dp(24), dp(24) + height)

    def show(self, text):
        Clock.schedule_once(lambda _dt: setattr(self.status, "text", text))

    def refresh(self):
        def read():
            addresses = subprocess.run(["hostname", "-I"], capture_output=True, text=True, check=False).stdout.strip()
            fingerprint = subprocess.run(["ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub"],
                                         capture_output=True, text=True, check=False).stdout.strip()
            self.show(f"Network addresses: {addresses or 'not connected'}\n"
                      f"Laptop login: carvera-admin@{os.uname().nodename}.local\n"
                      f"SSH identity: {fingerprint}\n\n"
                      "Network changes revert after 120 seconds unless you select Keep new network.")
        self.worker.submit(read)

    def perform(self, action):
        if not self.idle.active:
            self.status.text = "Confirm that the machine is idle before making changes."
            return
        request = {"action": action, "confirmed_idle": True}
        if action == "wifi":
            request["wifi"] = {"ssid": self.ssid.text, "password": self.password.text}
        self.status.text = "Applying the requested change…"

        def apply():
            result = subprocess.run(["sudo", "-n", "/usr/local/sbin/carvera-recover"],
                                    input=json.dumps(request), text=True, capture_output=True, check=False)
            self.show(result.stdout if result.returncode == 0 else result.stderr)
            if result.returncode == 0 and action == "restart":
                Clock.schedule_once(lambda _dt: self.stop())
        self.worker.submit(apply)

    def close(self):
        try:
            value = json.loads(Path("/run/carvera/status.json").read_text())
        except (OSError, ValueError):
            self.status.text = "The controller is unavailable. Restart it after confirming the machine is idle."
            return
        if value.get("pid") and 0 <= time.monotonic() - value.get("updated", 0) <= 3 and not value.get("maintenance"):
            try:
                os.kill(value["pid"], 0)
            except OSError:
                pass
            else:
                self.stop()
                return
        self.status.text = "The controller is unavailable or in maintenance. Finish maintenance from the laptop or restart it."

    def on_stop(self):
        self.keyboard_event.cancel()
        self.worker.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    Recovery().run()
