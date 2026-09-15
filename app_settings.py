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

import customtkinter as ctk

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


def apply_theme(_app, dark: bool = True) -> None:
    """Delegate appearance switching to CustomTkinter."""
    ctk.set_appearance_mode("dark" if dark else "light")


# App is still declared as App(tk.Tk) in the legacy view during this
# incremental migration. Make that base resolve to CTk without touching the
# non-UI modules; the next UI step can replace the declaration directly.
ctk.set_default_color_theme("blue")
tk.Tk = ctk.CTk
