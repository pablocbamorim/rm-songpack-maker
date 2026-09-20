from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import yaml

import constants as C
import priority
import scopes
from models import Songpack, Entry
from condition_logic import build_events, parse_events

DEFAULT_ENTRIES_ROOT_KEY = "entries"

AUDIO_EXTENSIONS = (".mp3", ".ogg", ".wav")


# ---------------------------------------------------------------------------
# YAML output style
#
# MAKING_SONGPACKS.md writes every string in double quotes and indents list
# items under their key, e.g.
#
#     - events: [ "DAY", "BIOME=MOUNTAIN" ]
#       songs:
#         - "ForTheKing"
#
# PyYAML's default output (plain scalars, "- " flush with the parent key) is
# valid YAML that parses to exactly the same data, but we match the
# documented style so files look like the ones the mod's author shows.
# ---------------------------------------------------------------------------
class _FlowList(list):
    pass


class _Quoted(str):
    """A string that is always written with double quotes."""


class _SongpackDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        # Indent list items under their parent key instead of flush with it.
        return super().increase_indent(flow, False)

    def ignore_aliases(self, data):
        # Never emit &id001 / *id001 anchors for repeated values.
        return True


def _flow_list_representer(dumper: yaml.Dumper, data: _FlowList):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def _quoted_representer(dumper: yaml.Dumper, data: _Quoted):
    return dumper.represent_scalar("tag:yaml.org,2002:str", str(data), style='"')


_SongpackDumper.add_representer(_FlowList, _flow_list_representer)
_SongpackDumper.add_representer(_Quoted, _quoted_representer)


def _entry_looks_like_entry(obj) -> bool:
    return isinstance(obj, dict) and "events" in obj and "songs" in obj


def _find_entries_root_key(data: dict) -> Optional[str]:
    for key, value in data.items():
        if isinstance(value, list) and value and all(_entry_looks_like_entry(v) for v in value):
            return key
    return None


def load_songpack(path: str) -> Songpack:
    if os.path.isdir(path):
        candidate = os.path.join(path, "ReactiveMusic.yaml")
        if not os.path.isfile(candidate):
            raise FileNotFoundError(f"No ReactiveMusic.yaml found in {path}")
        path = candidate

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    pack = Songpack()

    if isinstance(data, list):
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

    # Editor-only global/default markers live next to the YAML (scopes.py).
    scopes.apply_to_entries(
        pack.entries, scopes.load(os.path.dirname(os.path.abspath(path))))

    return pack


# ---------------------------------------------------------------------------
# Merging entries that share the same conditions
#
# MAKING_SONGPACKS.md lets one entry hold a pool of songs:
#
#     - events: [ "DAY", "BIOME=MOUNTAIN" ]
#       songs:
#         - "ForTheKing"
#         - "Freedom"
#
# The editor keeps one entry per song (that is what the song list shows), so
# two songs with the same conditions are two entries in the editor. They are
# combined when the YAML is written, not in the editor, so the per-song rows
# stay independently editable.
#
# Two entries are "the same" when they have the same set of event
# requirements (order irrelevant, also inside "||" groups) AND the same
# advanced flags -- merging entries that differ in allowFallback or
# forceStop* would silently change how one of them behaves.
#
# The merged entry sits where its FIRST member was in the priority order.
# ---------------------------------------------------------------------------
def _merge_key(entry: Entry) -> tuple:
    events = tuple(sorted(
        " || ".join(sorted(p.strip() for p in str(ev).split("||") if p.strip()))
        for ev in build_events(entry)
    ))
    return (
        events,
        bool(entry.allow_fallback),
        bool(entry.force_stop_on_changed),
        bool(entry.force_stop_on_valid),
        bool(entry.force_stop_on_invalid),
        bool(entry.force_start_on_valid),
        float(entry.force_chance),
        # A global/default entry must never merge into a normal one that
        # happens to share its conditions.
        getattr(entry, "scope", C.SCOPE_NORMAL),
    )


def merge_equivalent_entries(entries: List[Entry]) -> List[Tuple[Entry, List[str]]]:
    """Group entries with identical conditions and flags.

    Returns a list of (representative_entry, songs) in priority order, where
    `songs` is every song of the group, in order, without duplicates.
    """
    groups: Dict[tuple, List[Entry]] = {}
    # Global/default entries always go below normal ones (priority.py), no
    # matter what order the list is in right now.
    for entry in priority.scope_sorted(entries):
        groups.setdefault(_merge_key(entry), []).append(entry)

    merged: List[Tuple[Entry, List[str]]] = []
    for members in groups.values():          # dicts keep first-seen order
        songs: List[str] = []
        for member in members:
            for song in member.songs:
                if song not in songs:
                    songs.append(song)
        merged.append((members[0], songs))
    return merged


def _entry_to_dict(entry: Entry, songs: Optional[List[str]] = None) -> dict:
    if songs is None:
        songs = entry.songs
    d = {
        "events": _FlowList(_Quoted(e) for e in build_events(entry)),
        "songs": [_Quoted(s) for s in songs],
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


def songpack_to_dict(pack: Songpack, merge_equivalent: bool = True) -> dict:
    if merge_equivalent:
        entry_dicts = [_entry_to_dict(e, songs)
                       for e, songs in merge_equivalent_entries(pack.entries)]
    else:
        entry_dicts = [_entry_to_dict(e) for e in pack.entries]

    def q(value) -> _Quoted:
        return _Quoted("" if value is None else str(value))

    data = {
        "name": q(pack.name),
        "version": q(pack.version),
        "author": q(pack.author),
        "description": q(pack.description),
        "credits": q(pack.credits),
        "musicSwitchSpeed": pack.music_switch_speed,
        "musicDelayLength": pack.music_delay_length,
        (pack.entries_root_key or DEFAULT_ENTRIES_ROOT_KEY): entry_dicts,
    }
    return data


def expected_songs_after_save(pack: Songpack) -> List[str]:
    """Flat song list a saved-and-reloaded file should contain (used by the
    save verification step)."""
    return [s for _e, songs in merge_equivalent_entries(pack.entries)
            for s in songs]


def save_songpack(pack: Songpack, folder: str, copy_music_from: Optional[str] = None) -> str:
    os.makedirs(folder, exist_ok=True)
    yaml_path = os.path.join(folder, "ReactiveMusic.yaml")

    data = songpack_to_dict(pack)
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, Dumper=_SongpackDumper, sort_keys=False,
                  allow_unicode=True, default_flow_style=False, width=10000)

    scopes.save(folder, merge_equivalent_entries(pack.entries))

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
    if not os.path.isdir(folder):
        return []
    stems = []
    for fname in os.listdir(folder):
        stem, ext = os.path.splitext(fname)
        if ext.lower() in AUDIO_EXTENSIONS:
            stems.append(stem)
    return sorted(stems)
