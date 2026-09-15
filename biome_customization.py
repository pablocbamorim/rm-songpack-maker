"""
biome_customization.py
-----------------------
Small, dependency-free helpers for the custom biome/biome-tag colour
feature. This module intentionally does NOT touch tkinter widgets or
monkey-patch the App/LibraryTab classes -- the editor UI and the
load/save/new wiring live directly in app_core.py so there's exactly one
place that builds the Biome editor and exactly one place that owns
App's load/save/new lifecycle.

There are two separate colour stores, and it's important to keep them
distinct:

  * Per-songpack overrides (`load`/`save` below) -- written to
    `biome_customization.json` next to a specific songpack's
    ReactiveMusic.yaml. These only affect that one songpack.

  * Bundled app defaults (`load_app_defaults`/`save_app_default_color`
    below) -- written to `default_biome_colors.json` next to this
    script. This ships WITH the editor, so it's what every new songpack,
    for every user who has this file (i.e. once it's committed to the
    project repo), starts out seeing. `default_color()` checks this
    before falling back to the hash-based algorithmic colour.
"""

from __future__ import annotations

import colorsys
import json
import os
import sys
import tempfile

CONFIG_FILENAME = "biome_customization.json"
APP_DEFAULTS_FILENAME = "default_biome_colors.json"

# (biomes_dict, tags_dict) or None if not loaded yet
_app_defaults_cache = None


def _bundled_defaults_path() -> str:
    """Where the app-wide default colour file lives, in both a source
    checkout and a PyInstaller-frozen build (mirrors main.py's icon
    lookup so both refer to the same bundle).
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, APP_DEFAULTS_FILENAME)


def _clean_color_map(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v).lower() for k, v in value.items() if valid_color(v)}


def load_app_defaults(force_reload: bool = False):
    """Load (biomes, tags) dicts from the bundled default-colours file.
    Cached after the first read since this is consulted on every
    default_color() call; pass force_reload=True after writing to it.
    """
    global _app_defaults_cache
    if _app_defaults_cache is not None and not force_reload:
        return _app_defaults_cache
    try:
        with open(_bundled_defaults_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _app_defaults_cache = (
        _clean_color_map(data.get("biomes", {})),
        _clean_color_map(data.get("biome_tags", {})),
    )
    return _app_defaults_cache


def save_app_default_color(name: str, is_tag: bool, color: str) -> str:
    """Persist one biome/tag colour into the bundled defaults file so it
    becomes the default for every songpack, for anyone using this copy
    of the editor once the file is committed to the project's repo.
    Returns the path written, so the caller can point the user at it.
    """
    path = _bundled_defaults_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}

    key = "biome_tags" if is_tag else "biomes"
    section = data.get(key, {})
    if not isinstance(section, dict):
        section = {}
    section[str(name)] = color.lower()
    data[key] = section

    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".default_biome_colors_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "biomes": dict(sorted(data.get("biomes", {}).items(), key=lambda x: x[0].lower())),
                    "biome_tags": dict(sorted(data.get("biome_tags", {}).items(), key=lambda x: x[0].lower())),
                },
                f, indent=2, ensure_ascii=False,
            )
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    load_app_defaults(force_reload=True)
    return path


def remove_app_default_color(name: str, is_tag: bool) -> None:
    """Drop a name from the bundled defaults file (falls back to the
    algorithmic colour again). No-op if it wasn't there.
    """
    path = _bundled_defaults_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return
    if not isinstance(data, dict):
        return
    key = "biome_tags" if is_tag else "biomes"
    section = data.get(key, {})
    if isinstance(section, dict) and name in section:
        del section[name]
        data[key] = section
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    load_app_defaults(force_reload=True)


def is_bundled_default(name: str, is_tag: bool) -> bool:
    biomes, tags = load_app_defaults()
    return name in (tags if is_tag else biomes)


def default_color(name: str, is_tag: bool = False) -> str:
    """Return the colour a biome/tag should show when no per-songpack
    override exists: the bundled app default if one has been set, else a
    deterministic (but arbitrary) colour derived from the name.
    """
    biomes, tags = load_app_defaults()
    bundled = (tags if is_tag else biomes).get(name)
    if bundled:
        return bundled

    hue = (sum((i + 1) * ord(c) for i, c in enumerate(name)) % 360) / 360.0
    saturation = 0.62 if is_tag else 0.58
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, 0.92)
    return "#%02x%02x%02x" % (
        round(r * 255), round(g * 255), round(b * 255)
    )


def valid_color(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def load(folder: str):
    """Load (custom_biomes, custom_tags) dicts from a songpack folder.
    Missing/invalid files just yield empty customization -- this must
    never prevent a songpack from loading.
    """
    try:
        with open(os.path.join(folder, CONFIG_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}

    return _clean_color_map(data.get("biomes", {})), _clean_color_map(data.get("biome_tags", {}))


def save(folder: str, biomes: dict, tags: dict) -> None:
    """Write biome_customization.json into the songpack folder, atomically."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, CONFIG_FILENAME)
    fd, tmp = tempfile.mkstemp(
        prefix=".biome_customization_", suffix=".tmp", dir=folder
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "biomes": dict(sorted(biomes.items(), key=lambda x: x[0].lower())),
                    "biome_tags": dict(sorted(tags.items(), key=lambda x: x[0].lower())),
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
