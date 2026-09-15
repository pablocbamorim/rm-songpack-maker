"""
app_settings.py
----------------
Editor-wide (not songpack-specific) preferences and the Tk/ttk theming
that depends on them.

Preferences live in ~/.rm-songpack-maker/settings.json so they persist
across songpacks and across runs. Biome/biome-tag colours are NOT here:
those belong to a songpack and are stored next to it by
biome_customization.py.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".rm-songpack-maker")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULTS = {
    "double_click_preview": False,
    "dark_theme": True,
}


def load() -> dict:
    """Read the saved preferences, falling back to DEFAULTS for anything
    missing or malformed. Never raises -- a broken settings file must not
    stop the editor from starting.
    """
    settings = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return settings
    if not isinstance(data, dict):
        return settings
    for key, default in DEFAULTS.items():
        value = data.get(key, default)
        if isinstance(value, type(default)):
            settings[key] = value
    return settings


def save(settings: dict) -> None:
    """Write the preferences atomically. Raises OSError on failure so the
    caller can surface it.
    """
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: settings.get(k, v) for k, v in DEFAULTS.items()},
                  f, indent=2)
        f.write("\n")
    os.replace(tmp, SETTINGS_PATH)


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------
DARK = {
    "bg": "#1e1e1e",
    "surface": "#252526",
    "field": "#2d2d30",
    "border": "#3f3f46",
    "fg": "#e6e6e6",
    "muted": "#a0a0a5",
    "accent": "#3b82f6",
    "accent_hover": "#4b8ff7",
    "selected": "#264f78",
    "select_fg": "#ffffff",
}

LIGHT = {
    "bg": "#f2f2f2",
    "surface": "#e6e6e6",
    "field": "#ffffff",
    "border": "#c3c3c3",
    "fg": "#1b1b1b",
    "muted": "#5c5c5c",
    "accent": "#3b82f6",
    "accent_hover": "#5a9bf8",
    "selected": "#cfe3ff",
    "select_fg": "#10233d",
}


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def apply_theme(app, dark: bool = True) -> None:
    """Apply the light or dark palette to every existing widget, and set
    the option database so widgets created later pick it up too. Safe to
    call repeatedly (that's how the Settings tab toggles live).
    """
    p = palette(dark)

    style = ttk.Style(app)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=p["bg"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], troughcolor=p["field"])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("TLabelframe", background=p["bg"],
                    foreground=p["fg"], bordercolor=p["border"])
    style.configure("TLabelframe.Label",
                    background=p["bg"], foreground=p["fg"])
    style.configure("TButton", background=p["field"], foreground=p["fg"],
                    bordercolor=p["border"], padding=(8, 4), focuscolor=p["border"])
    style.map("TButton",
              background=[("active", p["accent_hover"]),
                          ("pressed", p["accent"])],
              foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
    style.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"], insertcolor=p["fg"],
                    bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"])
    style.configure("TSpinbox", fieldbackground=p["field"], foreground=p["fg"],
                    background=p["field"], arrowcolor=p["fg"], bordercolor=p["border"])
    style.configure("TCombobox", fieldbackground=p["field"], foreground=p["fg"],
                    background=p["field"], arrowcolor=p["fg"], bordercolor=p["border"])
    style.map("TCombobox",
              fieldbackground=[("readonly", p["field"])],
              foreground=[("readonly", p["fg"])],
              background=[("readonly", p["field"])])
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"],
                    indicatorcolor=p["field"])
    style.map("TCheckbutton", background=[("active", p["bg"])],
              foreground=[("active", p["fg"])],
              indicatorcolor=[("selected", p["accent"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"],
                    indicatorcolor=p["field"])
    style.map("TRadiobutton", background=[("active", p["bg"]),],
              foreground=[("active", p["fg"])],
              indicatorcolor=[("selected", p["accent"])])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
    style.configure("TNotebook.Tab", background=p["surface"], foreground=p["muted"],
                    padding=(12, 6), bordercolor=p["border"])
    style.map("TNotebook.Tab",
              background=[("selected", p["field"]), ("active", p["surface"])],
              foreground=[("selected", p["fg"]), ("active", p["fg"])])
    style.configure("Treeview", background=p["field"], fieldbackground=p["field"],
                    foreground=p["fg"], bordercolor=p["border"], rowheight=25)
    style.map("Treeview", background=[("selected", p["selected"])],
              foreground=[("selected", p["select_fg"])])
    style.configure("Treeview.Heading", background=p["surface"], foreground=p["fg"],
                    bordercolor=p["border"], relief="flat")
    style.map("Treeview.Heading", background=[("active", p["field"])])
    style.configure("TScale", background=p["bg"], troughcolor=p["field"])
    style.configure("Vertical.TScrollbar", background=p["field"], troughcolor=p["bg"],
                    bordercolor=p["bg"], arrowcolor=p["fg"])
    style.configure("Horizontal.TScrollbar", background=p["field"], troughcolor=p["bg"],
                    bordercolor=p["bg"], arrowcolor=p["fg"])

    app.configure(background=p["bg"])

    # Widgets created *after* this call (dialogs, rebuilt editors, ...).
    app.option_add("*TCombobox*Listbox.background", p["field"])
    app.option_add("*TCombobox*Listbox.foreground", p["fg"])
    app.option_add("*TCombobox*Listbox.selectBackground", p["selected"])
    app.option_add("*TCombobox*Listbox.selectForeground", p["select_fg"])
    app.option_add("*Listbox.background", p["field"])
    app.option_add("*Listbox.foreground", p["fg"])
    app.option_add("*Listbox.selectBackground", p["selected"])
    app.option_add("*Listbox.selectForeground", p["select_fg"])
    app.option_add("*Text.background", p["field"])
    app.option_add("*Text.foreground", p["fg"])
    app.option_add("*Text.insertBackground", p["fg"])
    app.option_add("*Toplevel.background", p["bg"])
    app.option_add("*Menu.background", p["surface"])
    app.option_add("*Menu.foreground", p["fg"])
    app.option_add("*Menu.activeBackground", p["accent"])
    app.option_add("*Menu.activeForeground", "#ffffff")

    # Widgets that already exist (plain tk ones don't follow ttk styles).
    _retint_tree(app, p)


def _retint_tree(widget, p: dict) -> None:
    for child in widget.winfo_children():
        _retint_one(child, p)
        _retint_tree(child, p)


def _retint_one(widget, p: dict) -> None:
    try:
        if isinstance(widget, tk.Listbox):
            widget.configure(background=p["field"], foreground=p["fg"],
                             selectbackground=p["selected"], selectforeground=p["select_fg"],
                             highlightbackground=p["border"], highlightcolor=p["border"],
                             relief="flat", borderwidth=1)
        elif isinstance(widget, tk.Text):
            widget.configure(background=p["field"], foreground=p["fg"], insertbackground=p["fg"],
                             highlightbackground=p["border"], highlightcolor=p["border"],
                             relief="flat", borderwidth=1)
        elif isinstance(widget, tk.Canvas):
            widget.configure(background=p["bg"], highlightbackground=p["border"],
                             highlightcolor=p["border"])
        elif isinstance(widget, tk.Menu):
            widget.configure(background=p["surface"], foreground=p["fg"],
                             activebackground=p["accent"], activeforeground="#ffffff",
                             borderwidth=0)
        elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
            widget.configure(background=p["bg"], foreground=p["fg"],
                             activebackground=p["bg"], activeforeground=p["fg"],
                             selectcolor=p["field"], highlightthickness=0)
        elif isinstance(widget, (tk.Label, tk.Button)):
            widget.configure(background=p["bg"], foreground=p["fg"])
        elif isinstance(widget, (tk.Frame, tk.Toplevel, tk.LabelFrame)):
            widget.configure(background=p["bg"])
    except tk.TclError:
        # Colour swatches and other deliberately-coloured widgets are
        # allowed to refuse; theming is cosmetic and must never crash.
        pass