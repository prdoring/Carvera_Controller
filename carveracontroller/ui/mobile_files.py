"""File actions and destinations with the existing controller callbacks."""

from kivy.app import App
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import Metrics, dp, sp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner

from carveracontroller import Utils
from carveracontroller.translation import tr

from .android_layout import (
    DialogActions,
    DialogLabel,
    DialogSurface,
    TouchActionRow,
    _text_width,
    control_height,
    style_action,
)


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
    pages = {}
    for name, proxy in (("remote", popup.remote_rv), ("local", popup.local_rv)):
        rv = next(child for child in proxy.parent.children if child == proxy)
        pages[name] = {"rv": rv}
    sources = []
    for name, header, title in (("remote", remote, tr._("On the mill")), ("local", popup.ids.local_file_header, tr._("On this device"))):
        pages[name]["header"] = header
        pages[name]["directories"] = next(child for child in header.children if isinstance(child, BoxLayout)
                                          and any(hasattr(item, "data_text") for item in child.children))
        for child in header.children:
            if isinstance(child, Label) and not isinstance(child, ButtonBehavior) and child.text:
                index = header.children.index(child)
                header.remove_widget(child)
                source = Spinner(text=title, values=(tr._("On this device"), tr._("On the mill")), size_hint_x=.45)
                header.add_widget(source, index=index)
                sources.append(source)
                pages[name]["source"] = source
                def choose(_widget, text):
                    target = "local_page" if text == tr._("On this device") else "remote_page"
                    if popup.popup_manager.current != target:
                        if target == "local_page":
                            app.root.open_upload_local_file_popup()
                        else:
                            popup.load_remote_page()
                source.bind(text=choose)
                break
        for child in list(header.children):
            if type(child) is Label and not child.text:
                header.remove_widget(child)
            elif isinstance(child, BoxLayout) and any(hasattr(item, "data_text") for item in child.children):
                child.size_hint_x = .28
        header.height = control_height()
    def sync_source(_manager, page):
        for source in sources:
            source.text = tr._("On this device") if page == "local_page" else tr._("On the mill")
    popup.popup_manager.bind(current=sync_source)
    actions = [child for child in reversed(remote.children) if isinstance(child, Button) and not isinstance(child, Spinner)]
    for child in actions:
        remote.remove_widget(child)
        child.size_hint = (1, None)
        child.height = dp(56)
        child.bind(on_release=lambda *_: popup._file_action_sheet.dismiss())
    menu = Button(text=tr._("File actions"), size_hint_x=None, width=dp(144))
    remote.add_widget(menu)

    def show_actions(items, title):
        surface = DialogSurface(orientation="vertical", padding=dp(12), spacing=dp(8))
        for child in items:
            if not child.opacity:
                continue
            if child.parent is not None:
                child.parent.remove_widget(child)
            surface.add_widget(child)
        footer = DialogActions()
        close = Button(text=tr._("Close"))
        footer.add_widget(close)
        surface.add_widget(footer)
        sheet = Popup(title=title, content=surface, size_hint=(.85, .85))
        popup._file_action_sheet = sheet
        close.bind(on_release=lambda *_: sheet.dismiss())
        sheet.open()
    menu.bind(on_release=lambda *_: show_actions(actions, tr._("Mill file actions")))
    local_actions = [child for child in reversed(local.children) if isinstance(child, Button)]
    row = TouchActionRow(spacing=dp(6))
    for child in local_actions:
        local.remove_widget(child)
        child.size_hint_x = 1
        row.add_widget(child)
    popup.btn_view.text = tr._("Preview")
    popup.ids.btn_upload_and_select.text = tr._("Upload and Select")
    style_action(popup.btn_view, "primary")
    local.parent.add_widget(row, index=0)
    pages["local"]["footer"] = row
    pages["remote"]["menu"] = menu

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
        pages["remote" if rv == popup.remote_rv else "local"]["status"] = status

    for rv, search in ((popup.remote_rv, popup.ti_remote_search), (popup.local_rv, popup.ti_local_search)):
        row = search.parent.parent
        crumbs = [w for w in row.children if w.__class__.__name__ in ("LinkButton", "ButtonLabel")]
        if not crumbs:
            continue
        for crumb in crumbs:
            row.remove_widget(crumb)
        for placeholder in list(row.children):
            if type(placeholder) is Label and not placeholder.text:
                row.remove_widget(placeholder)
        old_search = search.parent
        search = next(child for child in old_search.children if child == search)
        old_search.remove_widget(search)
        row.remove_widget(old_search)
        search.size_hint = (1, 1)
        search.pos_hint = {}
        search.foreground_color = (.95, .95, .95, 1)
        search.background_normal = ""
        search.background_active = ""
        search.background_color = (.2, .2, .2, 1)
        search.hint_text_color = (.72, .72, .72, 1)
        search.cursor_color = (.95, .95, .95, 1)
        row.height = control_height()
        search_bar = BoxLayout(spacing=dp(6), size_hint_x=.5)
        search_bar.add_widget(search)
        clear = Button(text=tr._("Clear"), size_hint_x=None, width=max(dp(72), sp(16)*3.5))
        clear.bind(on_release=lambda _button, field=search: setattr(field, "text", ""))
        search_bar.add_widget(clear)
        row.add_widget(search_bar)
        path = Button(text=rv.curr_dir, shorten=True)
        path.bind(size=lambda item, size: setattr(item, "text_size", (max(1, size[0] - dp(16)), None)))
        rv.bind(curr_path_list=lambda _rv, _paths, item=path, view=rv: setattr(item, "text", view.curr_dir))
        row.add_widget(path, index=1)
        def show_path(_button, view=rv):
            surface = DialogSurface(orientation="vertical", padding=dp(12))
            folder_label = DialogLabel(text=view.curr_dir)
            surface.add_widget(folder_label)
            selected_label = DialogLabel(text=tr._("Selected file") + ":\n" + view.curr_selected_file if view.curr_selected_file else "")
            surface.add_widget(selected_label)
            controls = pages["remote" if view == popup.remote_rv else "local"]["directories"]
            if controls.parent is not None:
                controls.parent.remove_widget(controls)
            controls.size_hint = (1, None)
            controls.height = control_height()
            controls.padding = 0
            surface.add_widget(controls)
            actions = DialogActions()
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
            def folder_changed(_view, folder, label=folder_label):
                label.text = folder
            def selected_changed(_view, filename, label=selected_label):
                label.text = tr._("Selected file") + ":\n" + filename if filename else ""
            view.bind(curr_dir=folder_changed)
            view.bind(curr_selected_file=selected_changed)
            dialog.bind(on_dismiss=lambda *_: app.unbind(on_resume=resume))
            dialog.bind(on_dismiss=lambda *_: view.unbind(curr_dir=folder_changed))
            dialog.bind(on_dismiss=lambda *_: view.unbind(curr_selected_file=selected_changed))
            dialog.open()
        path.bind(on_release=show_path)
        page = pages["remote" if rv == popup.remote_rv else "local"]
        page.update(path_row=row, path=path, search=search, search_bar=search_bar, clear=clear)

    _finish_file_layout(popup, pages, actions, local_actions, show_actions)


def _finish_file_layout(popup, pages, remote_actions, local_actions, show_actions):
    app = App.get_running_app()
    popup._mobile_file_pages = pages
    popup._mobile_search_sheets = {}
    popup._mobile_search_buttons = {}
    remote_footer = popup.ids.btn_select.parent
    open_button = next(child for child in remote_footer.children if child == popup.ids.btn_select)
    close_button = next(child for child in remote_footer.children if getattr(child, "text", "") == tr._("Close"))
    clear_job = next(child for child in remote_footer.children if child not in (open_button, close_button))
    clear_job.text = tr._("Clear current job")
    clear_job.bind(on_release=lambda *_: popup._file_action_sheet.dismiss())
    remote_actions.append(clear_job)
    selection = popup.ids.remote_selection_bar
    mode_button = next(child for child in selection.children if isinstance(child, Button))
    counter = next(child for child in selection.children if type(child) is Label)
    selection.remove_widget(mode_button)
    selection.remove_widget(counter)
    selection.parent.remove_widget(selection)
    Builder.unbind_property(mode_button, "text")
    footer_index = remote_footer.parent.children.index(remote_footer)
    parent = remote_footer.parent
    remote_footer.clear_widgets()
    parent.remove_widget(remote_footer)
    footer = TouchActionRow(spacing=dp(6))
    for button in (close_button, mode_button, open_button):
        button.size_hint = (1, 1)
        footer.add_widget(button)
    parent.add_widget(footer, index=footer_index)
    pages["remote"].update(footer=footer, mode=mode_button, counter=counter)
    local_footer = pages["local"]["footer"]
    local_footer.clear_widgets()
    close = Button(text=tr._("Close"))
    close.bind(on_release=lambda *_: popup.dismiss())
    local_footer.add_widget(close)
    for button in local_actions:
        if button == popup.btn_view or button == popup.ids.btn_upload:
            button.size_hint = (1, 1)
            local_footer.add_widget(button)
    local_menu_actions = [button for button in local_actions if button == popup.ids.btn_upload_and_select]
    local_menu_actions[0].bind(on_release=lambda *_: popup._file_action_sheet.dismiss())

    for name, page in pages.items():
        rv, header, source = page["rv"], page["header"], page["source"]
        columns = popup.ids[name + "_file_columns"]
        columns = next(child for child in columns.parent.children if child == columns)
        columns.parent.remove_widget(columns)
        page["columns"] = columns
        items = remote_actions if name == "remote" else local_menu_actions
        for label in reversed(columns.children):
            button = Button(text=tr._("Sort by") + ": " + label.text.strip(), size_hint_y=None)
            def sort_caption(_label, text, target=button):
                target.text = tr._("Sort by") + ": " + text.strip()
            label.bind(text=sort_caption)
            def sort(_button, original=label):
                popup._file_action_sheet.dismiss()
                original.dispatch("on_release")
            button.bind(on_release=sort)
            items.append(button)
        menu = page.get("menu") or Button()
        menu.text = tr._("Actions")
        menu.size_hint_x = None
        if name == "local":
            menu.bind(on_release=lambda *_: show_actions(local_menu_actions, tr._("Device file actions")))
        header.clear_widgets()
        source.size_hint_x = 1
        source.shorten = True
        header.add_widget(source)
        if name == "remote":
            counter.size_hint_x = None
            counter.font_size = sp(14)
            header.add_widget(counter)
        header.add_widget(menu)
        Builder.unbind_property(header, "height")
        header._mobile_keyboard_secondary = True
        page["menu"] = menu

        status = page["status"]
        status.parent.remove_widget(status)
        parent = rv.parent
        index = parent.children.index(rv)
        parent.remove_widget(rv)
        body = BoxLayout(orientation="vertical")
        info = ScrollView(do_scroll_x=False)
        info.add_widget(status)
        body.add_widget(rv)
        body.add_widget(info)
        parent.add_widget(body, index=index)
        page.update(body=body, info=info)
        def state(_widget, value, page=page):
            visible = bool(value)
            page["info"].size_hint_y = 1 if visible else None
            page["info"].height = 0
            page["info"].opacity = int(visible)
            page["info"].disabled = not visible
            page["rv"].size_hint_y = None if visible else 1
            page["rv"].height = 0
            page["rv"].opacity = int(not visible)
        rv.bind(browser_state=state)
        state(rv, rv.browser_state)

        search, clear = page["search"], page["clear"]
        page["search_bar"].remove_widget(search)
        page["search_bar"].remove_widget(clear)
        page["path_row"].remove_widget(page["search_bar"])
        page["path_row"]._mobile_keyboard_secondary = True
        Builder.unbind_property(page["path_row"], "height")
        search.size_hint = (1, None)
        search.input_policy = "filename"
        surface = DialogSurface(orientation="vertical", padding=dp(12))
        surface.add_widget(search)
        actions = DialogActions(spacing=dp(8))
        done = Button(text=tr._("Done"))
        style_action(done, "primary")
        actions.add_widget(clear)
        actions.add_widget(done)
        surface.add_widget(actions)
        sheet = Popup(title=tr._("Search filenames"), content=surface, auto_dismiss=False)
        sheet.bind(on_dismiss=lambda *_args, field=search: setattr(field, "focus", False))
        popup.bind(on_dismiss=lambda *_args, child=sheet: child.dismiss())
        done.bind(on_release=lambda *_args, child=sheet: child.dismiss())
        launch = Button(size_hint_x=None, disabled=search.disabled)
        search.bind(disabled=lambda _field, value, button=launch: setattr(button, "disabled", value))
        def open_search(*_args, child=sheet, field=search):
            child.open()
            field.focus = True
        launch.bind(on_release=open_search)
        def filtered(_field, text, button=launch):
            button.text = tr._("Filter") if text else tr._("Search")
            style_action(button, "primary" if text else "secondary")
        search.bind(text=filtered)
        filtered(search, search.text)
        page["path_row"].add_widget(launch)
        popup._mobile_search_sheets[name] = sheet
        popup._mobile_search_buttons[name] = launch
        page["search_button"] = launch

        def reflow(*_args, page=page):
            page["header"].height = page["path_row"].height = control_height()
            page["header"].spacing = page["path_row"].spacing = dp(6)
            page["path_row"].padding = 0
            page["footer"].spacing = dp(6)
            page["search"].height = control_height()
            for button in (page["menu"], page["search_button"]):
                button.width = max(app.touch_target, _text_width(button.text, button.font_name, sp(16)) + dp(24))
            page["rv"].layout_manager.default_size = (None, max(dp(72), sp(16) * 2.6 + dp(16)))
            if "counter" in page:
                selecting = page["rv"].touch_selection_mode
                page["mode"].text = tr._("Done") if selecting else tr._("Select")
                page["counter"].width = _text_width(page["counter"].text, page["counter"].font_name, sp(14)) + dp(12) if selecting else 0
                page["counter"].opacity = int(selecting)
        rv.bind(touch_selection_mode=reflow, curr_selected_files=reflow)
        if "counter" in page:
            page["counter"].bind(text=reflow)
        launch.bind(text=reflow)
        Metrics.bind(density=reflow, fontscale=reflow)
        app.bind(touch_target=reflow)
        header.bind(width=reflow)
        reflow()
