"""File actions and destinations with the existing controller callbacks."""

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup

from carveracontroller import Utils
from carveracontroller.translation import tr

from .android_layout import DialogLabel, DialogSurface, TouchActionRow


def prepare_file_browser(popup):
    if getattr(popup, "_mobile_files_ready", False):
        return
    popup._mobile_files_ready = True
    def connection_state(_app, state):
        if state in ("N/A", "Wait"):
            popup.remote_rv.directory_failed(tr._("Mill disconnected. Connect, then retry this folder."))
    app = App.get_running_app()
    app.bind(state=connection_state)
    connection_state(app, app.state)
    remote = popup.btn_rename.parent
    local = popup.btn_view.parent
    for header, title in ((remote, tr._("On the mill")), (local, tr._("On this device"))):
        for child in header.children:
            if isinstance(child, Label) and not isinstance(child, ButtonBehavior) and child.text:
                child.text = title
                child.size_hint_x = 1
                break
    actions = [child for child in reversed(remote.children) if isinstance(child, Button)]
    for child in actions:
        remote.remove_widget(child)
        child.size_hint = (1, None)
        child.height = dp(56)
        child.bind(on_release=lambda *_: popup._file_action_sheet.dismiss())
    menu = Button(text=tr._("File actions"), size_hint_x=None, width=dp(144))
    remote.add_widget(menu)

    def show_actions(*_args):
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        surface.add_widget(DialogLabel(text=tr._("Files on the mill"), bold=True))
        for child in actions:
            if child.parent is not None:
                child.parent.remove_widget(child)
            surface.add_widget(child)
        footer = TouchActionRow()
        close = Button(text=tr._("Close"))
        footer.add_widget(close)
        surface.add_widget(footer)
        sheet = Popup(title=tr._("File actions"), content=surface, size_hint=(.85, .85))
        popup._file_action_sheet = sheet
        close.bind(on_release=lambda *_: sheet.dismiss())
        sheet.open()
    menu.bind(on_release=show_actions)
    local_actions = [child for child in reversed(local.children) if isinstance(child, Button)]
    row = TouchActionRow(spacing=dp(6))
    for child in local_actions:
        local.remove_widget(child)
        child.size_hint_x = 1
        row.add_widget(child)
    popup.btn_view.text = tr._("Preview")
    popup.ids.btn_upload_and_select.text = tr._("Upload and Select")
    local.parent.add_widget(row, index=0)

    for rv in (popup.remote_rv, popup.local_rv):
        rv.layout_manager.default_size = (None, max(dp(72), sp(16) * 2 + dp(20)))
        status = DialogLabel(text=rv.browser_state)
        status.height = 0
        def refresh(_widget, value, label=status):
            label.text = value
            label.height = max(dp(48), label.texture_size[1] + dp(12)) if value else 0
        rv.bind(browser_state=refresh)
        rv.parent.add_widget(status, index=rv.parent.children.index(rv) + 1)
        refresh(rv, rv.browser_state)

    for rv, search in ((popup.remote_rv, popup.ti_remote_search), (popup.local_rv, popup.ti_local_search)):
        row = search.parent.parent
        crumbs = [w for w in row.children if w.__class__.__name__ == "LinkButton"]
        if not crumbs:
            continue
        for crumb in crumbs:
            row.remove_widget(crumb)
        path = Button(text=rv.curr_dir, shorten=True)
        path.bind(size=lambda item, size: setattr(item, "text_size", (max(1, size[0] - dp(16)), None)))
        rv.bind(curr_path_list=lambda _rv, _paths, item=path, view=rv: setattr(item, "text", view.curr_dir))
        row.add_widget(path, index=1)
        def show_path(_button, view=rv):
            surface = DialogSurface(orientation="vertical", padding=dp(12))
            surface.add_widget(DialogLabel(text=view.curr_dir))
            actions = TouchActionRow()
            up, close = Button(text=tr._("Parent folder")), Button(text=tr._("Close"))
            actions.add_widget(up)
            retry = Button(text=tr._("Retry folder"))
            actions.add_widget(retry)
            retry.bind(on_release=lambda *_: view.list_dir())
            if view is popup.local_rv:
                status = DialogLabel(text=tr._("Storage access is granted.") if Utils.has_all_files_access()
                                     else tr._("To use shared folders, grant storage access, then retry. Your folder and selection stay here."))
                surface.add_widget(status)
                grant = Button(text=tr._("Grant access"))
                actions.add_widget(grant)
                grant.bind(on_release=lambda *_: (Window.release_all_keyboards(), Utils.request_android_permissions()))
            actions.add_widget(close)
            surface.add_widget(actions)
            dialog = Popup(title=tr._("Current folder"), content=surface, size_hint=(.9, .8))
            up.bind(on_release=lambda *_: (dialog.dismiss(), view.parent_dir()))
            close.bind(on_release=lambda *_: dialog.dismiss())
            def resume(*_args):
                if view is popup.local_rv:
                    status.text = tr._("Storage access is granted. Retry the folder.") if Utils.has_all_files_access() else tr._("Storage access is still denied. Grant access or choose another folder.")
            app = App.get_running_app()
            app.bind(on_resume=resume)
            dialog.bind(on_dismiss=lambda *_: app.unbind(on_resume=resume))
            dialog.open()
        path.bind(on_release=show_path)
