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

Biome map attributes (temperature / humidity / erosion / weirdness, each in
[-1, 1]) live in the SAME two files, under a "biome_attributes" key, so they
travel with the colours: bundled values in `default_biome_colors.json`,
per-songpack additions/overrides in `biome_customization.json`. They drive
the Biome Map chart (see biome_chart.py).

BIOME TAGS ARE MEMBERSHIP LISTS, NOT COLOURS
--------------------------------------------
In `default_biome_colors.json`, "biome_tags" maps each tag to the list of
biomes it contains:

    "biome_tags": {"IS_HOT": ["desert", "badlands", ...], ...}

A tag therefore has no colour of its own any more; its colour is the average
of the colours of the biomes it holds (`tag_color`), and its position and
shape on the tag map come from the average of their chart attributes
(`tag_attributes`). The per-songpack `biome_customization.json` is unchanged:
its "biome_tags" is still {tag: "#rrggbb"} and, when present, overrides the
averaged colour. An old-style bundled file (tag -> colour string) still loads;
its colours are honoured before the average.
"""

from __future__ import annotations

import colorsys
import json
import math
import os
import sys
import tempfile

CONFIG_FILENAME = "biome_customization.json"
APP_DEFAULTS_FILENAME = "default_biome_colors.json"

#: Keys of one biome's chart attributes, each a float in [-1, 1].
ATTRIBUTE_KEYS = ("temperature", "humidity", "erosion", "weirdness")

# (biomes_dict, tags_dict) or None if not loaded yet
_app_defaults_cache = None
# {name: {temperature, humidity, erosion, weirdness}} or None if not loaded
_app_attributes_cache = None
# {biome_name: "minecraft:overworld"|...} or None if not loaded yet
_app_dimensions_cache = None
# {tag_name: [biome_name, ...]} or None if not loaded yet
_app_tag_members_cache = None


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
    """Load (biomes, tags) *colour* dicts from the bundled defaults file.
    Cached after the first read since this is consulted on every
    default_color() call; pass force_reload=True after writing to it.

    The tags dict is only filled by an old-style file whose "biome_tags"
    values are colour strings. In the current format they are biome lists
    (see load_app_tag_members), so it comes back empty and a tag's colour
    is averaged from its biomes instead (see tag_color).
    """
    global _app_defaults_cache, _app_attributes_cache, _app_dimensions_cache
    global _app_tag_members_cache
    if force_reload:
        # All four caches read the same file, so a forced reload has to
        # drop all of them -- otherwise editing e.g. biome_dimensions
        # would leave stale colours in _app_defaults_cache.
        _app_attributes_cache = None
        _app_dimensions_cache = None
        _app_tag_members_cache = None
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


def _clean_attribute_map(value) -> dict:
    """{name: {temperature, humidity, erosion, weirdness}}, dropping
    malformed entries and clamping every number into [-1, 1].
    """
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for name, attrs in value.items():
        if not isinstance(attrs, dict):
            continue
        try:
            cleaned[str(name)] = {
                key: max(-1.0, min(1.0, float(attrs.get(key, 0.0))))
                for key in ATTRIBUTE_KEYS
            }
        except (TypeError, ValueError):
            continue
    return cleaned


def load_app_attributes(force_reload: bool = False) -> dict:
    """Bundled biome chart attributes from default_biome_colors.json."""
    global _app_attributes_cache
    if _app_attributes_cache is not None and not force_reload:
        return _app_attributes_cache
    try:
        with open(_bundled_defaults_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _app_attributes_cache = _clean_attribute_map(
        data.get("biome_attributes", {}))
    return _app_attributes_cache


def _clean_dimension_map(value) -> dict:
    """{biome_name: dimension_id}, dropping anything that isn't a
    non-empty string. Same tolerant-of-malformed-input stance as the
    colour and attribute loaders.
    """
    if not isinstance(value, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in value.items()
        if isinstance(v, str) and v
    }


def load_app_dimensions(force_reload: bool = False) -> dict:
    """Bundled biome -> dimension mapping from default_biome_colors.json.

    Used by the Biome Map's dimension filter (see app_core.py). Custom
    biomes added through the editor have no entry here, which is why
    they only show up under the 'All' filter on the map.
    """
    global _app_dimensions_cache
    if _app_dimensions_cache is not None and not force_reload:
        return _app_dimensions_cache
    try:
        with open(_bundled_defaults_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _app_dimensions_cache = _clean_dimension_map(
        data.get("biome_dimensions", {}))
    return _app_dimensions_cache


def _clean_tag_members(value) -> dict:
    """{tag: [biome, ...]}, keeping only list-valued entries. A string value
    is an old-style colour (handled by _clean_color_map), not a membership.
    """
    if not isinstance(value, dict):
        return {}
    return {
        str(tag): [str(b) for b in biomes if isinstance(b, str) and b]
        for tag, biomes in value.items()
        if isinstance(biomes, (list, tuple))
    }


def load_app_tag_members(force_reload: bool = False) -> dict:
    """Bundled biome-tag membership: {"IS_HOT": ["desert", ...], ...}."""
    global _app_tag_members_cache
    if _app_tag_members_cache is not None and not force_reload:
        return _app_tag_members_cache
    try:
        with open(_bundled_defaults_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _app_tag_members_cache = _clean_tag_members(data.get("biome_tags", {}))
    return _app_tag_members_cache


def all_tag_names(custom_members: dict | None = None,
                  custom_colors: dict | None = None) -> list:
    """Return every biome-tag name the editor can offer.

    The bundled membership table is the canonical built-in source because it
    is also what the Biome Tag map renders. Empty membership lists are kept:
    they are valid BIOMETAG= targets even when no known biome currently uses
    them. Per-songpack membership additions and tag colour overrides are
    appended as custom names so either kind of customization remains writable
    through the condition editor.
    """
    names = list(load_app_tag_members())
    for source in (custom_members or {}, custom_colors or {}):
        for name in source:
            if name not in names:
                names.append(name)
    return names



def _norm_tag(name: str) -> str:
    """'IS_HOT', 'is_hot' and 'HOT' are the same tag (the IS_ prefix is
    optional in ReactiveMusic). Mirrors simulation.normalize_tag.
    """
    text = str(name).strip().upper()
    return text[3:] if text.startswith("IS_") else text


def tag_members(name: str, custom: dict | None = None) -> list:
    """The biomes a tag contains: bundled membership plus any per-songpack
    additions from the custom-biome tag picker. The IS_ prefix is still
    optional when looking up either source.
    """
    table = load_app_tag_members()
    members = list(table.get(name, []))
    key = _norm_tag(name)
    if name not in table:
        for tag, biomes in table.items():
            if _norm_tag(tag) == key:
                members = list(biomes)
                break
    if custom:
        extra = custom.get(name)
        if extra is None:
            for tag, biomes in custom.items():
                if _norm_tag(tag) == key:
                    extra = biomes
                    break
        if extra:
            members.extend(b for b in extra if b not in members)
    return members


def tag_attributes(biome_attrs: dict, custom: dict | None = None) -> dict:
    """Chart attributes for every tag, averaged over the biomes it contains.

    Returns {tag: {temperature, humidity, erosion, weirdness}}, ready to hand
    to the Biome Map chart exactly like biome attributes:

      * temperature, humidity -> plain average (where the icon sits),
      * erosion               -> plain average (lobe depth E),
      * weirdness             -> round(average) (lobe count f).

    Weirdness is rounded (half up, matching biome_chart.weirdness_to_freq)
    to a whole number before the chart applies f = round(4*w + 4), so a tag
    ends up with 0, 4 or 8 lobes rather than the finer 0..8 a single biome
    can have. To give tags the full range instead, drop the rounding line.

    A tag with no members carrying known chart attributes -- including an
    EMPTY membership list, which the bundled JSON deliberately keeps for
    compatibility tags such as "IS_MAGICAL" or "HIDDEN_FROM_LOCATOR_SELECTION"
    that ship with zero vanilla biomes and only get populated per-modpack --
    still gets an entry here, centred at (0, 0, 0, 0) rather than being left
    out. It has to stay visible and clickable: a modpack can add biomes that
    carry the tag even though this editor has no chart data for them, and
    the tag map is how a songpack author writes a BIOMETAG= condition for it
    without typing the name by hand. Dropping the tag here would hide it
    from the Biome Tag map (and, via biome_case_editor's biome-first cases,
    from right-click editing) even though it is a perfectly valid condition.
    """
    members = {tag: list(biomes) for tag, biomes in load_app_tag_members().items()}
    if custom:
        for tag, biomes in custom.items():
            key = next((existing for existing in members
                        if _norm_tag(existing) == _norm_tag(tag)), None)
            if key is None:
                members[tag] = list(biomes)
            else:
                members[key].extend(b for b in biomes if b not in members[key])
    result = {}
    for tag, biomes in members.items():
        rows = [biome_attrs[b] for b in biomes if b in biome_attrs]
        if not rows:
            result[tag] = {key: 0.0 for key in ATTRIBUTE_KEYS}
            continue
        count = len(rows)
        avg = {key: sum(r[key] for r in rows) /
               count for key in ATTRIBUTE_KEYS}
        avg["weirdness"] = float(math.floor(avg["weirdness"] + 0.5))
        result[tag] = avg
    return result


def average_color(colors) -> str | None:
    """Per-channel RGB mean of '#rrggbb' strings, or None if none are valid."""
    rgb = [
        (int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16))
        for c in colors if valid_color(c)
    ]
    if not rgb:
        return None
    count = len(rgb)
    return "#%02x%02x%02x" % tuple(round(sum(ch) / count) for ch in zip(*rgb))


def tag_color(name: str, biome_color=None, custom: dict | None = None) -> str | None:
    """A tag's colour: the average of the colours of the biomes it contains.

    `biome_color(biome_name) -> "#rrggbb"` decides what each member's colour
    is. The default is the bundled colour (default_color); the editor passes
    its own lookup so a songpack's recoloured biomes are reflected too.
    Returns None for a tag with no known members.
    """
    members = tag_members(name, custom)
    if not members:
        return None
    pick = biome_color or (lambda biome: default_color(biome, False))
    return average_color([pick(b) for b in members])


def all_attributes(custom: dict | None = None) -> dict:
    """Every biome the chart can draw: the bundled attributes, with the
    current songpack's own entries (`custom`) added on top / overriding.
    """
    merged = dict(load_app_attributes())
    if custom:
        merged.update(custom)
    return merged


def save_app_default_color(name: str, is_tag: bool, color: str) -> str:
    """Persist one biome/tag colour into the bundled defaults file so it
    becomes the default for every songpack, for anyone using this copy
    of the editor once the file is committed to the project's repo.
    Returns the path written, so the caller can point the user at it.

    Only biomes have a bundled colour now: in the bundled file a tag maps
    to its biome list, and its colour is averaged from those biomes.
    """
    if is_tag:
        raise ValueError(
            "Biome tags have no colour of their own in the bundled defaults: "
            "it is the average of the biomes they contain.")
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
            out = dict(data)  # keep other keys, e.g. "biome_attributes"
            out["biomes"] = dict(
                sorted(data.get("biomes", {}).items(), key=lambda x: x[0].lower()))
            out["biome_tags"] = dict(
                sorted(data.get("biome_tags", {}).items(), key=lambda x: x[0].lower()))
            json.dump(out, f, indent=2, ensure_ascii=False)
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
    algorithmic colour again). No-op if it wasn't there, and always a no-op
    for tags, whose bundled entry is a biome list rather than a colour.
    """
    if is_tag:
        return
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
    override exists: the bundled app default if one has been set, else (for
    a tag) the average of its biomes' colours, else a deterministic (but
    arbitrary) colour derived from the name.
    """
    biomes, tags = load_app_defaults()
    bundled = (tags if is_tag else biomes).get(name)
    if bundled:
        return bundled
    if is_tag:
        averaged = tag_color(name)
        if averaged:
            return averaged

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


def load_attributes(folder: str) -> dict:
    """Per-songpack biome chart attributes (custom biomes that should show
    up on the Biome Map). Missing/invalid data just means "none".
    """
    try:
        with open(os.path.join(folder, CONFIG_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return _clean_attribute_map(data.get("biome_attributes", {}))


def load_tag_members(folder: str) -> dict:
    """Per-songpack custom tag-membership additions made by the custom-biome
    dialog. Missing/invalid data just means no additions.
    """
    try:
        with open(os.path.join(folder, CONFIG_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return _clean_tag_members(data.get("biome_tag_members", {}))


def _clean_tag_groups(value) -> dict:
    """Return a valid {group_name: [biome_tag, ...]} mapping."""
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for name, tags in value.items():
        if not isinstance(tags, (list, tuple)):
            continue
        values = list(dict.fromkeys(
            str(tag) for tag in tags if isinstance(tag, str) and tag))
        if values:
            cleaned[str(name)] = values
    return cleaned


def load_tag_groups(folder: str) -> dict:
    """Load custom biome-tag groups stored with a songpack.

    Groups are editor metadata: they are shortcuts for adding plain
    BIOMETAG= conditions and are never written into ReactiveMusic.yaml.
    Missing or malformed data is treated as having no groups.
    """
    try:
        with open(os.path.join(folder, CONFIG_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return _clean_tag_groups(data.get("biome_tag_groups", {}))


def save(folder: str, biomes: dict, tags: dict, attributes: dict | None = None,
         tag_members: dict | None = None, tag_groups: dict | None = None) -> None:
    """Write biome_customization.json into the songpack folder, atomically."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, CONFIG_FILENAME)
    fd, tmp = tempfile.mkstemp(
        prefix=".biome_customization_", suffix=".tmp", dir=folder
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            payload = {
                "version": 1,
                "biomes": dict(sorted(biomes.items(), key=lambda x: x[0].lower())),
                "biome_tags": dict(sorted(tags.items(), key=lambda x: x[0].lower())),
            }
            if attributes:
                payload["biome_attributes"] = dict(
                    sorted(attributes.items(), key=lambda x: x[0].lower()))
            if tag_members:
                cleaned = {
                    str(tag): sorted(set(bs))
                    for tag, bs in tag_members.items()
                    if isinstance(bs, (list, tuple)) and bs
                }
                if cleaned:
                    payload["biome_tag_members"] = dict(
                        sorted(cleaned.items(), key=lambda x: x[0].lower()))
            cleaned_groups = _clean_tag_groups(tag_groups or {})
            if cleaned_groups:
                payload["biome_tag_groups"] = dict(
                    sorted(cleaned_groups.items(), key=lambda x: x[0].lower()))
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
