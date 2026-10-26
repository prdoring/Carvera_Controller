"""Android input metadata that SDL2 does not expose to Kivy."""

import json
from collections import defaultdict, deque

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
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            params = autoclass("android.view.WindowManager$LayoutParams")
            activity.getWindow().setSoftInputMode(params.SOFT_INPUT_ADJUST_NOTHING)
            self.api.install(activity)

        install()

    def poll(self):
        state = json.loads(self.api.drain())
        for pointer, action, travel in state["edges"]:
            self.edges[str(pointer)].append((action, travel))
        if state["slop"]:
            gestures.touch_slop = state["slop"]
            gestures.hold_timeout = state["hold_ms"] / 1000
        if state["interrupted"]:
            gestures.cancel_all_touches()
            self.app.root.controller.stopContinuousJog()
            self.edges.clear()
        insets = state["insets"]
        if state["keyboard_height"]:
            insets[3] = self.app.safe_area_padding[3]
        self.app.safe_area_padding = insets
        self.app.android_keyboard_height = state["keyboard_height"]
        return state["interrupted"]

    def process(self, events):
        interrupted = self.poll()
        for phase, motion in events:
            if interrupted:
                gestures.cancel_touch(motion)
            if motion.device != "sdl" or phase not in ("begin", "end"):
                continue
            queue = self.edges[str(motion.id)]
            if queue:
                action, travel = queue.popleft()
                if travel > gestures.touch_slop:
                    motion.ud["carvera_dragged"] = True
                if action == "cancel" or (phase == "end" and action != "up") or (phase == "begin" and action != "down"):
                    gestures.cancel_touch(motion)
            if not queue:
                self.edges.pop(str(motion.id), None)
        return events

    def stop(self):
        self.edges.clear()
        self.api.uninstall()
