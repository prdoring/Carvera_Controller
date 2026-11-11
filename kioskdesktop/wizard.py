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
    "downloading": "Downloading kiosk software",
    "permission": "Waiting for administrator permission",
    "staging": "Preparing files for the card",
    "verifying_image": "Checking the download",
    "writing": "Writing the card",
    "verifying_write": "Checking what was written",
    "configuring": "Saving Pi settings",
    "ejecting": "Ejecting the card",
    "complete": "Safe to remove the card",
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
        self.confirmed_host = None
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
                    "source": "",
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
        self.set_step(step)
        self.status.configure(text="", style="Secondary.TLabel", wraplength=430)
        return parent

    def notice(self, text, error=False):
        self.status.configure(text=text, style="Error.TLabel" if error else "Secondary.TLabel")

    def button(self, parent, label, command):
        button = ttk.Button(parent, text=label, command=command)
        button.pack(fill="x", pady=6)
        return button

    def detail(self, parent, text, style="Mono.TLabel"):
        label = ttk.Label(parent, text=text, style=style, wraplength=900)
        label.pack(anchor="w", fill="x", pady=8)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width)))

    def advanced(self, parent, title):
        expanded = tk.BooleanVar(value=False)
        frame = ttk.Frame(parent)
        toggle = ttk.Checkbutton(parent, text=title, variable=expanded)
        toggle.configure(command=lambda: frame.pack(fill="x") if expanded.get() else frame.pack_forget())
        toggle.pack(anchor="w", pady=12)
        return frame

    def clear_secrets(self):
        for key in (
            "password",
            "passphrase",
            "confirmation",
            "phrase_maintenance",
            "phrase_administrator",
            "recovery_password",
            "recovery_confirmation",
        ):
            self.variables[key].set("")

    def home(self):
        self.clear_secrets()
        parent = self.page(
            "Choose a card",
            "Set up your kiosk" if not self.viewer_mode else "Screen Share",
            "Use a spare SD card and keep your working card for recovery."
            if not self.viewer_mode
            else "Choose your kiosk to view and control its touchscreen from this computer.",
        )
        if not self.viewer_mode:
            self.button(parent, "Install on an SD card", lambda: self.begin("flash"))
            self.button(parent, "Continue a saved setup", self.choose_profile)
            advanced = self.advanced(parent, "Advanced options")
            self.button(advanced, "Configure an already-written card", lambda: self.begin("configure"))
        else:
            self.button(parent, "Choose kiosk", self.choose_profile)
        self.actions()

    def begin(self, mode):
        self.clear_secrets()
        self.mode = mode
        self.profile_path = self.profile = self.selected = self.release = None
        self.catalogue = []
        self.variables["release"].set("")
        self.variables["image"].set("")
        self.variables["source"].set("")
        for name in ("preferences", "key_maintenance", "key_administrator"):
            self.variables[name].set("")
        self.show_card()

    def choose_profile(self):
        self.clear_secrets()
        parent = self.page(
            "Start the kiosk", "Choose your kiosk", "Continue with the keys and settings saved on this computer."
        )
        self.profile_box = ttk.Combobox(parent, state="readonly")
        self.profile_box.pack(fill="x", pady=12)
        self.button(parent, "Browse for profile", self.browse_profile)
        self.actions(self.home)
        self.background(profiles.saved, self.profiles_ready, "Finding saved setups")

    def profiles_ready(self, values):
        self.saved_profiles = values
        stages = {"keys": "Setup not saved", "prepared": "Setup in progress", "verified": "Laptop access verified"}
        self.profile_box.configure(
            values=[f"{value['hostname']} · {stages[value['stage']]} · {value['id'][:8]}" for _path, value in values]
        )
        self.actions(self.home, self.open_selected_profile)
        if values:
            self.profile_box.current(0)
            self.notice("Choose the kiosk you want to continue setting up.")
        else:
            self.next.configure(state="disabled")
            self.notice("No saved setups found. Browse for the original profile.json if it is in another folder.")

    def open_selected_profile(self):
        index = self.profile_box.current()
        if 0 <= index < len(self.saved_profiles):
            self.open_profile(self.saved_profiles[index][0])

    def browse_profile(self):
        selected = filedialog.askopenfilename(
            title="Open kiosk profile",
            initialdir=Path.home() / ".ssh/carvera",
            filetypes=(("Kiosk profile", "profile.json"), ("JSON", "*.json")),
        )
        if selected:
            self.open_profile(selected)

    def open_profile(self, selected):
        try:
            path = Path(selected).resolve(strict=True)
            profile = profiles.load(path)
            self.release = None
            self.selected = None
            self.confirmed_host = None
            self.variables["image"].set("")
            self.profile_path, self.profile = path, profile
            self.variables["host"].set(self.profile.get("host", {}).get("address", self.profile["hostname"] + ".local"))
            if self.viewer_mode:
                self.viewer_page()
            elif profile["stage"] == "verified":
                self.finish()
            elif profile["stage"] == "keys":
                self.notice(
                    "This setup was not saved. Start an installation again; the existing key folder is retained.", True
                )
            else:
                self.release = installer.load_release(path, profile)
                status_path = path.parent / "card-status.json"
                try:
                    status = installer.shared("setup_protocol").read_json(status_path)
                except (OSError, ValueError):
                    status = {}
                phase = status.get("phase") if status.get("id") == profile["id"] else None
                if phase == "complete":
                    self.card_ready()
                elif phase == "ejecting":
                    self.ejection_failed()
                else:
                    configuring = phase == "configuring" or (
                        status.get("id") == profile["id"] and status.get("action") in {"configure", "resume"}
                    )
                    self.mode = "configure" if configuring else "flash"
                    self.resume_page()
        except (OSError, ValueError, KeyError):
            self.notice("This profile could not be opened. Select the original profile.json in your key folder.", True)

    def resume_page(self):
        parent = self.page(
            "Start the kiosk",
            "Continue a saved setup",
            "If the card is in the Pi, wait for the controller screen, then check laptop access. "
            "If card preparation was interrupted on this computer, select the card again to retry.",
        )
        ttk.Label(parent, text=self.profile["hostname"], style="Mono.TLabel").pack(anchor="w", pady=8)
        self.button(parent, "Check laptop access", self.boot_page)
        label = "Retry saving settings" if self.mode == "configure" else "Select and write the card again"
        self.button(parent, label, self.show_card)
        self.actions(self.choose_profile, self.close, next_text="Finish later")

    def browse(self, variable, *, title, types):
        selected = filedialog.askopenfilename(title=title, filetypes=types)
        if selected:
            self.variables[variable].set(selected)

    def show_card(self):
        parent = self.page(
            "Choose a card",
            "Choose a card",
            "Select the reader name and capacity of your SD card. If Windows asks to format the card, choose Cancel.",
        )
        ttk.Label(parent, text="Card").pack(anchor="w", pady=8)
        self.card_box = ttk.Combobox(parent, state="readonly", textvariable=self.variables["device"])
        self.card_box.pack(fill="x")
        self.button(parent, "Refresh cards", self.refresh_cards)
        if self.profile is None:
            for label, source in (("Download kiosk software", "download"), ("Use downloaded files", "offline")):
                ttk.Radiobutton(
                    parent, text=label, variable=self.variables["source"], value=source, command=self.source_changed
                ).pack(anchor="w", pady=6)
            ttk.Label(parent, text="Kiosk software version").pack(anchor="w", pady=(16, 8))
            self.release_box = ttk.Combobox(parent, state="readonly", textvariable=self.variables["release"])
            self.release_box.pack(fill="x")
            self.release_box.configure(values=[value.version for value in self.catalogue])
            self.release_box.bind("<<ComboboxSelected>>", self.select_release)
            ttk.Checkbutton(parent, text="Include unsigned preview releases", variable=self.previews).pack(anchor="w")
            self.button(parent, "Find compatible versions", self.find_releases)
            self.offline_box = ttk.Frame(parent)
            self.button(self.offline_box, "Choose downloaded files", self.offline_metadata)
            if self.variables["source"].get() == "offline":
                self.offline_box.pack(fill="x")
        if self.release:
            ttk.Label(parent, text=f"Selected release: {self.release.version}", style="Mono.TLabel").pack(
                anchor="w", pady=12
            )
        if self.mode == "flash" and self.profile is not None:
            field(parent, "Downloaded image (optional; leave empty to download)", self.variables["image"])
            self.button(
                parent,
                "Choose image file",
                lambda: self.browse("image", title="Select matching image", types=(("XZ image", "*.img.xz"),)),
            )
        self.actions(self.home, self.card_continue)
        # Read Tk variables on the UI thread before starting discovery.
        online = self.profile is None and self.variables["source"].get() == "download" and self.release is None
        previews = self.previews.get()
        protected = [self.profile_path] if self.profile_path else []

        def inspect():
            cards = devices.inventory(protected)
            try:
                catalogue = releases.discover(previews) if online else None
            except (OSError, ValueError):
                catalogue = []
            return cards, catalogue

        def ready(result):
            cards, catalogue = result
            self.cards_ready(cards)
            if catalogue is not None:
                self.releases_ready(catalogue)

        self.background(inspect, ready, "Finding cards and kiosk software")

    def source_changed(self):
        self.release = None
        self.catalogue = []
        self.release_box.configure(values=[])
        self.variables["release"].set("")
        self.variables["image"].set("")
        if self.variables["source"].get() == "offline":
            self.offline_box.pack(fill="x")
            self.notice("Choose setup-release.json and its matching image from the same release.")
        else:
            self.offline_box.pack_forget()
            self.find_releases()

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
        self.variables["source"].set("download")
        self.variables["image"].set("")
        self.offline_box.pack_forget()
        previews = self.previews.get()
        self.background(lambda: releases.discover(previews), self.releases_ready, "Finding complete kiosk releases")

    def releases_ready(self, values):
        self.catalogue = values
        self.release = None
        self.variables["release"].set("")
        self.release_box.configure(values=[release.version for release in values])
        if values:
            self.release_box.current(0)
            self.select_release()
        else:
            self.notice("No compatible kiosk software was found. Retry finding versions or use downloaded files.", True)

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
            if self.mode == "flash":
                image = filedialog.askopenfilename(
                    title="Choose the matching kiosk image",
                    initialdir=Path(path).parent,
                    filetypes=(("Kiosk image", "*.img.xz"),),
                )
                self.variables["image"].set(image)
            self.notice("Downloaded files selected. Their contents will be checked before erasing.")
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
        if (
            self.mode == "flash"
            and self.profile is None
            and self.variables["source"].get() == "offline"
            and not self.variables["image"].get()
        ):
            self.notice("Choose both setup-release.json and its matching image.", True)
            return
        selected = self.selected
        protected = [self.profile_path] if self.profile_path else []

        def ready(cards):
            current = next(
                (
                    card
                    for card in cards
                    if card.eligible
                    and (card.path, card.identity, card.capacity)
                    == (selected.path, selected.identity, selected.capacity)
                ),
                None,
            )
            if current is None:
                self.cards_ready(cards)
                self.notice("The card was removed or changed. Select the card again before continuing.", True)
                return
            self.selected = current
            if self.profile is not None:
                self.review()
            else:
                self.network_page()

        self.background(lambda: devices.inventory(protected), ready, "Checking the selected card")

    def network_page(self):
        parent = self.page(
            "Set up your Pi",
            "Set up your Pi",
            "Name your Pi using lowercase letters, numbers and hyphens. Choose how it will join your network.",
        )
        field(parent, "Pi name", self.variables["hostname"])
        self.address_preview = ttk.Label(parent, style="Secondary.TLabel")
        self.address_preview.pack(anchor="w", pady=8)

        def address(*_args):
            self.address_preview.configure(text=f"Pi address: {self.variables['hostname'].get()}.local")

        trace = self.variables["hostname"].trace_add("write", address)
        self.address_preview.bind("<Destroy>", lambda _event: self.variables["hostname"].trace_remove("write", trace))
        address()
        network = ttk.Combobox(
            parent, textvariable=self.variables["network"], values=("Ethernet", "Wi-Fi"), state="readonly"
        )
        network.pack(fill="x")
        self.network_choice = network
        self.wifi_box = ttk.Frame(parent)
        network.bind("<<ComboboxSelected>>", lambda _event: self.wifi_visibility())
        for name, label in (
            ("ssid", "Wi-Fi network name"),
            ("country", "Two-letter country code"),
        ):
            field(self.wifi_box, label, self.variables[name])
        field(self.wifi_box, "Wi-Fi password", self.variables["password"], secret=True)
        self.wifi_visibility()
        advanced = self.advanced(parent, "Restore a settings backup (optional)")
        field(advanced, "Settings backup", self.variables["preferences"])
        self.button(
            advanced,
            "Choose settings backup",
            lambda: self.browse(
                "preferences",
                title="Import preferences",
                types=(("Preferences archive", "*.tar.gz *.tgz *.tar *.xz *.bz2"),),
            ),
        )
        self.actions(self.show_card, self.network_continue)

    def wifi_visibility(self):
        if self.variables["network"].get() == "Wi-Fi":
            self.wifi_box.pack(fill="x", after=self.network_choice)
        else:
            self.wifi_box.pack_forget()

    def network_continue(self):
        if self.valid_network():
            self.access_page()

    def valid_network(self):
        request = {
            "format": 2,
            "setup_protocol": 1,
            "id": "0" * 32,
            "hostname": self.variables["hostname"].get(),
            "authorized_keys": ["unused"],
            "admin_public_keys": ["unused"],
        }
        if self.variables["network"].get() == "Wi-Fi":
            request["wifi"] = {name: self.variables[name].get() for name in ("ssid", "password", "country")}
            request["wifi"]["country"] = request["wifi"]["country"].upper()
        try:
            installer.shared("setup_protocol").validate_request(request, lambda _keys: None)
        except ValueError as error:
            self.notice(
                "Use a Pi name with lowercase letters, numbers and internal hyphens."
                if str(error) == "Use a valid lowercase kiosk hostname"
                else "Wi-Fi needs a network name, two-letter country code and an 8–63 byte password.",
                True,
            )
            return False
        return True

    def access_page(self):
        parent = self.page(
            "Set up your Pi",
            "Save an access key passphrase",
            "This unlocks the keys for Screen Share and Pi administration. Save it somewhere private. "
            "Setup saves encrypted keys on this computer. You will enter the passphrase again when connecting.",
        )
        field(parent, "Access key passphrase", self.variables["passphrase"], secret=True)
        field(parent, "Confirm access key passphrase", self.variables["confirmation"], secret=True)
        advanced = self.advanced(parent, "Use existing access keys (advanced)")
        for role, label in (("maintenance", "Maintenance"), ("administrator", "Administrator")):
            field(advanced, f"Existing encrypted {label.lower()} key (optional)", self.variables["key_" + role])
            self.button(
                advanced,
                f"Choose {label.lower()} key",
                lambda role=role: self.browse("key_" + role, title="Select encrypted key", types=(("All files", "*"),)),
            )
            field(advanced, f"Existing {label.lower()} key passphrase", self.variables["phrase_" + role], secret=True)
        self.actions(self.network_page, self.access_review, next_text="Review setup")

    def access_review(self):
        generated = any(not self.variables["key_" + role].get() for role in profiles.ROLES)
        phrase = self.variables["passphrase"].get()
        if generated and (not phrase or phrase != self.variables["confirmation"].get()):
            self.notice("Enter and confirm the same nonempty access key passphrase.", True)
            return
        self.review()

    def prepare_review(self):
        if not self.valid_network():
            return
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

        def prepare():
            path, profile = profiles.create(
                values["hostname"], values["passphrase"], values["confirmation"], existing=existing
            )
            installer.prepare(path, profile, release, wifi, values["preferences"] or None)
            return path, profile

        self.background(prepare, self.prepared, "Saving your setup and encrypted access keys")

    def prepared(self, result):
        self.profile_path, self.profile = result
        self.clear_secrets()
        self.install()

    def review(self):
        erases = self.mode == "flash"
        parent = self.page(
            "Write the card",
            "Review your setup",
            "Prepare card saves your setup, downloads and checks the software, then asks for permission to erase this card. "
            "Your computer may ask for administrator permission to access the card."
            if erases
            else "Prepare card saves your setup and asks for permission to write Pi settings. "
            "Use a fresh card or retry the original saved setup.",
        )
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=20)
        panel.pack(fill="x", pady=12)
        for text in (
            f"Card: {self.selected.description}",
            f"Physical device: {self.selected.path}",
            f"Capacity: {self.selected.capacity / 10**9:.1f} GB",
            f"Release: {self.release.version}",
            f"Pi address: {(self.profile['hostname'] if self.profile else self.variables['hostname'].get())}.local",
        ):
            self.detail(panel, text, "Panel.TLabel")
        if self.profile:
            self.detail(panel, f"Setup folder: {self.profile_path.parent}", "Panel.TLabel")
        else:
            network = self.variables["network"].get()
            if network == "Wi-Fi":
                network += " · " + self.variables["ssid"].get()
            self.detail(panel, f"Network: {network}", "Panel.TLabel")
            backup = self.variables["preferences"].get()
            self.detail(
                panel, f"Settings backup: {Path(backup).name if backup else 'Start with defaults'}", "Panel.TLabel"
            )
            for role in profiles.ROLES:
                choice = "Use existing key" if self.variables["key_" + role].get() else "Create new key"
                self.detail(panel, f"{role.capitalize()} access: {choice}", "Panel.TLabel")
        self.actions(
            self.show_card if self.profile else self.access_page,
            self.install if self.profile else self.prepare_review,
            next_text="Prepare card",
        )
        self.back.focus_set()

    def install(self):
        selected, path, profile, release, action = (
            self.selected,
            self.profile_path,
            self.profile,
            self.release,
            self.mode,
        )
        offline = self.variables["image"].get()
        self.page(
            "Write the card",
            "Preparing your card",
            "Keep the card inserted until Setup says it is safe to remove. Cancelling during writing leaves an incomplete card.",
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

    def install_failed(self, error):
        if self.card_operation.is_running():
            self.page(
                "Write the card",
                "Waiting for card access to close",
                "Keep the card inserted while the card worker finishes cleanup.",
            )
            self.actions()
            self.root.after(500, lambda: self.install_failed(error) if not self.closing else None)
            return
        phase = self.card_operation.last_phase
        if phase == "ejecting":
            self.ejection_failed()
            return
        incomplete = phase == "configuring" or self.mode != "flash"
        before_write = (
            phase in {None, "staging", "verifying_image", "awaiting_confirmation"}
            and not self.card_operation.confirmed.is_set()
        )
        if incomplete:
            title = "Pi settings could not be saved"
            explanation = "Select the same card to retry saving settings with your original keys and configuration."
        elif before_write:
            title = "Card preparation stopped"
            explanation = "Your card has not been erased. Check the downloaded files or approve the card-access prompt, then retry."
        else:
            title = "The card is not ready to boot"
            explanation = (
                "Writing or checking the card did not finish. Select the card again and confirm erasing it to retry."
            )
        parent = self.page(
            "Write the card",
            title,
            explanation,
        )
        self.detail(parent, f"Saved profile: {self.profile_path}")
        if incomplete:
            self.mode = "configure"
        self.actions(
            self.home, self.show_card, next_text="Retry saving settings" if incomplete else "Select card again"
        )

    def ejection_failed(self):
        self.page(
            "Write the card",
            "Eject the prepared card",
            "Your Pi settings were saved. Close any windows or applications using the card, then use your computer's Eject or Safely Remove control. "
            "After it confirms removal is safe, remove the card and continue.",
        )
        self.button(self.form.body, "Check laptop access", self.boot_page)
        self.actions(self.home, lambda: self.card_ready(ejected=False), next_text="I safely removed the card")

    def confirm_media(self, value):
        selected = value["device"]
        parent = self.page(
            "Write the card",
            "Erase this card?" if value["erases"] else "Configure this card?",
            "The image passed verification. Keep this exact card inserted while approving the operation."
            if value["erases"]
            else "Keep this exact card inserted. Only the saved setup transaction will be applied.",
        )
        for text in (selected["description"], selected["path"], f"Capacity: {selected['capacity'] / 10**9:.1f} GB"):
            self.detail(parent, text)
        self.agreement = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="Erase all contents of this card"
            if value["erases"]
            else "I checked this card and approve configuring it.",
            variable=self.agreement,
            command=lambda: self.next.configure(state="normal" if self.agreement.get() else "disabled"),
        ).pack(anchor="w", pady=16)
        self.actions(
            self.cancel,
            self.confirm_write,
            back_text="Cancel",
            next_text="Erase and write card" if value["erases"] else "Save Pi settings",
            danger=value["erases"],
        )
        self.next.configure(state="disabled")
        self.back.focus_set()

    def confirm_write(self):
        if not self.agreement.get():
            return
        self.card_operation.confirm()
        self.page("Write the card", "Writing your card", "Keep the selected card inserted until ejection finishes.")
        self.progress_label = ttk.Label(self.form.body, text="Preparing card")
        self.progress_label.pack(anchor="w", pady=12)
        self.progress_bar = ttk.Progressbar(self.form.body, maximum=100)
        self.progress_bar.pack(fill="x", pady=12)
        self.actions(None, self.cancel, next_text="Cancel")

    def card_ready(self, ejected=True):
        self.page(
            "Start the kiosk",
            "Safe to remove the card" if ejected else "Start the kiosk",
            "Put the card in the Pi. If you chose Ethernet, plug in the network cable. "
            "Leave the mill disconnected and power on. First startup can take several minutes. "
            "Wait for the controller screen to open, then check laptop access for Screen Share and Pi administration.",
        )
        self.clear_secrets()
        self.variables["host"].set(self.profile["hostname"] + ".local")
        self.actions(self.close, self.boot_page, back_text="Finish later", next_text="Check laptop access")
        self.notice("Resume later with Continue a saved setup.")

    def boot_page(self):
        parent = self.page(
            "Start the kiosk",
            "Check laptop access",
            "Wait for the controller screen on the Pi. On its touchscreen, open "
            "Settings → System → Overview → Laptop access to find the network address and SSH identity.",
        )
        field(parent, "Kiosk hostname or IP address", self.variables["host"])
        self.confirmed_host = None
        self.actions(self.close, self.probe_host, back_text="Finish later", next_text="Compare fingerprint")

    def probe_host(self):
        address = self.variables["host"].get()
        self.background(
            lambda: asyncio.run(transport.probe(address)),
            self.confirm_host,
            "Reading the Pi's SSH fingerprint",
            failure=lambda _error: self.notice(
                "Could not reach the Pi. Check its power and network, or enter the address shown under Laptop access on its touchscreen.",
                True,
            ),
        )

    def confirm_host(self, host):
        previous = self.profile.get("host")
        if previous and previous["public"] != host["public"]:
            self.notice(
                "The Pi's SSH identity has changed. Check the address and touchscreen identity before continuing with this saved setup.",
                True,
            )
            return
        parent = self.page(
            "Start the kiosk",
            "Compare with the touchscreen",
            "On the Pi, open Settings → System → Overview → Laptop access. "
            "Compare the SHA256 fingerprint under SSH identity with the one below.",
        )
        self.detail(parent, host["address"])
        self.detail(parent, host["fingerprint"])
        self.agreement = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            parent,
            text="The fingerprint matches exactly",
            variable=self.agreement,
            command=lambda: self.next.configure(state="normal" if self.agreement.get() else "disabled"),
        ).pack(anchor="w", pady=16)
        self.actions(self.boot_page, lambda: self.access_check_page(host), next_text="Continue")
        self.next.configure(state="disabled")

    def access_check_page(self, host):
        if not self.agreement.get():
            return
        self.confirmed_host = host
        parent = self.page(
            "Start the kiosk",
            "Unlock your access keys",
            "Enter the access key passphrase you saved when preparing the card. "
            "Setup will check this installation and both access accounts.",
        )
        field(parent, "Access key passphrase (maintenance key)", self.variables["passphrase"], secret=True)
        advanced = self.advanced(parent, "Separate administrator passphrase")
        field(advanced, "Administrator key passphrase", self.variables["phrase_administrator"], secret=True)
        self.actions(self.boot_page, self.verify, next_text="Check laptop access")

    def verify(self):
        host = self.confirmed_host
        if host is None:
            return
        candidate = {**self.profile, "host": host}
        phrase, admin_phrase = self.variables["passphrase"].get(), self.variables["phrase_administrator"].get()

        def operation():
            result = asyncio.run(transport.verify_first_boot(candidate, phrase, admin_phrase or None))
            candidate["stage"] = "verified"
            installer.finish_verification(self.profile_path, candidate)
            return candidate, result

        self.background(operation, self.verified, "Checking laptop access", failure=self.access_failed)

    def access_failed(self, error):
        self.notice(transport.failure_message(error), True)

    def verified(self, value):
        self.profile, _result = value
        self.finish()

    def recovery_page(self):
        parent = self.page(
            "Start the kiosk",
            "Set up offline recovery",
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
        if not password or password != confirmation or any(char in password for char in "\n\r\0:"):
            self.notice("Enter and confirm the same local recovery password, without newlines or colons.", True)
            return

        def saved(_result):
            self.finish()
            self.notice("Recovery password saved. Test keyboard login with Ctrl+Alt+F2, then return with Ctrl+Alt+F1.")

        self.background(
            lambda: asyncio.run(transport.set_recovery_password(self.profile, phrase, password, confirmation)),
            saved,
            "Setting the local console password over verified SSH",
            failure=lambda error: self.notice(
                "Could not set the recovery password. " + transport.failure_message(error), True
            ),
        )

    def finish(self):
        for key in ("passphrase", "phrase_administrator", "recovery_password", "recovery_confirmation"):
            self.variables[key].set("")
        parent = self.page(
            "Start the kiosk",
            "Laptop access verified",
            "Back up your setup folder and keep its passphrase somewhere private. "
            "In Screen Share, select this kiosk and enter its maintenance key passphrase. The screen opens in your browser; click Disconnect when finished. "
            "On the Pi, tap Connect when ready to connect the mill. Opening a USB connection resets the mill.",
        )
        details = profiles.connection_details(self.profile)
        ttk.Label(parent, text=f"Pi address: {details['address']}", style="Mono.TLabel").pack(anchor="w", pady=8)
        self.button(parent, "Download Screen Share", self.download_viewer)
        self.button(parent, "Open setup folder", self.show_folder)
        self.button(parent, "Set up offline recovery (optional)", self.recovery_page)
        advanced = self.advanced(parent, "Connection details")
        for text in (
            f"Address: {details['address']}",
            f"Host: {details['host_fingerprint']}",
            *(
                f"{role.capitalize()}: {item['username']} · {item['key_path']}"
                for role, item in details["accounts"].items()
            ),
        ):
            self.detail(advanced, text)
        self.button(advanced, "Copy connection details", self.copy_details)
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
        self.variables["passphrase"].set("")
        parent = self.page(
            "",
            "Connect to your kiosk",
            "The touchscreen opens in your browser and allows input. Click Disconnect here when you are finished.",
        )
        host = self.profile.get("host", {})
        self.detail(parent, f"Kiosk: {host.get('address', 'Not verified')}")
        self.detail(
            parent,
            host.get("fingerprint", "Choose Continue a saved setup in Carvera Kiosk Setup, then Check laptop access."),
        )
        self.detail(parent, f"Maintenance key: {self.profile['keys']['maintenance']['path']}")
        field(parent, "Maintenance key passphrase", self.variables["passphrase"], secret=True)
        self.actions(
            self.choose_profile,
            self.connect_viewer if self.profile["stage"] == "verified" else None,
            next_text="Connect",
        )
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
            failure=self.viewer_failure,
        )
        self.actions(None, self.cancel, next_text="Disconnect")

    def viewer_failure(self, error):
        self.viewer_page()
        self.notice("Screen sharing ended. " + transport.failure_message(error), True)

    def report(self, value):
        if "bytes" not in value and "percent" not in value:
            self.messages.put(("progress", value))
            return
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
        self.disabled_widgets = []
        pending = list(self.form.body.winfo_children())
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton, ttk.Radiobutton)):
                self.disabled_widgets.append((widget, widget.instate(["disabled"])))
                widget.state(["disabled"])

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
                    if not self.cancel_event.is_set():
                        self.confirm_media(value)
                    continue
                self.notice(PHASES.get(phase, "Working"))
                if hasattr(self, "progress_label") and self.progress_label.winfo_exists():
                    self.progress_label.configure(text=PHASES.get(phase, "Working"))
                    measurable = "percent" in value or ("bytes" in value and value.get("total", 0) > 0)
                    self.progress_bar.stop()
                    if measurable:
                        percent = value.get("percent", 100 * value.get("bytes", 0) / max(1, value.get("total", 1)))
                        self.progress_bar.configure(mode="determinate", value=percent)
                    else:
                        self.progress_bar.configure(mode="indeterminate")
                        self.progress_bar.start()
            else:
                self.busy = False
                for widget, disabled in self.disabled_widgets:
                    if widget.winfo_exists() and not disabled:
                        widget.state(["!disabled"])
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
