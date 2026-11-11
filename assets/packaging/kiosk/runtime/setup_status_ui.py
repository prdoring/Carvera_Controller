"""Limited initial-setup status, independent of controller availability."""

import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PRESENTATION = Path(__file__).resolve().parent.parent / "system-ui"
sys.path.insert(0, str(PRESENTATION if PRESENTATION.exists() else Path(__file__).resolve().parents[4]))
os.environ["KIVY_HOME"] = "/var/lib/carvera/recovery"

from runtime_profile import configure, prepare

prepare()
from kivy.config import Config

configure(Config)
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget
from system_ui import Panel, Paragraph, button, install_style

from carveracontroller.translation import init, tr


class SetupStatus(App):
    def build(self):
        self.title = "Carvera Initial Setup"
        init("en")
        install_style()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="setup-status")
        self.pending = False
        shell = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(16))
        shell.add_widget(Paragraph(text=tr._("Kiosk setup"), font_size=sp(24), bold=True))
        panel = Panel()
        self.message = Paragraph(
            text=tr._("The Pi is finishing setup. Keep it powered and wait for the controller screen to open.")
        )
        panel.add_widget(self.message)
        self.details = Paragraph(text="", font_name="PlexMono")
        panel.add_widget(self.details)
        shell.add_widget(panel)
        shell.add_widget(Widget())
        self.feedback = Paragraph(text="")
        shell.add_widget(self.feedback)
        actions = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(12))
        self.retry = button(tr._("Retry the same setup"), lambda: self.request("setup-retry"))
        self.shutdown = button(tr._("Shut down"), lambda: self.request("setup-shutdown"))
        actions.add_widget(self.retry)
        actions.add_widget(self.shutdown)
        shell.add_widget(actions)
        self.poll = Clock.schedule_interval(lambda _dt: self.refresh(), 3)
        self.refresh()
        return shell

    def refresh(self):
        try:
            path = Path("/run/carvera-maint/setup-status.json")
            if path.stat().st_size > 65536:
                raise ValueError("Invalid status")
            value = json.loads(path.read_text())
            if not isinstance(value, dict):
                raise ValueError("Invalid status")
            phase = value.get("phase", "unknown")
            fingerprints = value.get("host_fingerprints", [])
            if not isinstance(fingerprints, list) or any(not isinstance(item, str) for item in fingerprints):
                raise ValueError("Invalid identity")
            fingerprint = "\n".join(fingerprints)
            stages = {
                "fresh": tr._("Waiting to apply Pi settings"),
                "applying": tr._("Applying Pi settings"),
                "complete": tr._("Pi setup complete"),
                "unknown": tr._("Setup status needs attention"),
            }
            self.details.text = tr._("{stage}\nSSH identity:\n{fingerprint}").format(
                stage=stages.get(phase, stages["unknown"]), fingerprint=fingerprint or tr._("Not available yet")
            )
            messages = {
                "storage": tr._(
                    "Pi storage preparation did not finish. Choose Retry the same setup and keep the Pi powered. This can take several minutes."
                ),
                "interrupted": tr._(
                    "Setup was interrupted. Choose Retry the same setup to continue with your saved settings and keys."
                ),
                "configuration": tr._(
                    "Pi settings could not be applied. On your computer, open Carvera Kiosk Setup and choose Continue a saved setup."
                ),
                "system": tr._(
                    "Setup needs recovery. Shut down the Pi and open Continue a saved setup in Carvera Kiosk Setup on your computer."
                ),
            }
            self.message.text = messages.get(
                value.get("error"),
                tr._("The Pi is finishing setup. Keep it powered and wait for the controller screen to open."),
            )
            if phase not in {"fresh", "applying", "complete"}:
                self.message.text = messages["system"]
            self.retry.disabled = self.pending or phase not in {"fresh", "applying"}
        except (OSError, ValueError, TypeError):
            self.message.text = tr._(
                "Setup status is unavailable. Shut down the Pi, then choose Continue a saved setup in Carvera Kiosk Setup on your computer."
            )
            self.details.text = ""
            self.retry.disabled = True

    def request(self, action):
        if self.pending:
            return
        self.pending = True
        self.pending_action = action
        self.retry.disabled = self.shutdown.disabled = True
        self.feedback.text = tr._("Shutting down…") if action == "setup-shutdown" else tr._("Retrying the same setup…")
        future = self.executor.submit(
            subprocess.run,
            ["sudo", "-n", "/usr/local/sbin/carvera-recover"],
            input=json.dumps({"action": action, "id": uuid.uuid4().hex}),
            text=True,
            capture_output=True,
            timeout=150,
            check=False,
        )
        future.add_done_callback(lambda result: Clock.schedule_once(lambda _dt: self.finished(result)))

    def finished(self, future):
        self.pending = False
        self.retry.disabled = self.shutdown.disabled = False
        try:
            result = future.result()
            reply = json.loads(result.stdout)
            self.feedback.text = (
                (
                    tr._("Shutting down…")
                    if self.pending_action == "setup-shutdown"
                    else tr._("Retrying setup. Storage preparation may take several minutes.")
                )
                if reply.get("ok")
                else tr._(
                    "Setup remains incomplete. Choose Continue a saved setup in Carvera Kiosk Setup on your computer."
                )
            )
        except Exception:
            self.feedback.text = tr._(
                "Setup remains incomplete. Choose Continue a saved setup in Carvera Kiosk Setup on your computer."
            )
        self.refresh()

    def on_stop(self):
        if hasattr(self, "poll"):
            self.poll.cancel()
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    SetupStatus().run()
