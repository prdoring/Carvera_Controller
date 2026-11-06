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
        self.message = Paragraph(text=tr._("Initial setup has not finished. The controller is stopped."))
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
            phase = value.get("phase", "unknown")
            fingerprint = "\n".join(value.get("host_fingerprints", []))
            self.details.text = tr._("Setup stage: {phase}\nSSH fingerprint:\n{fingerprint}").format(
                phase=phase, fingerprint=fingerprint or tr._("Not available yet")
            )
            if value.get("error"):
                self.message.text = tr._(
                    "Setup could not finish. Use the same setup profile to recover, or reflash the card."
                )
        except (OSError, ValueError, TypeError):
            self.details.text = tr._("Setup status is unavailable. Shut down and inspect the card with Kiosk Setup.")

    def request(self, action):
        if self.pending:
            return
        self.pending = True
        self.retry.disabled = self.shutdown.disabled = True
        self.feedback.text = tr._("Checking setup…")
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
                tr._("Retrying setup. Storage preparation may take several minutes.")
                if reply.get("ok")
                else tr._("Setup remains incomplete. Check the card with Kiosk Setup.")
            )
        except Exception:
            self.feedback.text = tr._("Setup remains incomplete. Check the card with Kiosk Setup.")
        self.refresh()

    def on_stop(self):
        if hasattr(self, "poll"):
            self.poll.cancel()
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    SetupStatus().run()
