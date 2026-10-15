"""Pace machine configuration commands without blocking the Kivy loop."""

from collections import deque

from kivy.clock import Clock


class SettingsApply:
    def __init__(self, controller, pending, progress, finished):
        self.controller = controller
        self.pending = pending
        self.progress = progress
        self.finished = finished
        self.active = False
        self._event = None

    def start(self):
        if self.active:
            return False
        self._stream = self.controller.stream
        self._queue = deque(self.pending.items())
        self._total = len(self._queue)
        self.active = True
        self._event = Clock.schedule_once(self._send_next, 0)
        return True

    def _send_next(self, _dt):
        self._event = None
        if not self.active:
            return
        if self._stream is None or self.controller.stream is not self._stream or not self.controller.protocol_ready:
            self._finish("connection")
            return
        if not self._queue:
            self._finish(None)
            return
        key, value = self._queue[0]
        try:
            if self.controller.setConfigValue(key, value) is False:
                self._finish("send")
                return
        except Exception:
            self._finish("send")
            return
        self._queue.popleft()
        if self.pending.get(key) == value:
            self.pending.pop(key)
        self.progress(self._total - len(self._queue), self._total)
        self._event = Clock.schedule_once(self._send_next, 0.1)

    def _finish(self, error):
        self.active = False
        self.finished(error)

    def cancel(self, notify=True):
        if self._event is not None:
            self._event.cancel()
            self._event = None
        if self.active:
            self.active = False
            if notify:
                self.finished("cancelled")
