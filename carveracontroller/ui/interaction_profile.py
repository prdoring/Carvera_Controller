"""Optional app-side input and frame timing, without recording entered text."""

import json
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from kivy.clock import Clock
from kivy.core.window import Window


def distribution(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {"count": len(values), "p50_ms": values[int((len(values) - 1) * .5)] * 1000,
            "p95_ms": values[int((len(values) - 1) * .95)] * 1000,
            "max_ms": values[-1] * 1000, "over_100ms": sum(value > .1 for value in values)}


class InteractionProfile:
    def __init__(self, output):
        self.output = Path(output)
        self.frames = deque(maxlen=60000)
        self.feedback = deque(maxlen=10000)
        self._pending = []
        self._last_frame = None
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="interaction-profile")
        self._write = None
        Window.bind(on_motion=self.motion, on_flip=self.flip)
        self._frame_event = Clock.schedule_interval(self.frame, 0)
        self._save_event = Clock.schedule_interval(self.save, 2)

    def motion(self, _window, phase, motion):
        if phase == "begin" and motion.is_touch:
            self._pending.append(time.perf_counter())

    def frame(self, _dt):
        now = time.perf_counter()
        if self._last_frame is not None:
            self.frames.append(now - self._last_frame)
        self._last_frame = now

    def flip(self, *_args):
        now = time.perf_counter()
        self.feedback.extend(now - started for started in self._pending)
        self._pending.clear()

    def save(self, _dt=0):
        if self._write is None or self._write.done():
            frames, feedback = list(self.frames), list(self.feedback)
            self._write = self._writer.submit(self._save, frames, feedback)

    def _save(self, frames, feedback):
        result = {"measurement": "Kivy motion dispatch to next frame flip; excludes hardware/Android input latency",
                  "frames": distribution(frames), "press_feedback": distribution(feedback)}
        self.output.write_text(json.dumps(result, indent=2), encoding="utf-8")

    def stop(self):
        Window.unbind(on_motion=self.motion, on_flip=self.flip)
        self._save_event.cancel()
        self._frame_event.cancel()
        self._writer.submit(self._save, list(self.frames), list(self.feedback))
        self._writer.shutdown(wait=False)
