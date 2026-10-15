"""Android touch sizing, keyboard space, help and Back navigation."""

import weakref
from functools import lru_cache

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.metrics import Metrics, dp, sp
from kivy.properties import BooleanProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.settings import SettingItem
from kivy.uix.slider import Slider
from kivy.uix.splitter import Splitter
from kivy.uix.switch import Switch
from kivy.uix.tabbedpanel import TabbedPanel
from kivy.uix.textinput import TextInput

from carveracontroller.translation import tr

from .touch import TapBehavior


@lru_cache(maxsize=256)
def _text_width(text, font, size):
    label = CoreLabel(text=text, font_name=font, font_size=size)
    label.refresh()
    return label.texture.size[0]


class TouchActionRow(GridLayout):
    """Action buttons wrap into full touch rows on a narrow interface."""

    stacked = BooleanProperty(False)

    def __init__(self, **kwargs):
        kwargs.setdefault("rows", None)
        super().__init__(**kwargs)
        self.bind(width=self._columns, children=self._columns, stacked=self._columns,
                  padding=self._columns, spacing=self._columns)
        self.bind(minimum_height=self.setter("height"))
        self.size_hint_y = None
        self._columns()

    def _columns(self, *_args):
        app = App.get_running_app()
        mobile = app is not None and app.android_touch
        width = max([app.touch_target if mobile else dp(48)] + [
            min(dp(200), _text_width(str(child.text), getattr(child, "font_name", "Roboto"), sp(16)) + dp(24))
            for child in self.children if mobile and hasattr(child, "text")])
        available = max(1, self.width - self.padding[0] - self.padding[2])
        self.cols = (1 if self.stacked else max(1, min(len(self.children) or 1,
                     int((available + self.spacing[0]) / (width + self.spacing[0]))))) if mobile else max(1, len(self.children))
        self.row_force_default = True
        self.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16)) if mobile else dp(40)
        if mobile:
            for child in self.children:
                child.size_hint_x = 1
                if isinstance(child, Button):
                    child.font_size = sp(16)
                    child.text_size = (max(1, (available - self.spacing[0] * (self.cols - 1)) / self.cols - dp(24)), None)
                    child.halign = "center"
                    child.valign = "middle"
                    child.texture_update()
                    self.row_default_height = max(self.row_default_height, child.texture_size[1] + dp(16))


class DialogLabel(Label):
    """Full wording that grows vertically instead of shrinking or clipping."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(width=self._fit, texture_size=self._fit, text=self._fit)
        self._fit()

    def _fit(self, *_args):
        app = App.get_running_app()
        if app is not None and app.android_touch:
            self.size_hint_y = None
            self.font_size = sp(18 if self.bold else 16)
            self.text_size = (max(1, self.width - dp(16)), None)
            self.height = max(dp(48), self.texture_size[1] + dp(16)) if self.text else 0


class DialogSurface(BoxLayout):
    """An explicitly managed dialog with a content viewport and fixed footer."""

    def on_parent(self, *_args):
        Clock.schedule_once(self._prepare_attached, 0)

    def _prepare_attached(self, _dt):
        app = App.get_running_app()
        if app is not None and app.android_touch and self.get_root_window() is not None:
            self.prepare()
            layout = getattr(app, "_touch_layout", None)
            if layout is not None:
                layout._update()

    def prepare(self):
        if getattr(self, "_prepared", False):
            return
        self._prepared = True
        self.orientation = "vertical"
        self.spacing = dp(8)
        children = list(reversed(self.children))
        if not children:
            return
        footer = children.pop() if isinstance(children[-1], TouchActionRow) else None
        self.clear_widgets()
        content = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))
        viewport = ScrollView(do_scroll_x=False)
        viewport.bind(height=lambda *_: setattr(viewport, "do_scroll_y", content.height > viewport.height + 1))
        content.bind(height=lambda *_: setattr(viewport, "do_scroll_y", content.height > viewport.height + 1))
        for child in children:
            self._natural_height(child)
            content.add_widget(child)
        viewport.add_widget(content)
        self.add_widget(viewport)
        if footer is not None:
            self.add_widget(footer)

    def _natural_height(self, widget):
        if isinstance(widget, ScrollView):
            return
        if isinstance(widget, BoxLayout) and widget.orientation == "vertical":
            for child in widget.children:
                self._natural_height(child)
            widget.size_hint_y = None
            widget.bind(minimum_height=widget.setter("height"))
            widget.height = widget.minimum_height
        elif isinstance(widget, GridLayout) and not isinstance(widget, TouchActionRow):
            widget.size_hint_y = None
            widget.row_force_default = True
            widget.row_default_height = max(dp(48), sp(16) * 2 + dp(16))
            widget.bind(minimum_height=widget.setter("height"))
        elif isinstance(widget, BoxLayout):
            widget.size_hint_y = None
            widget.height = max(dp(48), sp(16) * 2 + dp(16)) if widget.children else 0
        elif isinstance(widget, Label):
            widget.size_hint_y = None
            widget.text_size = (max(1, widget.width - dp(8)), None)
            widget.bind(width=lambda item, width: setattr(item, "text_size", (max(1, width - dp(8)), None)))
            widget.bind(texture_size=lambda item, size: setattr(item, "height", size[1] + dp(12) if item.text else 0))
            widget.height = widget.texture_size[1] + dp(12) if widget.text else 0


class AndroidTouchLayout:
    def __init__(self, app):
        self.app = app
        self.dialogs = weakref.WeakKeyDictionary()
        self._update = Clock.create_trigger(self.update, 0)
        self._history = []
        self._last_page = app.root.content.current
        Window.bind(children=self._update, size=self._update, on_resize=self._update)
        Metrics.bind(density=self._update, fontscale=self._update)
        app.bind(android_keyboard_height=self._update, safe_area_padding=self._update)
        app.root.content.bind(current=self._page_changed)
        self.size_controls(app.root)
        self._update()

    def _page_changed(self, _manager, page):
        if page != self._last_page:
            self._history.append(self._last_page)
            self._last_page = page

    def size_controls(self, root):
        target = self.app.touch_target
        for widget in root.walk():
            if not widget.opacity or not widget.height or not widget.width:
                continue
            if isinstance(widget, (ButtonBehavior, TextInput, Slider, Switch, SettingItem, TapBehavior)):
                widget.size_hint_min_x = max(widget.size_hint_min_x or 0, target)
                widget.size_hint_min_y = max(widget.size_hint_min_y or 0, target)
                if widget.size_hint_y is None and widget.height:
                    widget.height = max(widget.height, target)
                if widget.size_hint_x is None and widget.width:
                    widget.width = max(widget.width, target)
                if isinstance(widget, TextInput):
                    widget._mobile_text_sp = getattr(widget, "_mobile_text_sp", max(16, widget.font_size / sp(1)))
                    widget.font_size = sp(widget._mobile_text_sp)
                    if not getattr(widget, "_mobile_focus_bound", False):
                        widget.bind(focus=lambda field, focused: self.focus_field(field) if focused else None)
                        widget._mobile_focus_bound = True
                if isinstance(widget, Button) and widget.text:
                    widget._mobile_text_sp = getattr(widget, "_mobile_text_sp", max(16, widget.font_size / sp(1)))
                    widget.font_size = sp(widget._mobile_text_sp)
                    widget.text_size = (max(1, widget.width - dp(12)), None)
                    if not getattr(widget, "_mobile_wrap_bound", False):
                        widget.bind(width=lambda item, width: setattr(item, "text_size", (max(1, width - dp(12)), None)))
                        widget._mobile_wrap_bound = True
                    widget.halign = "center"
                    widget.valign = "middle"
            if isinstance(widget, TouchActionRow):
                widget._columns()
            elif isinstance(widget, GridLayout) and widget.row_force_default:
                widget.row_default_height = max(target, sp(16) * 2 + dp(16))
            if isinstance(widget, RecycleBoxLayout):
                width, height = widget.default_size
                if height is not None:
                    widget.default_size = (width, max(height, target))
            if isinstance(widget, Splitter):
                widget.strip_size = target
            if isinstance(widget, TabbedPanel):
                widget.tab_height = 0 if getattr(widget, "mobile_selector", None) is not None and self.app.compact_layout else max(widget.tab_height, target)
            if isinstance(widget, Label) and widget.text:
                widget._mobile_text_sp = getattr(widget, "_mobile_text_sp", max(16, widget.font_size / sp(1)))
                widget.font_size = sp(widget._mobile_text_sp)

    def _prepare_dialog(self, modal):
        from .mobile_tools import prepare_tool_dialog

        prepare_tool_dialog(modal, self.app)
        self.size_controls(modal)
        state = {"size_hint_y": modal.size_hint_y, "height": modal.height, "pos_hint": dict(modal.pos_hint)}
        self.dialogs[modal] = state
        jog_panel = modal.ids.get("jog_panel")
        if jog_panel is not None and type(modal).__name__ != "ProbingPopup":
            state["jog_panel"] = (jog_panel, jog_panel.height)
        state["drafts"] = {}
        def remember_drafts(_dt):
            if modal.__class__.__name__ in ("SetXPopup", "SetYPopup", "SetZPopup", "SetAPopup",
                                            "MoveAPopup", "SetToolPopup", "ChangeToolPopup", "WCSSettingsPopup"):
                state["drafts"] = {field: field.text for field in modal.walk() if isinstance(field, TextInput)
                                   and not getattr(field, "saves_immediately", False)}
        Clock.schedule_once(remember_drafts, 0.2)
        content = modal.content if isinstance(modal, Popup) else next(iter(modal.children), None)
        surfaces = [w for w in modal.walk() if isinstance(w, DialogSurface)]
        if surfaces:
            for surface in surfaces:
                surface.prepare()
            state["managed"] = True
            return
        # Existing tabbed and split-pane forms own their scrolling.

    def update(self, _dt=0):
        self.size_controls(self.app.root)
        keyboard = self.app.android_keyboard_height
        available = max(dp(96), Window.height - keyboard)
        self.app.root.size_hint = (None, None)
        self.app.root.pos = (0, keyboard)
        self.app.root.size = (Window.width, available)
        text_scale = max(1, Metrics.fontscale)
        self.app.compact_layout = Window.width / dp(1) / text_scale < 960 or available / dp(1) / text_scale < 560
        for modal in list(Window.children):
            if not isinstance(modal, ModalView):
                continue
            if modal not in self.dialogs:
                self._prepare_dialog(modal)
                Clock.schedule_once(lambda _dt, modal=modal: self.size_controls(modal), 0.1)
            state = self.dialogs[modal]
            self.size_controls(modal)
            if "jog_panel" in state:
                panel, height = state["jog_panel"]
                if keyboard and panel.height:
                    from .touch import cancel_jog

                    cancel_jog()
                panel.height = 0 if keyboard else height
                panel.opacity = 0 if keyboard else 1
                panel.disabled = bool(keyboard)
            # ModalView adds another fbind on every open, including reused dialogs.
            for name in ("center", "size"):
                for callback in modal.get_property_observers(name):
                    if callback == modal._align_center:
                        modal.funbind(name, callback)
            Window.unbind(on_resize=modal._align_center, on_keyboard=modal._handle_keyboard)
            modal.size_hint_y = None
            desired = state["height"] if state["size_hint_y"] is None else Window.height * state["size_hint_y"]
            if state.get("managed"):
                modal.size_hint_x = None
                modal.width = min(Window.width - dp(16), max(dp(560), Window.width * .85))
                desired = max(desired, min(dp(480), Window.height * .9))
            modal.height = max(dp(80), min(desired, available - dp(16)))
            modal.pos_hint = {}
            modal.center = (Window.width / 2, keyboard + available / 2)

    def focus_field(self, field):
        def reveal(_dt):
            if not field.focus or field.get_root_window() is None:
                return
            parent = field.parent
            while parent is not None and parent is not Window:
                if isinstance(parent, ScrollView):
                    parent.scroll_to(field, padding=dp(12), animate=False)
                parent = parent.parent
        Clock.schedule_once(reveal, 0.15)
        Clock.schedule_once(reveal, 0.35)

    def back(self):
        if self.app.android_keyboard_height:
            Window.release_all_keyboards()
            return True
        modals = [child for child in Window.children if isinstance(child, ModalView)]
        if modals:
            modal = modals[0]
            root = self.app.root
            if modal is getattr(root, "progress_popup", None) or getattr(modal, "is_probing", False):
                return True
            if self.app.playing or self.app.state not in ("Idle", "N/A", "Sleep", "Alarm"):
                return True
            # Each form retains its own apply/discard and operation-cancellation policy.
            drafts = self.dialogs.get(modal, {}).get("drafts", {})
            if any(field.text != original for field, original in drafts.items()):
                self._confirm_discard(modal, drafts)
                return True
            modal.dismiss()
            return True
        if self.app.playing or self.app.state not in ("Idle", "N/A", "Sleep", "Alarm"):
            return True
        if self._history:
            page = self._history.pop()
            self._last_page = page
            self.app.root.content.current = page
            return True
        confirm = self.app.root.confirm_popup
        confirm.lb_title.text = tr._("Exit controller?")
        confirm.lb_content.text = tr._("Close the controller application?")
        confirm.confirm = lambda *_: self.app.stop()
        confirm.cancel = None
        confirm.open()
        return True

    def _confirm_discard(self, modal, drafts):
        actions = BoxLayout(spacing=dp(8))
        prompt = Popup(title=tr._("Discard unapplied edits?"), content=actions,
                       size_hint=(0.7, None), height=dp(160), auto_dismiss=False)
        keep = Button(text=tr._("Keep editing"))
        discard = Button(text=tr._("Discard"))
        keep.bind(on_release=lambda *_: prompt.dismiss())
        def discard_edits(*_args):
            for field, original in drafts.items():
                field.text = original
            prompt.dismiss()
            modal.dismiss()
        discard.bind(on_release=discard_edits)
        actions.add_widget(keep)
        actions.add_widget(discard)
        prompt.open()

    def show_help(self, source=None):
        modals = [child for child in Window.children if isinstance(child, ModalView)]
        source = source or (modals[0] if modals else self.app.root)
        entries = []
        seen = set()
        for widget in source.walk():
            text = getattr(widget, "tooltip_txt", "")
            image = getattr(widget, "tooltip_image", "")
            key = (text, image)
            if (not text and not image) or key in seen or not widget.opacity or not widget.width or not widget.height:
                continue
            seen.add(key)
            entries.append((getattr(widget, "text", ""), text, image))
        listing = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(12), padding=dp(12))
        listing.bind(minimum_height=listing.setter("height"))
        for title, text, image in entries:
            label = Label(text=(title + "\n" if title else "") + text, size_hint_y=None,
                          text_size=(None, None), halign="left", valign="top", font_size=sp(16))
            label.bind(width=lambda item, width: setattr(item, "text_size", (width, None)))
            label.bind(texture_size=lambda item, size: setattr(item, "height", size[1] + dp(12)))
            listing.add_widget(label)
            if image:
                listing.add_widget(Image(source=image, size_hint_y=None, height=dp(180), fit_mode="contain"))
        if not entries:
            listing.add_widget(Label(text=tr._("No additional help for this screen."), size_hint_y=None, height=dp(48)))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(listing)
        Popup(title=tr._("Control help"), content=scroll, size_hint=(0.8, 0.85)).open()

    def stop(self):
        self._update.cancel()
        Window.unbind(children=self._update, size=self._update, on_resize=self._update)
        Metrics.unbind(density=self._update, fontscale=self._update)
        self.app.unbind(android_keyboard_height=self._update, safe_area_padding=self._update)
        self.app.root.content.unbind(current=self._page_changed)
