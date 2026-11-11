"""Slate Workshop desktop shell and packaged visual verification screens."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from kioskdesktop.theme import ScrollForm, Slate, field, register_fonts


class Application:
    def __init__(self, root: tk.Tk, viewer=False):
        self.root, self.viewer = root, viewer
        self.theme = Slate(root)
        root.title("Carvera Kiosk Screen Share" if viewer else "Carvera Kiosk Setup")
        root.geometry("1080x760")
        root.minsize(600, 400)
        self.variables = {
            name: tk.StringVar(value=value)
            for name, value in {
                "hostname": "carvera-pi",
                "ssid": "",
                "country": "US",
                "password": "",
                "passphrase": "",
                "confirmation": "",
                "host": "",
                "key": "",
            }.items()
        }
        header = ttk.Frame(root, padding=(24, 20))
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        title = ttk.Label(header, text="Screen Share" if viewer else "Kiosk Setup", style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")
        brand = ttk.Label(header, text="Carvera · Slate Workshop", style="Secondary.TLabel")
        brand.grid(row=0, column=1, sticky="e")
        text_size = ttk.Combobox(header, values=("100%", "125%", "150%"), state="readonly", width=6)
        self.text_size = text_size
        text_size.set("100%")
        text_size.grid(row=0, column=2, sticky="e", padx=(16, 0))

        def fit_header(event):
            if title.winfo_reqwidth() + brand.winfo_reqwidth() + text_size.winfo_reqwidth() + 80 > event.width:
                brand.grid_remove()
            else:
                brand.grid()

        header.bind("<Configure>", fit_header)
        text_size.bind("<<ComboboxSelected>>", lambda _event: self.theme.scale(int(text_size.get()[:-1]) / 100))
        self.navigation = ttk.Frame(root, padding=(24, 0, 24, 12))
        self.navigation.pack(fill="x")
        self.current_step = "Choose a card"
        if not viewer:
            for name in ("Choose a card", "Set up your Pi", "Write the card", "Start the kiosk"):
                label = ttk.Label(
                    self.navigation,
                    text=name,
                    foreground=self.theme.color["ACCENT"]
                    if name == self.current_step
                    else self.theme.color["SECONDARY"],
                )
                label.grid(row=0, column=len(self.navigation.winfo_children()) - 1, sticky="w", padx=(0, 24))

            def fit_navigation(_event):
                width = max(1, self.navigation.winfo_width() - 48)
                compact = sum(label.winfo_reqwidth() + 24 for label in self.navigation.winfo_children()) > width
                for label in self.navigation.winfo_children():
                    if compact and label.cget("text") != self.current_step:
                        label.grid_remove()
                    else:
                        label.grid()

            self.fit_navigation = fit_navigation
            self.navigation.bind("<Configure>", fit_navigation)
            for label in self.navigation.winfo_children():
                label.bind("<Configure>", fit_navigation)
        self.form = ScrollForm(root, self.theme)
        self.footer = ttk.Frame(root, padding=(24, 16))
        self.footer.pack(side="bottom", fill="x")
        self.form.pack(fill="both", expand=True, padx=8)
        self.status = ttk.Label(self.footer, text="Your existing card can remain unchanged.", style="Secondary.TLabel")
        self.status.pack(fill="x", pady=(0, 10))
        self.footer.bind("<Configure>", lambda event: self.status.configure(wraplength=max(200, event.width - 48)))
        actions = ttk.Frame(self.footer)
        actions.pack(fill="x")
        actions.columnconfigure(0, weight=1)
        self.back = ttk.Button(actions, text="Back")
        self.back.grid(row=0, column=0, sticky="e", padx=8)
        self.next = ttk.Button(actions, text="Continue", style="Selected.TButton")
        self.next.grid(row=0, column=1, sticky="e")

        def fit_actions(_event):
            stacked = self.back.winfo_reqwidth() + self.next.winfo_reqwidth() + 16 > actions.winfo_width()
            row, column = (1, 0) if stacked else (0, 1)
            if (int(self.next.grid_info()["row"]), int(self.next.grid_info()["column"])) != (row, column):
                self.next.grid(row=row, column=column)

        actions.bind("<Configure>", fit_actions)
        self.back.bind("<Configure>", fit_actions)
        self.next.bind("<Configure>", fit_actions)
        self.show_viewer() if viewer else self.show_network()

    def clear(self):
        for child in self.form.body.winfo_children():
            child.destroy()

    def set_step(self, step):
        self.current_step = step
        for child in self.navigation.winfo_children():
            child.configure(
                foreground=self.theme.color["ACCENT"] if child.cget("text") == step else self.theme.color["SECONDARY"]
            )
        if hasattr(self, "fit_navigation"):
            self.fit_navigation(None)

    def panel(self, title: str, explanation: str):
        self.clear()
        parent = self.form.body
        ttk.Label(parent, text=title, font=self.theme.bold).pack(anchor="w", pady=(0, 8))
        text = ttk.Label(parent, text=explanation, style="Secondary.TLabel", wraplength=900, justify="left")
        text.pack(anchor="w", fill="x", pady=(0, 16))
        text.bind("<Configure>", lambda event: text.configure(wraplength=max(200, event.width - 32)))
        return parent

    def show_network(self):
        self.set_step("Set up your Pi")
        parent = self.panel(
            "Set up your Pi",
            "Name your Pi and choose how it will join your network.",
        )
        network = ttk.Combobox(parent, values=("Wi-Fi", "Ethernet"), state="readonly")
        network.current(0)
        network.pack(fill="x", pady=(0, 8))
        for key, label in (
            ("hostname", "Pi name"),
            ("ssid", "Wi-Fi network name"),
            ("country", "Two-letter country code"),
        ):
            field(parent, label, self.variables[key])
        field(parent, "Wi-Fi password", self.variables["password"], secret=True)
        ttk.Label(
            parent, text="The password is removed from the card after successful setup.", style="Secondary.TLabel"
        ).pack(anchor="w", pady=12)

    def show_erase(self):
        self.set_step("Write the card")
        parent = self.panel(
            "Erase this card?",
            "Everything on the selected card will be erased. Keep your current kiosk card for recovery.",
        )
        panel = ttk.Frame(parent, style="Panel.TFrame", padding=20)
        panel.pack(fill="x", pady=12)
        for label in ("Selected card: USB SD Card Reader", "Capacity: 32 GB", "Existing volume: bootfs"):
            ttk.Label(panel, text=label, style="Panel.TLabel").pack(anchor="w", pady=4)
        ttk.Label(
            parent, text="This screen is a design preview. It cannot write to a card.", style="Error.TLabel"
        ).pack(anchor="w", pady=16)
        self.agreement = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Erase all contents of this card", variable=self.agreement).pack(
            anchor="w", pady=12
        )
        self.next.configure(text="Erase and write card", style="Danger.TButton", state="disabled")

    def show_viewer(self):
        parent = self.panel(
            "Connect to your kiosk",
            "Use the maintenance key created during setup. Screen sharing allows control of the touchscreen.",
        )
        field(parent, "Kiosk address", self.variables["host"])
        field(parent, "Maintenance key", self.variables["key"])
        field(parent, "Key passphrase", self.variables["passphrase"], secret=True)
        ttk.Label(
            parent,
            text="The host identity must match the fingerprint you verified on the Pi.",
            style="Secondary.TLabel",
        ).pack(anchor="w", pady=20)
        self.status.configure(text="Disconnected")
        self.back.configure(text="Choose profile")
        self.next.configure(text="Connect", state="disabled")

    def capture(self, target: str):
        """Capture only this owned verification window, then close it."""
        from PIL import ImageGrab

        self.root.update_idletasks()
        box = (
            self.root.winfo_rootx(),
            self.root.winfo_rooty(),
            self.root.winfo_rootx() + self.root.winfo_width(),
            self.root.winfo_rooty() + self.root.winfo_height(),
        )
        if self.root.tk.call("tk", "windowingsystem") == "win32":
            ImageGrab.grab(window=self.root.winfo_id()).save(target)
        else:
            ImageGrab.grab(bbox=box).save(target)
        Path(target).with_suffix(".json").write_text(
            json.dumps(
                {
                    "fonts": {"sans": self.theme.sans.actual(), "mono": self.theme.mono.actual()},
                    "size": [self.root.winfo_width(), self.root.winfo_height()],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.root.destroy()


def launch(viewer=False, design_slice=None, capture=None):
    register_fonts()
    root = tk.Tk()
    if not design_slice:
        from kioskdesktop.elevation import elevated

        if elevated():
            Slate(root)
            root.title("Carvera Kiosk Setup")
            frame = ttk.Frame(root, padding=24)
            frame.pack(fill="both", expand=True)
            ttk.Label(
                frame,
                text="Open this app from your normal desktop account.\nGrant administrator permission only when Setup asks to work on a card.",
                wraplength=600,
            ).pack(pady=16)
            ttk.Button(frame, text="Close", command=root.destroy).pack(anchor="e")
            root.mainloop()
            return
    if design_slice:
        app = Application(root, viewer=viewer or design_slice == "viewer")
    else:
        from kioskdesktop.wizard import Wizard

        app = Wizard(root, viewer_mode=viewer)
    if design_slice == "setup":
        app.variables["ssid"].set("Workshop 工作室")
    if design_slice == "erase":
        app.show_erase()
    if capture:
        if not design_slice:
            raise ValueError("Captures require an explicit design slice")
        root.after(1000, lambda: app.capture(capture))
    root.mainloop()
