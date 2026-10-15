"""Android touch sizing, keyboard space, help and Back navigation."""

import weakref

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
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


class TouchActionRow(GridLayout):
    """Action buttons wrap into full touch rows on a narrow interface."""

    stacked = BooleanProperty(False)

    def __init__(self, **kwargs):
        kwargs.setdefault("rows", None)
        super().__init__(**kwargs)
        self.bind(width=self._columns, children=self._columns, stacked=self._columns)
        self.bind(minimum_height=self.setter("height"))
        self.size_hint_y = None
        self._columns()

    def _columns(self, *_args):
        app = App.get_running_app()
        mobile = app is not None and app.android_touch
        self.cols = (1 if self.stacked else max(1, min(len(self.children) or 1, int(self.width / dp(160))))) if mobile else max(1, len(self.children))
        self.row_force_default = True
        self.row_default_height = max(app.touch_target, sp(16) * 2 + dp(16)) if mobile else dp(40)
        if mobile:
            for child in self.children:
                if isinstance(child, Button):
                    child.font_size = sp(16)
                    child.text_size = (max(1, self.width / self.cols - dp(24)), None)
                    child.halign = "center"
                    child.valign = "middle"


class DialogLabel(Label):
    """Full wording that grows vertically instead of shrinking or clipping."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(width=self._fit, texture_size=self._fit)
        self._fit()

    def _fit(self, *_args):
        app = App.get_running_app()
        if app is not None and app.android_touch:
            self.size_hint_y = None
            self.font_size = sp(18 if self.bold else 16)
            self.text_size = (max(1, self.width - dp(16)), None)
            self.height = max(dp(48), self.texture_size[1] + dp(16))


class DialogSurface(BoxLayout):
    """An explicitly managed dialog with a content viewport and fixed footer."""

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
            content.add_widget(child)
        viewport.add_widget(content)
        self.add_widget(viewport)
        if footer is not None:
            self.add_widget(footer)


class AndroidTouchLayout:
    def __init__(self, app):
        self.app = app
        self.dialogs = weakref.WeakKeyDictionary()
        self._update = Clock.create_trigger(self.update, 0)
        self._history = []
        self._last_page = app.root.content.current
        Window.bind(children=self._update, size=self._update, on_resize=self._update)
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
            if isinstance(widget, (ButtonBehavior, TextInput, Slider, Switch, SettingItem, TapBehavior)):
                widget.size_hint_min_x = max(widget.size_hint_min_x or 0, target)
                widget.size_hint_min_y = max(widget.size_hint_min_y or 0, target)
                if widget.size_hint_y is None and widget.height:
                    widget.height = max(widget.height, target)
                if widget.size_hint_x is None and widget.width:
                    widget.width = max(widget.width, target)
                if isinstance(widget, TextInput):
                    widget.font_size = max(widget.font_size, sp(16))
            if isinstance(widget, GridLayout) and widget.row_force_default:
                widget.row_default_height = max(widget.row_default_height, target)
            if isinstance(widget, RecycleBoxLayout):
                width, height = widget.default_size
                if height is not None:
                    widget.default_size = (width, max(height, target))
            if isinstance(widget, Splitter):
                widget.strip_size = target
            if isinstance(widget, TabbedPanel):
                widget.tab_height = max(widget.tab_height, target)
            if isinstance(widget, Label) and widget.text:
                widget.font_size = max(widget.font_size, sp(16))

    def _prepare_dialog(self, modal):
        self.size_controls(modal)
        state = {"size_hint_y": modal.size_hint_y, "height": modal.height, "pos_hint": dict(modal.pos_hint)}
        self.dialogs[modal] = state
        jog_panel = modal.ids.get("jog_panel")
        if jog_panel is not None:
            state["jog_panel"] = (jog_panel, jog_panel.height)
        state["drafts"] = {}
        def remember_drafts(_dt):
            if modal.__class__.__name__ in ("SetXPopup", "SetYPopup", "SetZPopup", "SetAPopup",
                                            "MoveAPopup", "SetToolPopup", "ChangeToolPopup", "WCSSettingsPopup"):
                state["drafts"] = {field: field.text for field in modal.walk() if isinstance(field, TextInput)
                                   and not getattr(field, "saves_immediately", False)}
        Clock.schedule_once(remember_drafts, 0.2)
        content = modal.content if isinstance(modal, Popup) else next(iter(modal.children), None)
        if isinstance(content, DialogSurface):
            content.prepare()
            state["managed"] = True
            return
        # Existing tabbed and split-pane forms own their scrolling.

    def update(self, _dt=0):
        keyboard = self.app.android_keyboard_height
        available = max(dp(96), Window.height - keyboard)
        self.app.root.size_hint = (None, None)
        self.app.root.pos = (0, keyboard)
        self.app.root.size = (Window.width, available)
        self.app.compact_layout = Window.width / dp(1) < 960 or available / dp(1) < 560
        for modal in list(Window.children):
            if not isinstance(modal, ModalView):
                continue
            if modal not in self.dialogs:
                self._prepare_dialog(modal)
                Clock.schedule_once(lambda _dt, modal=modal: self.size_controls(modal), 0.1)
            state = self.dialogs[modal]
            if "jog_panel" in state:
                panel, height = state["jog_panel"]
                if keyboard and panel.height:
                    from .touch import cancel_jog

                    cancel_jog()
                panel.height = 0 if keyboard else height
                panel.opacity = 0 if keyboard else 1
                panel.disabled = bool(keyboard)
            modal.unbind(center=modal._align_center, size=modal._align_center)
            Window.unbind(on_keyboard=modal._handle_keyboard)
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
        self.app.unbind(android_keyboard_height=self._update, safe_area_padding=self._update)
        self.app.root.content.unbind(current=self._page_changed)

