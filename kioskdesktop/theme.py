"""Adapt the canonical Slate Workshop presentation to Tk without loading Kivy."""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib.util
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font, ttk


def assets() -> Path:
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "slate"
    return bundled if bundled.is_dir() else Path(__file__).resolve().parents[1] / "carveracontroller"


def canonical():
    spec = importlib.util.spec_from_file_location("slate_presentation", assets() / "ui/theme.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("The Slate Workshop theme is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def colors() -> dict[str, str]:
    module = canonical()
    return {
        name: "#" + "".join(f"{round(channel * 255):02x}" for channel in value[:3])
        for name, value in vars(module).items()
        if name.isupper() and isinstance(value, tuple) and len(value) == 4
    }


_font_library = None


def register_fonts() -> None:
    global _font_library
    files = sorted(path for path in (assets() / "data/fonts").iterdir() if path.suffix.lower() in {".ttf", ".otf"})
    if not files:
        raise RuntimeError("The bundled interface fonts are missing")
    if os.name == "nt":
        library = ctypes.WinDLL("gdi32", use_last_error=True)
        library.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        for path in files:
            if not library.AddFontResourceExW(str(path), 0x10, None):
                raise RuntimeError(f"Could not register {path.name} (Windows error {ctypes.get_last_error()})")
    else:
        library = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
        library.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        library.FcConfigAppFontAddFile.restype = ctypes.c_int
        for path in files:
            if not library.FcConfigAppFontAddFile(None, os.fsencode(path)):
                raise RuntimeError("Could not register a bundled interface font")
    _font_library = library


class Slate:
    def __init__(self, root: tk.Tk):
        self.root = root
        root._slate = self
        self.canonical = canonical()
        self.color = colors()
        c = self.color
        root.configure(background=c["BACKGROUND"])
        available = set(font.families(root))
        if not {"IBM Plex Sans", "IBM Plex Mono"}.issubset(available):
            raise RuntimeError("The bundled IBM Plex fonts were not loaded")
        self.sans = font.Font(root=root, family="IBM Plex Sans", size=12)
        self.bold = font.Font(root=root, family="IBM Plex Sans", size=12, weight="bold")
        self.mono = font.Font(root=root, family="IBM Plex Mono", size=11)
        self.title = font.Font(root=root, family="IBM Plex Sans", size=20, weight="bold")
        self.fallback = (
            font.Font(root=root, family="Noto Sans CJK SC", size=12) if "Noto Sans CJK SC" in available else None
        )
        root.option_add("*insertBackground", c["ACCENT"])
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=c["BACKGROUND"], foreground=c["TEXT"], font=self.sans)
        style.configure("TFrame", background=c["BACKGROUND"])
        style.configure(
            "Panel.TFrame",
            background=c["PANEL"],
            relief="solid",
            borderwidth=1,
            bordercolor=c["BORDER"],
            lightcolor=c["BORDER"],
            darkcolor=c["BORDER"],
        )
        style.configure("TLabel", background=c["BACKGROUND"], foreground=c["TEXT"])
        style.configure("Panel.TLabel", background=c["PANEL"])
        style.configure("Secondary.TLabel", foreground=c["SECONDARY"])
        style.configure("Title.TLabel", font=self.title)
        style.configure("Mono.TLabel", font=self.mono)
        style.configure("Error.TLabel", foreground=c["ERROR"])
        style.configure("Success.TLabel", foreground=c["SUCCESS"])
        style.configure(
            "TButton",
            background=c["CONTROL"],
            foreground=c["TEXT"],
            bordercolor=c["BORDER"],
            lightcolor=c["BORDER"],
            darkcolor=c["BORDER"],
            padding=(16, 12),
            font=self.bold,
            focuscolor=c["ACCENT"],
            focusthickness=2,
        )
        style.map(
            "TButton",
            background=[("disabled", c["PANEL"]), ("pressed", c["SELECTED"]), ("active", c["CONTROL_HOVER"])],
            foreground=[("disabled", c["MUTED"])],
            bordercolor=[("focus", c["ACCENT"])],
        )
        style.configure("Selected.TButton", background=c["SELECTED"], bordercolor=c["ACCENT"])
        style.configure("Danger.TButton", background=c["DANGER"])
        style.map("Danger.TButton", background=[("pressed", c["DANGER"]), ("active", c["DANGER"])])
        style.configure(
            "TEntry",
            fieldbackground=c["FIELD"],
            foreground=c["TEXT"],
            insertcolor=c["ACCENT"],
            bordercolor=c["BORDER"],
            lightcolor=c["BORDER"],
            darkcolor=c["BORDER"],
            padding=12,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", c["ACCENT"]), ("invalid", c["ERROR"])],
            fieldbackground=[("disabled", c["PANEL"])],
            foreground=[("disabled", c["MUTED"])],
        )
        style.configure(
            "TCheckbutton",
            padding=(0, 8),
            indicatorbackground=c["FIELD"],
            indicatorforeground=c["ACCENT"],
            focuscolor=c["ACCENT"],
        )
        style.map("TCheckbutton", background=[("active", c["BACKGROUND"])])
        style.configure(
            "Horizontal.TProgressbar",
            background=c["ACCENT"],
            troughcolor=c["FIELD"],
            bordercolor=c["BORDER"],
            lightcolor=c["ACCENT"],
            darkcolor=c["ACCENT"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=c["FIELD"],
            background=c["CONTROL"],
            foreground=c["TEXT"],
            arrowcolor=c["TEXT"],
            bordercolor=c["BORDER"],
            lightcolor=c["BORDER"],
            darkcolor=c["BORDER"],
            padding=10,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["FIELD"])],
            foreground=[("readonly", c["TEXT"])],
            selectbackground=[("readonly", c["FIELD"])],
            selectforeground=[("readonly", c["TEXT"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=c["CONTROL"],
            troughcolor=c["FIELD"],
            bordercolor=c["BORDER"],
            arrowcolor=c["TEXT"],
            lightcolor=c["BORDER"],
            darkcolor=c["BORDER"],
        )
        root.option_add("*TCombobox*Listbox.background", c["FIELD"])
        root.option_add("*TCombobox*Listbox.foreground", c["TEXT"])
        self.images = []
        self.buttons(style)

    def scale(self, factor):
        for selected, size in (
            (self.sans, 12),
            (self.bold, 12),
            (self.mono, 11),
            (self.title, 20),
            (self.fallback, 12),
        ):
            if selected is not None:
                selected.configure(size=round(size * factor))

    def text_font(self, text, mono=False):
        if self.canonical.font_for(text, mono) == "ARIALUNI" and self.fallback is not None:
            return self.fallback
        return self.mono if mono else self.sans

    def buttons(self, style):
        from PIL import Image, ImageDraw, ImageTk

        c = self.color
        for name, base in (("TButton", "CONTROL"), ("Selected.TButton", "SELECTED"), ("Danger.TButton", "DANGER")):
            pictures = []
            for state in ("normal", "disabled", "pressed", "active", "focus"):
                shade = "PANEL" if state == "disabled" else "SELECTED" if state == "pressed" else base
                if state == "active" and base == "CONTROL":
                    shade = "CONTROL_HOVER"
                texture = Image.open(assets() / "data/theme/button.png").convert("RGBA")
                picture = Image.new("RGBA", texture.size, c[shade])
                picture.putalpha(texture.getchannel("A"))
                border = c["ACCENT"] if state in {"focus", "pressed"} or base == "SELECTED" else c["BORDER"]
                ImageDraw.Draw(picture).rounded_rectangle(
                    (0, 0, picture.width - 1, picture.height - 1), 6, outline=border, width=1
                )
                photo = ImageTk.PhotoImage(picture, master=self.root)
                self.images.append(photo)
                pictures.append(photo)
            element = "Slate" + name.replace(".", "")
            style.element_create(
                element,
                "image",
                pictures[0],
                ("disabled", pictures[1]),
                ("pressed", pictures[2]),
                ("focus", pictures[4]),
                ("active", pictures[3]),
                border=8,
                sticky="nsew",
            )
            style.layout(
                name,
                [
                    (
                        element,
                        {
                            "sticky": "nsew",
                            "children": [
                                (
                                    "Button.padding",
                                    {"sticky": "nsew", "children": [("Button.label", {"sticky": "nsew"})]},
                                )
                            ],
                        },
                    )
                ],
            )


class ScrollForm(ttk.Frame):
    """Keep the wizard footer visible when window size or text scaling changes."""

    def __init__(self, parent, theme: Slate):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=theme.color["BACKGROUND"], highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, padding=16)
        self.window = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.body.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.body.bind_all("<FocusIn>", self.reveal, add=True)
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.body.bind_all(event, self.wheel, add=True)

    def wheel(self, event):
        if str(event.widget).startswith(str(self)):
            direction = (-1 if event.num == 4 else 1) if event.num in {4, 5} else (-1 if event.delta > 0 else 1)
            self.canvas.yview_scroll(direction * 3, "units")

    def reveal(self, event):
        widget = event.widget
        if not str(widget).startswith(str(self.body)) or widget is not self.focus_get():
            return
        self.update_idletasks()
        top = widget.winfo_rooty() - self.body.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible_top = self.canvas.canvasy(0)
        visible_height = self.canvas.winfo_height()
        margin = max(0, min(12, (visible_height - widget.winfo_height()) // 2))
        height = max(1, self.body.winfo_height())
        if top < visible_top:
            self.canvas.yview_moveto(max(0, top - margin) / height)
        elif bottom > visible_top + visible_height:
            self.canvas.yview_moveto(max(0, bottom - visible_height + margin) / height)


def field(parent, label: str, variable: tk.StringVar, *, secret: bool = False) -> ttk.Entry:
    caption = ttk.Label(parent, text=label, wraplength=900)
    caption.pack(anchor="w", fill="x", pady=(12, 6))
    caption.bind("<Configure>", lambda event: caption.configure(wraplength=max(100, event.width)))
    entry = ttk.Entry(parent, textvariable=variable, show="•" if secret else "")
    entry.pack(fill="x")
    theme = getattr(parent.winfo_toplevel(), "_slate", None)
    if theme is not None:

        def update(*_args):
            entry.configure(font=theme.text_font("•" if secret else variable.get()))

        trace = variable.trace_add("write", update)
        entry.bind("<Destroy>", lambda event: variable.trace_remove("write", trace) if event.widget is entry else None)
        update()
    return entry
