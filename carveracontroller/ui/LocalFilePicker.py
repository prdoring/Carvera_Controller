"""Reusable local folder + file name picker (load/save dialogs)."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.properties import ListProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.dropdown import DropDown
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.utils import platform

from carveracontroller import Utils
from carveracontroller.translation import tr

from .android_layout import DialogActions, DialogLabel, DialogSurface, TouchActionRow, style_action
from .touch import Gesture


class TouchFileChooserListView(FileChooserListView):
    def entry_touched(self, entry, touch):
        if platform != "android":
            return super().entry_touched(entry, touch)
        if not getattr(touch, "is_mouse_scrolling", False):
            touch.ud[self] = (entry, entry.path, Gesture(touch))

    def entry_released(self, entry, touch):
        if platform != "android":
            return super().entry_released(entry, touch)
        candidate = touch.ud.pop(self, None)
        if candidate is None:
            return None
        original, path, gesture = candidate
        if not gesture.finish() or original is not entry or path != entry.path:
            return None
        if self.file_system.is_dir(path):
            self.open_entry(entry)
        else:
            super().entry_touched(entry, touch)


class LocalFilePickerDirButton(ButtonBehavior, BoxLayout):
    """Compact folder shortcut button (common/recent places dropdown)."""

    data_text = StringProperty("")


class LocalFilePickerSheet(BoxLayout):
    """Folder browser with breadcrumb path bar and file name field."""

    curr_path_list = ListProperty([])
    curr_dir_name = StringProperty("")
    storage_status = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.curr_full_path_list: list[str] = []
        self._common_dirs: list[dict] = []
        self._recent_dirs: list[str] = []
        self._dir_dropdown = DropDown(auto_width=False, width="190dp")
        self._dir_dropdown.bind(on_select=self._on_dir_dropdown_select)

    def on_kv_post(self, base_widget):
        super().on_kv_post(base_widget)
        if platform == "android":
            App.get_running_app().bind(on_resume=self._resume_storage)
            self._refresh_storage_status()

    def _refresh_storage_status(self, *_args):
        self.storage_status = tr._("Storage access is available") if Utils.has_all_files_access() else tr._("Some folders need storage access. Your file name and folder stay here while you grant access.")

    def show_folder_path(self):
        surface = DialogSurface(orientation="vertical", padding="12dp", spacing="8dp")
        surface.add_widget(DialogLabel(text=self.ids.fc.path))
        actions = DialogActions()
        up, close = Button(text=tr._("Parent folder")), Button(text=tr._("Close"))
        actions.add_widget(up)
        actions.add_widget(close)
        surface.add_widget(actions)
        popup = Popup(title=tr._("Current folder"), content=surface, size_hint=(.9, .75))
        up.bind(on_release=lambda *_: (setattr(self.ids.fc, "path", os.path.dirname(self.ids.fc.path)), popup.dismiss()))
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def show_storage_access(self):
        self._refresh_storage_status()
        surface = DialogSurface(orientation="vertical", padding="12dp", spacing="8dp")
        label = DialogLabel(text=self.storage_status)
        self.bind(storage_status=lambda _widget, text: setattr(label, "text", text))
        surface.add_widget(label)
        actions = DialogActions()
        grant, retry, close = (Button(text=tr._(text)) for text in ("Grant access", "Retry folder", "Close"))
        for button in (grant, retry, close):
            actions.add_widget(button)
        surface.add_widget(actions)
        popup = Popup(title=tr._("Storage access"), content=surface, size_hint=(.9, .75))
        grant.bind(on_release=lambda *_: self.request_storage())
        style_action(grant, "primary")
        retry.bind(on_release=lambda *_: self.retry_storage())
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def request_storage(self):
        Window.release_all_keyboards()
        Utils.request_android_permissions()

    def retry_storage(self):
        self._refresh_storage_status()
        self.ids.fc._update_files()

    def _resume_storage(self, *_args):
        if self.get_root_window() is not None:
            Clock.schedule_once(lambda _dt: self.retry_storage(), .1)

    def _on_dir_dropdown_select(self, _dropdown, path: str) -> None:
        self.ids.fc.path = path

    def open_dir_dropdown(self, button) -> None:
        if not self._common_dirs:
            self._common_dirs = Utils.common_local_directories()
        self._recent_dirs = Utils.load_recent_local_directories(
            seed_if_empty=not self._recent_dirs,
        )
        Utils.fill_local_dir_dropdown(self._dir_dropdown, self._common_dirs, self._recent_dirs)
        self._dir_dropdown.open(button)

    def update_from_directory(self, directory: str) -> None:
        full_paths, path_labels = Utils.directory_breadcrumb_paths(directory)
        self.curr_full_path_list = full_paths
        self.curr_path_list = path_labels
        self.curr_dir_name = tr._("Controller files") if platform == "android" and directory == home_directory() else path_labels[-1] if path_labels else ""

    def goto_path(self, index: int) -> None:
        if index < len(self.curr_full_path_list):
            self.ids.fc.path = self.curr_full_path_list[index]


if "LocalFilePickerDirButton" not in Factory.classes:
    Factory.register("LocalFilePickerDirButton", cls=LocalFilePickerDirButton)

if "LocalFilePickerSheet" not in Factory.classes:
    Factory.register("LocalFilePickerSheet", cls=LocalFilePickerSheet)


def home_directory() -> str:
    if platform == "android":
        app = App.get_running_app()
        folder = os.path.join(app.user_data_dir, "exports")
        os.makedirs(folder, exist_ok=True)
        return folder
    try:
        home = os.path.expanduser("~")
        return home if os.path.isdir(home) else os.getcwd()
    except Exception:
        return "/"


def confirm_overwrite_then(dest: str, write_fn: Callable[[str], None]) -> None:
    """Ask to replace an existing file, then call write_fn(dest)."""
    root = App.get_running_app().root
    if os.path.isfile(dest):
        cp = root.confirm_popup
        cp.lb_title.text = tr._("Overwrite file?")
        cp.lb_content.text = tr._("Replace existing file?\n%s") % dest
        cp.confirm = lambda: write_fn(dest)
        cp.cancel = None
        cp.open(root)
    else:
        write_fn(dest)


def open_local_file_picker(
    *,
    title: str,
    default_name: str,
    on_confirm: Callable[[Popup, str], None],
    confirm_label: str | None = None,
    size_hint: tuple[float, float] = (0.82, 0.82),
    filters: Sequence[str] | None = None,
) -> None:
    """Open a popup to pick a folder and file name; on_confirm receives (popup, full_path)."""
    root = App.get_running_app().root
    try:
        content = Factory.LocalFilePickerSheet()
    except KeyError:
        if hasattr(root, "show_message_popup"):
            root.show_message_popup(tr._("Dialog unavailable (UI not loaded)."), False)
        return

    fc = content.ids.fc
    ti = content.ids.ti_filename
    fc.path = home_directory()
    fc.filters = list(filters) if filters else []
    ti.text = default_name

    def sync_path(_inst, path):
        content.update_from_directory(path or "")

    sync_path(fc, fc.path)
    fc.bind(path=sync_path)

    def sync_filename_from_selection(_inst, sel):
        if not sel:
            return
        path = sel[0]
        try:
            if os.path.isfile(path):
                ti.text = os.path.basename(path)
        except OSError:
            pass

    fc.bind(selection=sync_filename_from_selection)
    popup = Popup(title=title, content=content, size_hint=size_hint, auto_dismiss=False)
    if platform == "android":
        style_action(content.ids.btn_confirm, "primary")
    if confirm_label:
        content.ids.btn_confirm.text = confirm_label

    def attempt(*_):
        raw_name = ti.text.strip()
        if not raw_name:
            root.show_message_popup(tr._("Enter a file name."), False)
            return
        fn = os.path.basename(raw_name)
        dd = fc.path
        if not dd or not os.path.isdir(dd):
            root.show_message_popup(tr._("Choose an existing folder."), False)
            return
        Utils.record_recent_local_directory(dd)
        on_confirm(popup, os.path.join(dd, fn))

    content.ids.btn_cancel.bind(on_release=lambda *_: popup.dismiss())
    content.ids.btn_confirm.bind(on_release=attempt)
    popup.open()
