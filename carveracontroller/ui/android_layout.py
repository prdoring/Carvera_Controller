"""Android touch sizing, keyboard space, help and Back navigation."""

import weakref

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
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
from kivy.uix.slider import Slider
from kivy.uix.splitter import Splitter
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.tabbedpanel import TabbedPanel
from kivy.uix.settings import SettingItem
from .touch import TapBehavior

from carveracontroller.translation import tr


class TouchActionRow(GridLayout):
    """Action buttons wrap into full touch rows on a narrow interface."""

    def __init__(self, **kwargs):
        kwargs.setdefault("rows", None)
        super().__init__(**kwargs)
        self.bind(width=self._columns, children=self._columns)
        self.bind(minimum_height=self.setter("height"))
        self.size_hint_y = None
        self._columns()

    def _columns(self, *_args):
        app = App.get_running_app()
        self.cols = max(1, min(len(self.children) or 1, int(self.width / dp(128)))) if app.android_touch else max(1, len(self.children))
        self.row_force_default = True
        self.row_default_height = app.touch_target if app.android_touch else dp(40)


class AndroidTouchLayout:
    def __init__(self, app):
        self.app = app
        self.dialogs = weakref.WeakKeyDictionary()
        self._update = Clock.create_trigger(self.update, 0)
        self._history = []
        self._last_page = app.root.content.current
        Window.bind(children=self._update, size=self._update)
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

    def _prepare_dialog(self, modal):
        self.size_controls(modal)
        state = dict(size_hint_y=modal.size_hint_y, height=modal.height, pos_hint=dict(modal.pos_hint))
        self.dialogs[modal] = state
        state["drafts"] = {}
        def remember_drafts(_dt):
            if modal.__class__.__name__ in ("SetXPopup", "SetYPopup", "SetZPopup", "SetAPopup",
                                            "MoveAPopup", "SetToolPopup", "ChangeToolPopup", "WCSSettingsPopup"):
                state["drafts"] = {field: field.text for field in modal.walk() if isinstance(field, TextInput)}
        Clock.schedule_once(remember_drafts, 0.2)
        content = modal.content if isinstance(modal, Popup) else next(iter(modal.children), None)
        if not (isinstance(content, BoxLayout) and content.orientation == "vertical"
                or isinstance(content, GridLayout) and content.cols == 1):
            return
        # Preserve existing field IDs and callbacks; only the containing viewport changes.
        body = BoxLayout(orientation="vertical", spacing=dp(8))
        actions = content.children[0] if content.children else None
        if (isinstance(actions, (BoxLayout, TouchActionRow)) and actions.size_hint_y is None
                and any(isinstance(child, ButtonBehavior) for child in actions.children)):
            content.remove_widget(actions)
        else:
            actions = None
        jog_panel = modal.ids.get("jog_panel")
        if jog_panel is not None and jog_panel.parent is content:
            content.remove_widget(jog_panel)
            state["jog_panel"] = (jog_panel, jog_panel.height)
        scroll = ScrollView(do_scroll_x=False)
        content.size_hint_y = None
        def fit_content(*_args):
            content.height = max(scroll.height, content.minimum_height)
        content.bind(minimum_height=fit_content)
        scroll.bind(height=fit_content)
        if isinstance(modal, Popup):
            modal.content = body
        else:
            modal.remove_widget(content)
            modal.add_widget(body)
        scroll.add_widget(content)
        body.add_widget(scroll)
        if "jog_panel" in state:
            body.add_widget(jog_panel)
        if actions is not None:
            footer = BoxLayout(size_hint_y=None, height=actions.height, spacing=dp(8))
            actions.bind(height=lambda _widget, height: setattr(footer, "height", height))
            footer.add_widget(actions)
            body.add_widget(footer)
        else:
            footer = BoxLayout(size_hint_y=None, height=self.app.touch_target)
            body.add_widget(footer)
        help_button = Button(text="?", size_hint_x=None, width=self.app.touch_target)
        help_button.bind(on_release=lambda *_: self.show_help(modal))
        footer.add_widget(help_button)
        fit_content()

    def update(self, _dt=0):
        keyboard = self.app.android_keyboard_height
        available = max(dp(96), Window.height - keyboard)
        self.app.root.size_hint = (None, None)
        self.app.root.pos = (0, keyboard)
        self.app.root.size = (Window.width, available)
        for modal in list(Window.children):
            if not isinstance(modal, ModalView):
                continue
            if modal not in self.dialogs:
                self._prepare_dialog(modal)
                Clock.schedule_once(lambda _dt, modal=modal: self.size_controls(modal), 0.1)
            state = self.dialogs[modal]
            if "jog_panel" in state:
                panel, height = state["jog_panel"]
                panel.height = 0 if keyboard else height
                panel.opacity = 0 if keyboard else 1
                panel.disabled = bool(keyboard)
            # ModalView otherwise forces its centre back to the full window on
            # every size change, including while the keyboard covers that area.
            modal.unbind(center=modal._align_center, size=modal._align_center)
            Window.unbind(on_keyboard=modal._handle_keyboard)
            if keyboard:
                state.setdefault("keyboard_center", tuple(modal.center))
                modal.size_hint_y = None
                desired = state["height"] if state["size_hint_y"] is None else Window.height * state["size_hint_y"]
                modal.height = min(desired, available - dp(8))
                modal.pos_hint = {"center_x": 0.5, "center_y": (keyboard + available / 2) / Window.height}
                modal.center = (Window.width / 2, keyboard + available / 2)
            else:
                modal.size_hint_y = state["size_hint_y"]
                if state["size_hint_y"] is None:
                    modal.height = state["height"]
                modal.pos_hint = dict(state["pos_hint"])
                if "keyboard_center" in state:
                    modal.center = state.pop("keyboard_center")

    def focus_field(self, field):
        def reveal(_dt):
            if not field.focus or field.get_root_window() is None:
                return
            parent = field.parent
            while parent is not None:
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
        Window.unbind(children=self._update, size=self._update)
        self.app.unbind(android_keyboard_height=self._update, safe_area_padding=self._update)
        self.app.root.content.unbind(current=self._page_changed)
