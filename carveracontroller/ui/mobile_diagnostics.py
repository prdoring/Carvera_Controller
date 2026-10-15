"""Group the existing diagnostic widgets without changing their commands."""

from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem

from carveracontroller.translation import tr

from .android_layout import DialogLabel
from .mobile_tools import operation_selector


def prepare_diagnostics(modal):
    if getattr(modal, "_diagnostics_prepared", False):
        return
    modal._diagnostics_prepared = True
    old = modal.ids.sw_spindle.parent.parent
    columns = list(reversed(old.children))
    parent = old.parent
    index = parent.children.index(old)
    note = parent.children[index - 1]
    parent.remove_widget(old)
    parent.remove_widget(note)
    tabs = TabbedPanel(do_default_tab=False)
    outputs = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8), padding=dp(8))
    outputs.bind(minimum_height=outputs.setter("height"))
    outputs.add_widget(DialogLabel(text=tr._("Unavailable controls follow the detected machine and installed capabilities. Values are applied after two seconds.")))
    groups = [list(reversed(column.children)) for column in columns[:2]]
    for position in range(max(map(len, groups))):
        for column, widgets in zip(columns[:2], groups):
            if position >= len(widgets):
                continue
            widget = widgets[position]
            column.remove_widget(widget)
            if isinstance(widget, Label) and widget.text:
                outputs.add_widget(DialogLabel(text=widget.text))
                continue
            if not widget.children:
                continue
            widget.size_hint_y = None
            widget.height = max(dp(144), sp(16) * 3 + dp(16)) if hasattr(widget, "slider") else max(dp(64), sp(16) * 3 + dp(16))
            outputs.add_widget(widget)
            if isinstance(getattr(widget, "label", None), str):
                label = widget.label
                def availability(item, disabled, text=label):
                    item.label = text + (" — " + tr._("unavailable") if disabled else "")
                widget.bind(disabled=availability)
                availability(widget, widget.disabled)
            for child in widget.children:
                if isinstance(child, Label):
                    child.bind(width=lambda label, width: setattr(label, "text_size", (width, None)))
    inputs = GridLayout(cols=2, size_hint_y=None, spacing=dp(8), padding=dp(8))
    inputs.bind(minimum_height=inputs.setter("height"))
    for column in columns[2:]:
        for widget in list(reversed(column.children)):
            column.remove_widget(widget)
            if not hasattr(widget, "state"):
                continue
            widget.size_hint_y = None
            widget.height = max(dp(64), sp(16) * 2 + dp(16))
            inputs.add_widget(widget)
    for title, content in ((tr._("Outputs"), outputs), (tr._("Inputs / sensors"), inputs)):
        tab = TabbedPanelItem(text=title)
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(content)
        tab.add_widget(scroll)
        tabs.add_widget(tab)
    parent.add_widget(tabs, index=index - 1)
    operation_selector(tabs)
