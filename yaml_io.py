"""
yaml_io.py
-----------
Reading and writing ReactiveMusic.yaml files, and scanning a folder of
mp3s.

A note on the file format: MAKING_SONGPACKS.md shows the *global* keys
(name, version, author, ...) and shows *entry* dicts (events/songs/...)
but never explicitly shows the key that the list of entries lives under
in the final file (e.g. it might be `entries:`, `songs:`, or something
else depending on the exact version of the mod). Rather than guess and
risk generating a file the mod can't read, `load_songpack` auto-detects
whichever top-level key holds a list of entry-shaped dicts and remembers
it on the Songpack (`entries_root_key`), so re-saving a file you loaded
reproduces its original structure. For a brand-new songpack we default
to `entries:` -- if your installed mod version expects a different key,
change DEFAULT_ENTRIES_ROOT_KEY below (one line) or rename it in the
"Songpack Info" tab before saving.
"""

from __future__ import annotations

import os
from typing import Optional

import yaml

import constants as C
from models import Songpack, Entry
from condition_logic import build_events, parse_events

DEFAULT_ENTRIES_ROOT_KEY = "entries"

AUDIO_EXTENSIONS = (".mp3", ".ogg", ".wav")


class _FlowList(list):
    """A list that should be dumped in YAML flow style, e.g. [ "A", "B" ],
    matching the `events: [ "DAY", "BIOME=MOUNTAIN" ]` style shown in
    MAKING_SONGPACKS.md. Regular lists (like `songs:`) stay block style.
    """


def _flow_list_representer(dumper: yaml.Dumper, data: _FlowList):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


yaml.add_representer(_FlowList, _flow_list_representer)


def _entry_looks_like_entry(obj) -> bool:
    return isinstance(obj, dict) and "events" in obj and "songs" in obj


def _find_entries_root_key(data: dict) -> Optional[str]:
    for key, value in data.items():
        if isinstance(value, list) and value and all(_entry_looks_like_entry(v) for v in value):
            return key
    return None


def load_songpack(path: str) -> Songpack:
    """Load a ReactiveMusic.yaml (or a folder containing one) into a
    Songpack. Unrecognised global keys are ignored (but entry-level
    conditions we don't understand are preserved -- see condition_logic).
    """
    if os.path.isdir(path):
        candidate = os.path.join(path, "ReactiveMusic.yaml")
        if not os.path.isfile(candidate):
            raise FileNotFoundError(f"No ReactiveMusic.yaml found in {path}")
        path = candidate

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    pack = Songpack()

    if isinstance(data, list):
        # File is *only* a list of entries, no global config wrapper.
        raw_entries = data
        pack.entries_root_key = DEFAULT_ENTRIES_ROOT_KEY
    elif isinstance(data, dict):
        pack.name = data.get("name", pack.name)
        pack.version = str(data.get("version", pack.version))
        pack.author = data.get("author", pack.author)
        pack.description = data.get("description", pack.description)
        pack.credits = data.get("credits", pack.credits)
        pack.music_switch_speed = data.get(
            "musicSwitchSpeed", pack.music_switch_speed)
        pack.music_delay_length = data.get(
            "musicDelayLength", pack.music_delay_length)

        root_key = _find_entries_root_key(data)
        if root_key:
            pack.entries_root_key = root_key
            raw_entries = data[root_key]
        else:
            pack.entries_root_key = DEFAULT_ENTRIES_ROOT_KEY
            raw_entries = []
    else:
        raise ValueError("Unrecognised ReactiveMusic.yaml structure")

    for raw in raw_entries:
        entry = Entry()
        entry.songs = list(raw.get("songs", []) or [])
        parse_events(entry, raw.get("events", []) or [])
        entry.allow_fallback = bool(raw.get("allowFallback", False))
        entry.force_stop_on_changed = bool(
            raw.get("forceStopMusicOnChanged", False))
        entry.force_stop_on_valid = bool(
            raw.get("forceStopMusicOnValid", False))
        entry.force_stop_on_invalid = bool(
            raw.get("forceStopMusicOnInvalid", False))
        entry.force_start_on_valid = bool(
            raw.get("forceStartMusicOnValid", False))
        entry.force_chance = float(
            raw.get("forceChance", C.DEFAULT_FORCE_CHANCE))
        pack.entries.append(entry)

    return pack


def _entry_to_dict(entry: Entry) -> dict:
    d = {
        "events": _FlowList(build_events(entry)),
        "songs": list(entry.songs),
    }
    if entry.allow_fallback:
        d["allowFallback"] = True
    if entry.force_stop_on_changed:
        d["forceStopMusicOnChanged"] = True
    if entry.force_stop_on_valid:
        d["forceStopMusicOnValid"] = True
    if entry.force_stop_on_invalid:
        d["forceStopMusicOnInvalid"] = True
    if entry.force_start_on_valid:
        d["forceStartMusicOnValid"] = True
    if entry.force_chance != C.DEFAULT_FORCE_CHANCE:
        d["forceChance"] = entry.force_chance
    return d


def songpack_to_dict(pack: Songpack) -> dict:
    data = {
        "name": pack.name,
        "version": pack.version,
        "author": pack.author,
        "description": pack.description,
        "credits": pack.credits,
        "musicSwitchSpeed": pack.music_switch_speed,
        "musicDelayLength": pack.music_delay_length,
        (pack.entries_root_key or DEFAULT_ENTRIES_ROOT_KEY): [
            _entry_to_dict(e) for e in pack.entries
        ],
    }
    return data


def save_songpack(pack: Songpack, folder: str, copy_music_from: Optional[str] = None) -> str:
    """Write ReactiveMusic.yaml into `folder` (creating it if needed).
    If `copy_music_from` is given, any referenced song file found there
    is copied into `folder/music/`. Returns the path to the written yaml.
    """
    os.makedirs(folder, exist_ok=True)
    yaml_path = os.path.join(folder, "ReactiveMusic.yaml")

    data = songpack_to_dict(pack)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False,
                  allow_unicode=True, default_flow_style=False)

    if copy_music_from:
        _copy_referenced_music(pack, copy_music_from,
                               os.path.join(folder, "music"))

    return yaml_path


def _copy_referenced_music(pack: Songpack, source_folder: str, dest_folder: str) -> None:
    import shutil

    needed = {song for e in pack.entries for song in e.songs}
    if not needed:
        return
    os.makedirs(dest_folder, exist_ok=True)

    available = {}
    for fname in os.listdir(source_folder):
        stem, ext = os.path.splitext(fname)
        if ext.lower() in AUDIO_EXTENSIONS:
            available[stem] = fname

    for song in needed:
        src_name = available.get(song)
        if src_name:
            shutil.copy2(
                os.path.join(source_folder, src_name),
                os.path.join(dest_folder, src_name),
            )


def scan_music_folder(folder: str):
    """Return a sorted list of song "stems" (filename without extension)
    for every audio file directly inside `folder`.
    """
    if not os.path.isdir(folder):
        return []
    stems = []
    for fname in os.listdir(folder):
        stem, ext = os.path.splitext(fname)
        if ext.lower() in AUDIO_EXTENSIONS:
            stems.append(stem)
    return sorted(stems)
