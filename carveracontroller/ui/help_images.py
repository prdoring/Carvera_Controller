"""Detailed help artwork that is decoded only while visible."""

from functools import lru_cache

from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.resources import resource_find
from kivy.uix.image import Image


@lru_cache(maxsize=128)
def detail_source(source):
    prefix = "addons/probing/data/icons_1024x768/"
    if source.startswith(prefix) and not source.startswith(prefix + "details/"):
        candidate = prefix + "details/" + source[len(prefix) :]
        if resource_find(candidate):
            return candidate
    return source


class ViewportHelpImage(Image):
    """Keep only the images intersecting the help viewport resident."""

    image_path = StringProperty("")

    def __init__(self, viewport, **kwargs):
        self.viewport = viewport
        kwargs.update(nocache=True, fit_mode="contain", size_hint_y=None)
        super().__init__(**kwargs)
        self._refresh = Clock.create_trigger(self._visibility, 0)
        self.bind(width=self._square, pos=self._refresh, size=self._refresh, parent=self._refresh)
        viewport.bind(scroll_y=self._refresh, size=self._refresh, pos=self._refresh)
        self._square()

    def _square(self, *_args):
        self.height = self.width
        self._refresh()

    def _visibility(self, *_args):
        if self.get_root_window() is None:
            visible = False
        else:
            x, y = self.to_window(*self.pos)
            vx, vy = self.viewport.to_window(*self.viewport.pos)
            visible = (
                x < vx + self.viewport.width
                and x + self.width > vx
                and y < vy + self.viewport.height
                and y + self.height > vy
            )
        source = detail_source(self.image_path) if visible else ""
        if self.source != source:
            self.source = source

    def close(self):
        self._refresh.cancel()
        self.viewport.unbind(scroll_y=self._refresh, size=self._refresh, pos=self._refresh)
        self.source = ""
        self.texture = None
