"""Android input metadata that SDL2 does not expose to Kivy."""

import json
from collections import defaultdict, deque

from kivy.clock import Clock

from . import touch as gestures


class AndroidInput:
    def __init__(self, app):
        from android.runnable import run_on_ui_thread
        from jnius import autoclass

        self.app = app
        self.edges = defaultdict(deque)
        self.api = autoclass("org.carveracommunity.controller.InputBridge")

        @run_on_ui_thread
        def install():
            self.api.install(autoclass("org.kivy.android.PythonActivity").mActivity)

        install()
        self._poll_event = Clock.schedule_interval(lambda dt: self.poll(), 0.05)

    def poll(self):
        state = json.loads(self.api.drain())
        for pointer, action in state["edges"]:
            self.edges[str(pointer)].append(action)
        if state["slop"]:
            gestures.touch_slop = state["slop"]
            gestures.hold_timeout = state["hold_ms"] / 1000
        if state["interrupted"]:
            gestures.cancel_all_touches()
            self.app.root.controller.stopContinuousJog()
            self.edges.clear()
        self.app.safe_area_padding = state["insets"]
        self.app.android_keyboard_height = state["keyboard_height"]

    def process(self, events):
        self.poll()
        for phase, motion in events:
            if motion.device != "sdl" or phase not in ("begin", "end"):
                continue
            queue = self.edges[str(motion.id)]
            if queue:
                action = queue.popleft()
                if action == "cancel" or (phase == "end" and action != "up"):
                    gestures.cancel_touch(motion)
            if not queue:
                self.edges.pop(str(motion.id), None)
        return events

    def stop(self):
        self._poll_event.cancel()
