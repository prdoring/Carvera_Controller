"""Compact forms reuse their editors, values, focus and callbacks."""

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout

from carveracontroller.translation import tr

from .android_layout import DialogLabel


class WorkspaceLayout:
    def __init__(self, popup):
        self.popup = popup
        self.grid = popup.ids.wcs_grid
        self.original = list(reversed(self.grid.children))
        self.geometry = {w: (w.size_hint, w.width, w.height) for w in self.original}
        self.cards = None
        self.compact = None

    def update(self, *_args):
        app = App.get_running_app()
        compact = app.android_touch and app.compact_layout
        if compact == self.compact:
            return
        self.compact = compact
        self.grid.clear_widgets()
        if compact:
            self.grid.cols = 1
            if self.cards is None:
                self.cards = []
                for offset in range(8, len(self.original), 8):
                    items = self.original[offset:offset + 8]
                    if len(items) != 8:
                        continue
                    card = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8), padding=dp(8))
                    card.bind(minimum_height=card.setter("height"))
                    activate, *fields, clear, description = items
                    for widget in items:
                        widget.size_hint = (1, None)
                        widget.height = max(app.touch_target, dp(56))
                    card.add_widget(DialogLabel(text=activate.text + " — " + tr._("Activate immediately"), bold=True))
                    card.add_widget(activate)
                    values = GridLayout(cols=2, size_hint_y=None, spacing=dp(8))
                    values.bind(minimum_height=values.setter("height"))
                    for name, field in zip(("X offset", "Y offset", "Z offset", "A (degrees)", "Rotation (degrees)"), fields):
                        values.add_widget(DialogLabel(text=tr._(name)))
                        values.add_widget(field)
                    card.add_widget(values)
                    card.add_widget(clear)
                    card.add_widget(DialogLabel(text=tr._("Description — saved automatically on this device")))
                    card.add_widget(description)
                    self.cards.append(card)
            else:
                # Editors move back from the expanded grid into the existing cards.
                for card in self.cards:
                    for container, index, widget in sorted(card._editor_slots, key=lambda slot: slot[1]):
                        container.add_widget(widget, index=index)
            for widget in self.original[8:]:
                widget.size_hint = (1, None)
                widget.height = max(app.touch_target, dp(56))
            for card in self.cards:
                self.grid.add_widget(card)
        else:
            if self.cards:
                for card in self.cards:
                    slots = []
                    for widget in self.original:
                        if widget.parent is not None:
                            parent = widget.parent
                            slots.append((parent, parent.children.index(widget), widget))
                    card._editor_slots = [slot for slot in slots if slot[0] is card or slot[0].parent is card]
                for widget in self.original:
                    if widget.parent is not None:
                        widget.parent.remove_widget(widget)
            self.grid.cols = 8
            for widget in self.original:
                widget.size_hint, widget.width, widget.height = self.geometry[widget]
                self.grid.add_widget(widget)
