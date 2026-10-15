"""Helpers for working with Kivy widgets."""

from typing import Any

from kivy.clock import Clock


def bind_auto_select_to_text_input(widget: Any) -> None:
    if getattr(widget, "_auto_select_bound", False):
        return
    widget._auto_select_bound = True
    pending = None

    def cancel_selection(*_args):
        nonlocal pending
        if pending is not None:
            pending.cancel()
            pending = None

    def select_initial(_dt):
        nonlocal pending
        pending = None
        if widget.focus:
            widget.select_all()

    def focus_handler(_input: Any, focused: bool) -> None:
        nonlocal pending
        cancel_selection()
        if focused:
            pending = Clock.schedule_once(select_initial, 0)

    def touch_handler(_input, touch):
        if widget.focus and widget.collide_point(*touch.pos):
            cancel_selection()

    widget.bind(focus=focus_handler)
    widget.bind(on_touch_down=touch_handler, text=cancel_selection)
