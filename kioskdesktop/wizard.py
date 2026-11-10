"""Graphical card installation and verified first-boot handoff."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import subprocess
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from kioskdesktop import devices, installer, profiles, releases, transport, viewer
from kioskdesktop.gui import Application
from kioskdesktop.theme import field

PHASES = {
    "downloading": "Downloading image",
    "permission": "Waiting for administrator permission",
    "staging": "Copying into protected staging",
    "verifying_image": "Verifying image before erasure",
    "writing": "Flashing card",
    "verifying_write": "Verifying written card",
    "configuring": "Configuring kiosk",
    "ejecting": "Flushing and ejecting card",
    "complete": "Card ready",
    "connected": "Screen sharing connected",
    "disconnected": "Disconnected",
}


class Wizard(Application):
    def __init__(self, root, viewer_mode=False):
        super().__init__(root, viewer=viewer_mode)
        self.viewer_mode = viewer_mode
        self.profile_path = self.profile = self.release = self.selected = self.image = None
        self.mode, self.busy, self.closing = "flash", False, False
        self.cards, self.catalogue = [], []
        self.messages = queue.Queue(maxsize=64)
        self.cancel_event = threading.Event()
        self.card_operation = self.screen_session = self.screen_loop = None
        self.worker = None
        self.variables.update(
            {
                name: tk.StringVar(value=value)
                for name, value in {
                    "network": "Ethernet",
                    "preferences": "",
                    "device": "",
                    "release": "",
                    "image": "",
                    "profile": "",
                    "key_maintenance": "",
                    "key_administrator": "",
                    "phrase_maintenance": "",
                    "phrase_administrator": "",
                    "recovery_password": "",
                    "recovery_confirmation": "",
                }.items()
            }
        )
        self.previews = tk.BooleanVar(value=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.poll)
        self.home()

    def actions(self, back=None, next_action=None, *, back_text="Back", next_text="Continue", danger=False):
        self.back.configure(text=back_text, command=back or self.home, state="normal" if back else "disabled")
        self.next.configure(
            text=next_text,
            command=next_action or (lambda: None),
            style="Danger.TButton" if danger else "Selected.TButton",
            state="normal" if next_action else "disabled",
        )

    def page(self, step, title, explanation):
        parent = self.panel(title, explanation)
        self.form.canvas.yview_moveto(0)
        for child in self.navigation.winfo_children():
            child.configure(
                foreground=self.theme.color["ACCENT"] if child.cget("text") == step else self.theme.color["SECONDARY"]
            )
        self.status.configure(text="", style="Secondary.TLabel", wraplength=430)
        return parent

    def notice(self, text, error=False):
        self.status.configure(text=text, style="Error.TLabel" if error else "Secondary.TLabel")

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=label, command=command)
        button.pack(fill="x", pady=6)
        return button

    def home(self):
        parent = self.page(
            "Card",
            "Set up your kiosk" if not self.viewer_mode else "Screen Share",
            "Keep your existing card for recovery. Setup never connects to the mill."
            if not self.viewer_mode
            else "Open the verified setup profile for your kiosk. Screen sharing allows touchscreen input.",
        )
        if not self.viewer_mode:
            self.button(parent, "Install on a new card", lambda: self.begin("flash"))
            self.button(parent, "Configure an already-flashed card", lambda: self.begin("configure"))
            self.button(parent, "Check first boot", self.choose_profile)
            self.button(parent, "Resume saved card setup", lambda: self.choose_profile(resume=True))
        else:
            self.button(parent, "Choose kiosk profile", self.choose_profile)
        self.actions()

    def begin(self, mode):
        self.mode = mode
        self.profile_path = self.profile = self.selected = None
        self.show_card()

    def choose_profile(self, resume=False):
        selected = filedialog.askopenfilename(
            title="Open kiosk profile",
            initialdir=Path.home() / ".ssh/carvera",
            filetypes=(("Kiosk profile", "profile.json"), ("JSON", "*.json")),
        )
        if not selected:
            return
        try:
            self.profile_path = Path(selected).resolve(strict=True)
            self.profile = profiles.load(self.profile_path)
            self.variables["host"].set(self.profile.get("host", {}).get("address", self.profile["hostname"] + ".local"))
            if resume:
                if self.profile.get("stage") == "verified":
                    raise ValueError("Completed installations use authenticated settings")
                value = installer.transaction(self.profile_path, self.profile)
                self.release = releases.Release.parse(value["release"])
                status_path = self.profile_path.parent / "card-status.json"
                status = installer.shared("setup_protocol").read_json(status_path) if status_path.exists() else {}
                self.mode = (
                    "configure"
                    if status.get("id") == self.profile["id"]
                    and status.get("phase") in {"configuring", "ejecting", "complete"}
                    else "flash"
                )
                self.show_card()
            elif self.viewer_mode:
                self.viewer_page()
            else:
                self.boot_page()
        except (OSError, ValueError, KeyError):
            self.notice("This profile could not be opened. Select the original profile.json in your key folder.", True)

    def browse(self, variable, *, title, types):
        selected = filedialog.askopenfilename(title=title, filetypes=types)
        if selected:
            self.variables[variable].set(selected)

    def show_card(self):
        parent = self.page(
            "Card",
            "Select a removable card",
            "Only independently identified removable media are offered. "
            "If Windows asks to format the Linux partition, choose Cancel.",
        )
        ttk.Label(parent, text="Card").pack(anchor="w", pady=8)
        self.card_box = ttk.Combobox(parent, state="readonly", textvariable=self.variables["device"])
        self.card_box.pack(fill="x")
        self.button(parent, "Refresh cards", self.refresh_cards)
        if self.profile is None:
            ttk.Label(parent, text="Full kiosk release").pack(anchor="w", pady=(16, 8))
            self.release_box = ttk.Combobox(parent, state="readonly", textvariable=self.variables["release"])
            self.release_box.pack(fill="x")
            self.release_box.bind("<<ComboboxSelected>>", self.select_release)
            ttk.Checkbutton(parent, text="Include unsigned preview releases", variable=self.previews).pack(anchor="w")
            self.button(parent, "Find compatible releases", self.find_releases)
            self.button(parent, "Open offline release metadata", self.offline_metadata)
        if self.release:
            ttk.Label(parent, text=f"Selected release: {self.release.version}", style="Mono.TLabel").pack(
                anchor="w", pady=12
            )
        if self.mode == "flash":
            field(parent, "Offline image (optional; leave empty to download)", self.variables["image"])
            self.button(
                parent,
                "Choose image file",
                lambda: self.browse("image", title="Select matching image", types=(("XZ image", "*.img.xz"),)),
            )
        self.actions(self.home, self.card_continue)
        self.refresh_cards()

    def refresh_cards(self):
        self.background(
            lambda: devices.inventory([self.profile_path] if self.profile_path else []),
            self.cards_ready,
            "Checking removable cards",
        )

    def cards_ready(self, cards):
        self.cards = [card for card in cards if card.eligible]
        labels = [f"{card.description} · {card.capacity / 10**9:.1f} GB · {card.path}" for card in self.cards]
        self.card_box.configure(values=labels)
        self.variables["device"].set("")
        self.selected = None
        self.notice(
            "Select the card again after every removal or refresh."
            if labels
            else "No supported removable card found. Insert a card and refresh."
        )

    def find_releases(self):
        previews = self.previews.get()
        self.background(lambda: releases.discover(previews), self.releases_ready, "Finding complete kiosk releases")

    def releases_ready(self, values):
        self.catalogue = values
        self.release_box.configure(values=[release.version for release in values])
        if values:
            self.release_box.current(0)
            self.select_release()
        else:
            self.notice("No compatible full image is published. App-only releases cannot install a new card.", True)

    def select_release(self, _event=None):
        self.release = next(
            (value for value in self.catalogue if value.version == self.variables["release"].get()), None
        )

    def offline_metadata(self):
        path = filedialog.askopenfilename(
            title="Select setup-release.json", filetypes=(("Release metadata", "*.json"),)
        )
        if not path:
            return
        try:
            info = Path(path).stat()
            if info.st_size > releases.MAX_METADATA:
                raise ValueError("Metadata too large")
            self.release = releases.Release.parse(json.loads(Path(path).read_text(encoding="utf-8")))
            self.catalogue = [self.release]
            self.release_box.configure(values=[self.release.version])
            self.variables["release"].set(self.release.version)
            self.notice("Offline release loaded. Choose its matching image for installation.")
        except (ValueError, OSError, KeyError):
            self.notice("Select matching setup-release.json from a complete kiosk release.", True)

    def card_continue(self):
        index = self.card_box.current()
        if index < 0 or index >= len(self.cards) or self.release is None:
            self.notice("Select a card and a compatible full release first.", True)
            return
        self.selected = self.cards[index]
        if self.selected.capacity < self.release.image.minimum_capacity:
            self.notice("This card is too small for the selected image.", True)
            return
        if self.profile is not None:
            self.review()
        else:
            self.network_page()

    def network_page(self):
        parent = self.page(
            "Network",
            "Connect your kiosk",
            "Choose Ethernet or supported WPA-personal Wi-Fi. "
            "Network settings are removed from the boot partition after successful setup.",
        )
        ttk.Combobox(
            parent, textvariable=self.variables["network"], values=("Ethernet", "Wi-Fi"), state="readonly"
        ).pack(fill="x")
        for name, label in (
            ("hostname", "Kiosk name"),
            ("ssid", "Wi-Fi network name"),
            ("country", "Two-letter country code"),
        ):
            field(parent, label, self.variables[name])
        field(parent, "Wi-Fi password", self.variables["password"], secret=True)
        field(parent, "Preferences backup (optional)", self.variables["preferences"])
        self.button(
            parent,
            "Choose preferences backup",
            lambda: self.browse(
                "preferences",
                title="Import preferences",
                types=(("Preferences archive", "*.tar.gz *.tgz *.tar *.xz *.bz2"),),
            ),
        )
        self.actions(self.show_card, self.access_page)

    def access_page(self):
        parent = self.page(
            "Access",
            "Keep control of your kiosk",
            "Setup creates separate encrypted maintenance and administrator keys "
            "in a unique folder under your .ssh directory. Administrator access permits full control of the Pi.",
        )
        field(parent, "New key passphrase", self.variables["passphrase"], secret=True)
        field(parent, "Confirm new key passphrase", self.variables["confirmation"], secret=True)
        ttk.Label(
            parent,
            text="Save the passphrase privately. It is never saved in your setup profile.",
            style="Secondary.TLabel",
        ).pack(anchor="w", pady=12)
        for role, label in (("maintenance", "Maintenance"), ("administrator", "Administrator")):
            field(parent, f"Advanced: existing encrypted {label.lower()} key (optional)", self.variables["key_" + role])
            self.button(
                parent,
                f"Choose {label.lower()} key",
                lambda role=role: self.browse("key_" + role, title="Select encrypted key", types=(("All files", "*"),)),
            )
            field(parent, f"Existing {label.lower()} key passphrase", self.variables["phrase_" + role], secret=True)
        self.actions(self.network_page, self.prepare_review, next_text="Create keys and review")

    def prepare_review(self):
        values = {key: variable.get() for key, variable in self.variables.items()}
        wifi = (
            {"ssid": values["ssid"], "password": values["password"], "country": values["country"].upper()}
            if values["network"] == "Wi-Fi"
            else None
        )
        existing = {
            role: {"path": values["key_" + role], "passphrase": values["phrase_" + role]}
            for role in profiles.ROLES
            if values["key_" + role]
        }
        release = self.release
        if len(existing) < len(profiles.ROLES) and (
            not values["passphrase"] or values["passphrase"] != values["confirmation"]
        ):
            self.notice("Enter and confirm a nonempty passphrase for the new keys.", True)
            return
        probe = {
            "format": 2,
            "setup_protocol": 1,
            "id": "0" * 32,
            "hostname": values["hostname"],
            "authorized_keys": ["unused"],
            "admin_public_keys": ["unused"],
        }
        if wifi:
            probe["wifi"] = wifi
        try:
            installer.shared("setup_protocol").validate_request(probe, lambda _keys: None)
        except ValueError as error:
            self.notice(str(error), True)
            return

        def prepare():
            path, profile = profiles.create(
                values["hostname"], values["passphrase"], values["confirmation"], existing=existing
            )
            installer.prepare(path, profile, release, wifi, values["preferences"] or None)
            return path, profile

        self.background(prepare, self.prepared, "Saving encrypted keys and the private setup transaction")

    def prepared(self, result):
        self.profile_path, self.profile = result
        for key in ("password", "passphrase", "confirmation", "phrase_maintenance", "phrase_administrator"):
            self.variables[key].set("")
        self.review()

    def review(self):
        erases = self.mode == "flash"
        parent = self.page(
            "Review",
            "Review this card before erasing" if erases else "Review card configuration",
            "Everything on the selected card will be erased."
            if erases
            else "Only a fresh v3 card or this exact prepared transaction can be configured. Completed cards are rejected.",
        )
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=20)
        panel.pack(fill="x", pady=12)
        for text in (
            f"Card: {self.selected.description}",
            f"Physical device: {self.selected.path}",
            f"Capacity: {self.selected.capacity / 10**9:.1f} GB",
            f"Release: {self.release.version}",
            f"Kiosk: {self.profile['hostname']}",
            f"Key folder: {self.profile_path.parent}",
        ):
            ttk.Label(panel, text=text, style="Panel.TLabel", wraplength=900).pack(anchor="w", pady=4)
        self.agreement = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="I checked this physical card and approve erasing it."
            if erases
            else "I checked this physical card and approve its configuration.",
            variable=self.agreement,
            command=lambda: self.next.configure(state="normal" if self.agreement.get() else "disabled"),
        ).pack(anchor="w", pady=16)
        self.actions(self.show_card, self.install, next_text="Prepare installation")
        self.next.configure(state="disabled")
        self.back.focus_set()

    def install(self):
        if not self.agreement.get():
            return
        selected, path, profile, release, action = (
            self.selected,
            self.profile_path,
            self.profile,
            self.release,
            self.mode,
        )
        offline = self.variables["image"].get()
        self.page(
            "Install",
            "Installing your kiosk",
            "Keep the card inserted until ejection completes. Cancellation during flashing leaves an incomplete card.",
        )
        self.progress_label = ttk.Label(self.form.body, text="Preparing installation")
        self.progress_label.pack(anchor="w", pady=12)
        self.progress_bar = ttk.Progressbar(self.form.body, mode="determinate", maximum=100)
        self.progress_bar.pack(fill="x", pady=12)
        self.card_operation = installer.CardOperation()
        self.actions(None, self.cancel, next_text="Cancel")

        def operation():
            image = None
            if action == "flash":
                image = (
                    Path(offline).expanduser().resolve(strict=True)
                    if offline
                    else installer.download(release, installer.image_cache(), self.report, self.cancel_event.is_set)
                )
            return self.card_operation.run(selected, path, profile, action=action, image=image, progress=self.report)

        self.background(
            operation,
            lambda _result: self.card_ready(),
            "Preparing card operation",
            allow_cancel=True,
            failure=self.install_failed,
        )

    def install_failed(self, _error):
        phase = self.card_operation.last_phase
        incomplete = phase in {"configuring", "ejecting"}
        parent = self.page(
            "Install",
            "Configuration incomplete" if incomplete else "Installation incomplete",
            "Keep the card inserted. The saved profile retains the same keys and configuration. "
            "Retry configuration without reflashing after a verified flash. If flashing did not finish, explicitly install again.",
        )
        ttk.Label(parent, text=f"Saved profile: {self.profile_path}", style="Mono.TLabel", wraplength=900).pack(
            anchor="w", pady=16
        )
        self.mode = "configure" if incomplete else "flash"
        self.actions(self.home, self.show_card, next_text="Retry configuration" if incomplete else "Select card again")

    def confirm_media(self, value):
        selected = value["device"]
        parent = self.page(
            "Review",
            "Erase this card?" if value["erases"] else "Configure this card?",
            "The image passed verification. Keep this exact card inserted while approving the operation."
            if value["erases"]
            else "Keep this exact card inserted. Only the saved setup transaction will be applied.",
        )
        for text in (selected["description"], selected["path"], f"Capacity: {selected['capacity'] / 10**9:.1f} GB"):
            ttk.Label(parent, text=text, style="Mono.TLabel").pack(anchor="w", pady=8)
        self.agreement = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="I checked this card and approve erasing all its contents."
            if value["erases"]
            else "I checked this card and approve configuring it.",
            variable=self.agreement,
            command=lambda: self.next.configure(state="normal" if self.agreement.get() else "disabled"),
        ).pack(anchor="w", pady=16)
        self.actions(
            self.cancel,
            self.confirm_write,
            back_text="Cancel",
            next_text="Erase and install" if value["erases"] else "Configure card",
            danger=value["erases"],
        )
        self.next.configure(state="disabled")
        self.back.focus_set()

    def confirm_write(self):
        if not self.agreement.get():
            return
        self.card_operation.confirm()
        self.page("Install", "Installing your kiosk", "Keep the selected card inserted until ejection finishes.")
        self.progress_label = ttk.Label(self.form.body, text="Preparing card")
        self.progress_label.pack(anchor="w", pady=12)
        self.progress_bar = ttk.Progressbar(self.form.body, maximum=100)
        self.progress_bar.pack(fill="x", pady=12)
        self.actions(None, self.cancel, next_text="Cancel")

    def card_ready(self):
        self.page(
            "Install",
            "Your card is ready",
            "Insert it into the Pi, keep the mill disconnected, then power on. "
            "Wait for setup to finish on the touchscreen before checking first boot.",
        )
        self.variables["host"].set(self.profile["hostname"] + ".local")
        self.actions(self.home, self.boot_page, next_text="Check first boot")

    def boot_page(self):
        parent = self.page(
            "Install",
            "Check first boot",
            "The SSH fingerprint must match the one shown on the kiosk touchscreen. "
            "Do not trust a different or changed key.",
        )
        field(parent, "Kiosk hostname or IP address", self.variables["host"])
        field(parent, "Maintenance key passphrase", self.variables["passphrase"], secret=True)
        field(
            parent,
            "Administrator key passphrase (leave empty if the same)",
            self.variables["phrase_administrator"],
            secret=True,
        )
        self.actions(self.home, self.probe_host, next_text="Compare fingerprint")

    def probe_host(self):
        address = self.variables["host"].get()
        self.background(
            lambda: asyncio.run(transport.probe(address)), self.confirm_host, "Reading the Pi's SSH fingerprint"
        )

    def confirm_host(self, host):
        previous = self.profile.get("host")
        if previous and previous["public"] != host["public"]:
            self.notice(
                "The host key changed. The saved identity was preserved; check the Pi and network before continuing.",
                True,
            )
            return
        parent = self.page(
            "Install", "Compare with the touchscreen", "Only continue if this exact fingerprint appears on your Pi."
        )
        ttk.Label(parent, text=host["address"], style="Mono.TLabel").pack(anchor="w", pady=12)
        ttk.Label(parent, text=host["fingerprint"], style="Mono.TLabel", wraplength=900).pack(anchor="w", pady=16)
        self.agreement = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="I compared the fingerprint on the touchscreen and it matches exactly.",
            variable=self.agreement,
            command=lambda: self.next.configure(state="normal" if self.agreement.get() else "disabled"),
        ).pack(anchor="w", pady=16)
        self.actions(self.boot_page, lambda: self.verify(host), next_text="Verify installation")
        self.next.configure(state="disabled")

    def verify(self, host):
        if not self.agreement.get():
            return
        candidate = {**self.profile, "host": host}
        phrase, admin_phrase = self.variables["passphrase"].get(), self.variables["phrase_administrator"].get()

        def operation():
            result = asyncio.run(transport.verify_first_boot(candidate, phrase, admin_phrase or None))
            candidate["stage"] = "verified"
            installer.finish_verification(self.profile_path, candidate)
            return candidate, result

        self.background(operation, self.verified, "Checking installation, both accounts and administrator access")

    def verified(self, value):
        self.profile, result = value
        self.page(
            "Install",
            "Kiosk verified",
            "Both accounts and administrator access passed verification. "
            "The controller remains disconnected. Set a private local recovery password and test TTY2 with a keyboard.",
        )
        ttk.Label(self.form.body, text=f"Image: {result['image']['version']}", style="Mono.TLabel").pack(
            anchor="w", pady=4
        )
        for component, metadata in result["components"].items():
            ttk.Label(
                self.form.body, text=f"{component.capitalize()}: {metadata['version']}", style="Mono.TLabel"
            ).pack(anchor="w", pady=4)
        self.button(self.form.body, "Set local recovery password", self.recovery_page)
        self.actions(self.boot_page, self.finish, next_text="Finish setup")

    def recovery_page(self):
        parent = self.page(
            "Install",
            "Set local recovery password",
            "This password is for kiosk-admin on the physical keyboard console. "
            "SSH password login remains disabled. Use Ctrl+Alt+F2 to test it, then Ctrl+Alt+F1 to return to the kiosk.",
        )
        field(parent, "Administrator key passphrase", self.variables["phrase_administrator"], secret=True)
        field(parent, "Local recovery password", self.variables["recovery_password"], secret=True)
        field(parent, "Confirm local recovery password", self.variables["recovery_confirmation"], secret=True)
        self.actions(self.finish, self.set_password, next_text="Set password")

    def set_password(self):
        phrase = self.variables["phrase_administrator"].get() or self.variables["passphrase"].get()
        password, confirmation = (
            self.variables["recovery_password"].get(),
            self.variables["recovery_confirmation"].get(),
        )
        self.background(
            lambda: asyncio.run(transport.set_recovery_password(self.profile, phrase, password, confirmation)),
            lambda _result: self.finish(),
            "Setting the local console password over verified SSH",
        )

    def finish(self):
        for key in ("passphrase", "phrase_administrator", "recovery_password", "recovery_confirmation"):
            self.variables[key].set("")
        parent = self.page(
            "Install",
            "Your kiosk is set up",
            "Keep your profile and encrypted keys. "
            "Use the separate Screen Share download for touchscreen access; routine updates remain in the maintenance tools.",
        )
        details = profiles.connection_details(self.profile)
        for text in (
            f"Address: {details['address']}",
            f"Host: {details['host_fingerprint']}",
            *(
                f"{role.capitalize()}: {item['username']} · {item['key_path']}"
                for role, item in details["accounts"].items()
            ),
        ):
            ttk.Label(parent, text=text, style="Mono.TLabel", wraplength=900).pack(anchor="w", pady=8)
        self.button(parent, "Show key folder", self.show_folder)
        self.button(parent, "Copy connection details", self.copy_details)
        self.button(parent, "Download Screen Share", self.download_viewer)
        self.actions(self.home, self.close, next_text="Close")

    def show_folder(self):
        path = str(self.profile_path.parent)
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(
                ["/usr/bin/xdg-open", path],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

    def copy_details(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(json.dumps(profiles.connection_details(self.profile), indent=2))
        self.notice("Connection details copied. Private keys and passphrases are excluded.")

    def download_viewer(self):
        def resolve():
            release = self.release or installer.load_release(self.profile_path, self.profile)
            return release.version, releases.published_viewer_url(release, installer.desktop_target())

        def open_download(result):
            version, url = result
            webbrowser.open(url or releases.RELEASES_PAGE)
            if url:
                self.notice("Opened the Screen Share download in your browser.")
            else:
                self.notice(f"Look for Kiosk {version} on GitHub. Sign in to access a draft release.")

        self.background(resolve, open_download, "Checking the Screen Share download")

    def viewer_page(self):
        parent = self.page(
            "",
            "Connect to your kiosk",
            "Screen sharing allows touchscreen input. "
            "Connect explicitly when you are ready, then Disconnect to close the owned session.",
        )
        host = self.profile.get("host", {})
        ttk.Label(parent, text=f"Kiosk: {host.get('address', 'Not verified')}", style="Mono.TLabel").pack(
            anchor="w", pady=8
        )
        ttk.Label(
            parent,
            text=host.get("fingerprint", "Complete first-boot verification in Setup."),
            style="Mono.TLabel",
            wraplength=900,
        ).pack(anchor="w", pady=8)
        ttk.Label(
            parent,
            text=f"Maintenance key: {self.profile['keys']['maintenance']['path']}",
            style="Mono.TLabel",
            wraplength=900,
        ).pack(anchor="w", pady=8)
        field(parent, "Maintenance key passphrase", self.variables["passphrase"], secret=True)
        self.actions(self.home, self.connect_viewer, next_text="Connect")
        self.notice("Disconnected")

    def connect_viewer(self):
        profile, phrase = self.profile, self.variables["passphrase"].get()
        self.screen_session = viewer.Session()

        def operation():
            async def run():
                self.screen_loop = asyncio.get_running_loop()
                if self.cancel_event.is_set():
                    self.screen_session.stop_requested.set()
                await self.screen_session.run(profile, phrase, self.report)

            try:
                asyncio.run(run())
            finally:
                self.screen_loop = None

        self.background(
            operation,
            lambda _result: self.viewer_page(),
            "Connecting screen sharing",
            allow_cancel=True,
            failure=lambda _error: self.viewer_failure(),
        )
        self.actions(None, self.cancel, next_text="Disconnect")

    def viewer_failure(self):
        self.viewer_page()
        self.notice(
            "Screen sharing ended. Check the kiosk, passphrase and System version, then connect again explicitly.", True
        )

    def report(self, value):
        try:
            self.messages.put_nowait(("progress", value))
        except queue.Full:
            pass

    def background(self, function, success, label, *, allow_cancel=False, failure=None):
        if self.busy or self.closing:
            return
        self.busy = True
        self.cancel_event.clear()
        self.notice(label)
        self.back.configure(state="disabled")
        self.next.configure(state="normal" if allow_cancel else "disabled")
        self.on_success, self.on_failure = success, failure

        def run():
            try:
                result = function()
            except Exception as error:
                self.messages.put(("error", error))
            else:
                self.messages.put(("result", result))

        self.worker = threading.Thread(target=run, name="kiosk-desktop-operation")
        self.worker.start()

    def poll(self):
        for _ in range(64):
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                phase = value.get("phase")
                if phase == "awaiting_confirmation":
                    self.confirm_media(value)
                    continue
                self.notice(PHASES.get(phase, "Working"))
                if hasattr(self, "progress_label") and self.progress_label.winfo_exists():
                    self.progress_label.configure(text=PHASES.get(phase, "Working"))
                    percent = value.get("percent", 100 * value.get("bytes", 0) / max(1, value.get("total", 1)))
                    self.progress_bar.configure(value=percent)
            else:
                self.busy = False
                self.back.configure(state="normal")
                self.next.configure(state="normal")
                if kind == "result":
                    self.on_success(value)
                elif self.on_failure:
                    self.on_failure(value)
                else:
                    # Native tools and archive parsers may include private input in exceptions.
                    self.notice(
                        "Administrator permission was declined or no desktop authorization agent is available. Retry from your normal desktop account."
                        if isinstance(value, PermissionError)
                        else "This step could not finish. Check the selected files, connection and entered values, then retry.",
                        True,
                    )
        if (
            self.closing
            and not self.busy
            and (not self.worker or not self.worker.is_alive())
            and (not self.card_operation or not self.card_operation.is_running())
        ):
            self.root.destroy()
            return
        self.root.after(80, self.poll)

    def cancel(self):
        self.cancel_event.set()
        if self.card_operation:
            self.card_operation.cancel()
        if self.screen_loop and self.screen_session:
            self.screen_loop.call_soon_threadsafe(self.screen_session.stop_requested.set)
        self.notice("Closing the owned operation. Keep the card inserted until cleanup finishes.")
        self.next.configure(state="disabled")

    def close(self):
        if self.busy or (self.card_operation and self.card_operation.is_running()):
            if not messagebox.askyesno(
                "Close setup?",
                "Cancel the current operation and close after cleanup? A partially flashed card must be installed again.",
                parent=self.root,
            ):
                return
            self.closing = True
            self.cancel()
        else:
            self.root.destroy()
