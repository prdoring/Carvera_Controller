"""Live power adjustment for a vacuum connected to the external output."""

import time

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.CNC import CNC
from carveracontroller.translation import tr


class VacuumPowerControl(BoxLayout):
    value = NumericProperty(50)
    enabled = BooleanProperty(False)
    caption = StringProperty("")
    _syncing = False

    def __init__(self, **kwargs):
        self._pending = None
        self._last_send = 0
        self._refresh_event = None
        self._send_event = Clock.create_trigger(self._send_power, .15)
        super().__init__(**kwargs)

    def start(self):
        self.stop()
        self._last_send = 0
        CNC.vars["extout_report_time"] = 0
        self._refresh_event = Clock.schedule_interval(self.refresh, .1)
        self.refresh()

    def stop(self):
        self._send_event.cancel()
        self._pending = None
        self.enabled = False
        if self._refresh_event is not None:
            self._refresh_event.cancel()
            self._refresh_event = None

    def refresh(self, *_args):
        if self._refresh_event is None:
            self.enabled = False
            return
        app = App.get_running_app()
        fresh = time.monotonic() - CNC.vars.get("extout_report_time", 0) < 2
        known = fresh and CNC.vars.get("extout_power") is not None
        self.enabled = bool(known and CNC.vars.get("extout_state")
                            and app.model in ("C1", "CA1") and app.state in ("Idle", "Run"))
        if not self.enabled:
            self._send_event.cancel()
            self._pending = None
            self.caption = tr._("Off") if known and not CNC.vars.get("extout_state") else "—"
        elif self._pending is None and time.monotonic() - self._last_send > 1:
            self._syncing = True
            try:
                self.value = max(50, min(100, CNC.vars["extout_power"]))
            finally:
                self._syncing = False
            self.caption = f'{CNC.vars["extout_power"]:.0f}%'

    def change_power(self, value):
        if self._syncing or not self.enabled:
            return
        self.value = max(50, min(100, round(value)))
        self.caption = f"{self.value:.0f}%"
        self._pending = self.value
        self._send_event()

    def _send_power(self, _dt):
        self.refresh()
        if self.enabled and self._pending is not None:
            App.get_running_app().root.controller.setExternalControl(self._pending)
            self._pending = None
            self._last_send = time.monotonic()
