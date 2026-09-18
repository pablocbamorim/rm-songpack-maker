"""
app_settings.py
----------------
Editor-wide (not songpack-specific) preferences.

Preferences live in ~/.rm-songpack-maker/settings.json so they persist
across songpacks and across runs. Biome/biome-tag colours are NOT here:
those belong to a songpack and are stored next to it by
biome_customization.py.

UI appearance is handled by CustomTkinter. This module only owns persisted
settings and provides the compatibility hook used by the existing App while
the view layer is migrated incrementally.
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import ttk

import customtkinter as ctk

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".rm-songpack-maker")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULTS = {
    "double_click_preview": False,
    "dark_theme": True,
    # Preview playback gain (0.0-1.0). Shared by the song list's Preview
    # button and the audio editor's volume slider; it only ever changes
    # the output stream, never a file on disk.
    "preview_volume": 1.0,
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
# ttk theming bridge
#
# CustomTkinter's appearance mode does not reach plain ttk widgets, and the
# editor deliberately keeps three ttk.Treeviews (song list, priority order,
# biome colors) because CTk has no equivalent. This maps CTk's own theme
# colors onto ttk styles so the two halves match.
# ---------------------------------------------------------------------------

def _mode_color(value, dark: bool):
    """CTk theme values are either a single color or [light, dark]."""
    if isinstance(value, (list, tuple)):
        return value[1 if dark else 0]
    return value


def treeview_palette(dark: bool) -> dict:
    """Pull the relevant colors out of CustomTkinter's active theme so the
    Treeviews track whatever color theme is set, not a hardcoded palette.
    """
    theme = ctk.ThemeManager.theme
    frame = theme["CTkFrame"]
    button = theme["CTkButton"]
    label = theme["CTkLabel"]

    text = _mode_color(label.get("text_color", ["gray10", "gray90"]), dark)
    return {
        "background": _mode_color(frame["fg_color"], dark),
        "foreground": text,
        "heading_bg": _mode_color(frame.get("top_fg_color", frame["fg_color"]), dark),
        "heading_fg": text,
        "heading_active": _mode_color(button["hover_color"], dark),
        "selected_bg": _mode_color(button["fg_color"], dark),
        "selected_fg": _mode_color(button.get("text_color", "#ffffff"), dark),
        "border": _mode_color(frame["border_color"], dark),
        "muted": "gray70" if dark else "gray40",
    }


def apply_ttk_theme(widget, dark: bool = True) -> None:
    """Restyle every ttk widget in the app to match the current CTk
    appearance mode. Safe to call as often as you like.
    """
    style = ttk.Style(widget)

    # 'vista'/'xpnative' (Windows default) and 'aqua' (macOS) ignore
    # background/fieldbackground on Treeview. 'clam' honours them.
    if style.theme_use() not in ("clam", "alt", "default"):
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

    p = treeview_palette(dark)

    style.configure(
        "Treeview",
        background=p["background"],
        fieldbackground=p["background"],
        foreground=p["foreground"],
        bordercolor=p["border"],
        borderwidth=0,
        rowheight=24,
    )
    style.map(
        "Treeview",
        background=[("selected", p["selected_bg"])],
        foreground=[("selected", p["selected_fg"])],
    )
    style.configure(
        "Treeview.Heading",
        background=p["heading_bg"],
        foreground=p["heading_fg"],
        relief="flat",
        borderwidth=0,
        padding=(6, 4),
    )
    style.map(
        "Treeview.Heading",
        background=[("active", p["heading_active"])],
    )
    style.layout("Treeview", [
        ("Treeview.treearea", {"sticky": "nswe"}),  # drop the sunken border
    ])

    # --- surrounding ttk widgets (temporary: steps 5 & 6 replace most of
    # these with CTk equivalents, at which point these rules can go) ------
    style.configure("TFrame", background=p["background"])
    style.configure("TLabel", background=p["background"],
                    foreground=p["foreground"])
    style.configure("Muted.TLabel", background=p["background"],
                    foreground=p["muted"])
    style.configure("TLabelframe", background=p["background"],
                    bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["background"],
                    foreground=p["foreground"])
    style.configure("TCheckbutton", background=p["background"],
                    foreground=p["foreground"])
    style.map("TCheckbutton", background=[("active", p["background"])])
    style.configure("TButton", background=p["heading_bg"],
                    foreground=p["foreground"], borderwidth=0, padding=(8, 4))
    style.map("TButton", background=[("active", p["heading_active"])])
    style.configure("TEntry", fieldbackground=p["background"],
                    foreground=p["foreground"], bordercolor=p["border"])
    style.configure("Vertical.TScrollbar", background=p["heading_bg"],
                    troughcolor=p["background"], bordercolor=p["border"],
                    arrowcolor=p["foreground"])

    _restyle_classic_widgets(widget, p)


def _restyle_classic_widgets(widget, palette: dict) -> None:
    """ttk.Style can't reach plain tk widgets (Canvas, Text, Menu), so walk
    the tree and set their colors directly.
    """
    for child in widget.winfo_children():
        try:
            if isinstance(child, tk.Label):  # e.g. the color swatch
                child.configure(bg=child.cget("bg") or palette["background"])
        except tk.TclError:
            pass
        _restyle_classic_widgets(child, palette)
