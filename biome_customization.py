"""
biome_customization.py
-----------------------
Small, dependency-free helpers for the custom biome/biome-tag colour
feature. This module intentionally does NOT touch tkinter widgets or
monkey-patch the App/LibraryTab classes -- the editor UI and the
load/save/new wiring live directly in app_core.py so there's exactly one
place that builds the Biome editor and exactly one place that owns
App's load/save/new lifecycle.
"""

from __future__ import annotations

import colorsys
import json
import os
import tempfile

CONFIG_FILENAME = "biome_customization.json"


def default_color(name: str, is_tag: bool = False) -> str:
    """Return a deterministic readable color for a biome/tag name."""
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

    def clean(value):
        if not isinstance(value, dict):
            return {}
        return {
            str(k): str(v).lower()
            for k, v in value.items()
            if valid_color(v)
        }

    return clean(data.get("biomes", {})), clean(data.get("biome_tags", {}))


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
