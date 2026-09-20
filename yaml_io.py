from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import yaml

import constants as C
import entry_pools
import scopes
from models import Songpack, Entry
from condition_logic import build_events, parse_events

DEFAULT_ENTRIES_ROOT_KEY = "entries"

#: Keys this editor edits with widgets. Every other key of an entry / of the
#: file is preserved verbatim (Entry.extra_fields / Songpack.extra_top_level).
KNOWN_ENTRY_KEYS = frozenset({
    "events", "songs", "allowFallback", "forceStopMusicOnChanged",
    "forceStopMusicOnValid", "forceStopMusicOnInvalid",
    "forceStartMusicOnValid", "forceChance",
})
KNOWN_TOP_LEVEL_KEYS = frozenset({
    "name", "version", "author", "description", "credits",
    "musicSwitchSpeed", "musicDelayLength",
})


class SongpackFormatError(ValueError):
    """The file is not a songpack this editor can load without changing its
    meaning. The message lists what is wrong and where, for a dialog box.
    """

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


def _mentions_entry_keys(obj) -> bool:
    return isinstance(obj, dict) and ("events" in obj or "songs" in obj)


def _find_entries_root_key(data: dict) -> Optional[str]:
    """The top-level key holding the entries list, or None when the file has
    no entries at all.

    A list counts as the entries list when at least ONE member looks like an
    entry; the members are validated one by one afterwards, so a single bad
    item is reported by position instead of making the whole list invisible
    (which used to load as an EMPTY songpack and overwrite the file on the
    next save).
    """
    candidates = [
        key for key, value in data.items()
        if isinstance(value, list) and any(_mentions_entry_keys(v) for v in value)
    ]
    if candidates:
        return DEFAULT_ENTRIES_ROOT_KEY if DEFAULT_ENTRIES_ROOT_KEY in candidates \
            else candidates[0]
    if DEFAULT_ENTRIES_ROOT_KEY in data:
        value = data[DEFAULT_ENTRIES_ROOT_KEY]
        if value is None or value == []:
            return DEFAULT_ENTRIES_ROOT_KEY
        raise SongpackFormatError(
            f"'{DEFAULT_ENTRIES_ROOT_KEY}' is present but none of its items "
            "has 'events' or 'songs', so this does not look like a songpack "
            "entries list.")
    return None


def _describe(value) -> str:
    text = repr(value)
    return text if len(text) <= 40 else text[:37] + "..."


def _str_list(raw: dict, key: str, where: str, problems: List[str]) -> List[str]:
    value = raw.get(key)
    if not isinstance(value, list):
        problems.append(f"{where}: '{key}' must be a list, got {_describe(value)}.")
        return []
    out = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            out.append(item)
        else:
            problems.append(
                f"{where}: '{key}' item {index} must be text, got "
                f"{_describe(item)} (put it in quotes).")
    return out


def _bool_field(raw: dict, key: str, where: str, problems: List[str]) -> bool:
    if key not in raw:
        return False
    value = raw[key]
    if isinstance(value, bool):
        return value
    problems.append(
        f"{where}: '{key}' must be true or false, got {_describe(value)}.")
    return False


def _str_field(raw: dict, key: str, where: str, problems: List[str],
               default: str) -> str:
    """A single top-level scalar (name/author/description/credits/
    musicSwitchSpeed/musicDelayLength), all of which MAKING_SONGPACKS.md
    documents as strings. Missing is fine (falls back to `default`, same as
    the entry-level fields do); present-but-wrong-type is reported through
    the same `problems` list that events/songs/flags use, rather than being
    silently accepted (e.g. a YAML list or mapping where 'name:' belongs).
    A bare number or bool is still coerced to text -- that's PyYAML data a
    user could reasonably have typed unquoted -- but a list or mapping
    cannot be, and is reported instead of coerced.
    """
    if key not in raw:
        return default
    value = raw[key]
    if isinstance(value, (list, dict)):
        problems.append(
            f"{where}: '{key}' must be text, got {_describe(value)}.")
        return default
    if value is None:
        return default
    return str(value)


def _parse_entry(raw, position: int, problems: List[str]) -> Entry:
    where = f"Entry {position}"
    entry = Entry()
    events = _str_list(raw, "events", where, problems)
    entry.songs = _str_list(raw, "songs", where, problems)
    parse_events(entry, events)
    entry.allow_fallback = _bool_field(raw, "allowFallback", where, problems)
    entry.force_stop_on_changed = _bool_field(
        raw, "forceStopMusicOnChanged", where, problems)
    entry.force_stop_on_valid = _bool_field(
        raw, "forceStopMusicOnValid", where, problems)
    entry.force_stop_on_invalid = _bool_field(
        raw, "forceStopMusicOnInvalid", where, problems)
    entry.force_start_on_valid = _bool_field(
        raw, "forceStartMusicOnValid", where, problems)

    chance = raw.get("forceChance", C.DEFAULT_FORCE_CHANCE)
    if isinstance(chance, bool) or not isinstance(chance, (int, float)):
        problems.append(
            f"{where}: 'forceChance' must be a number, got {_describe(chance)}.")
    else:
        entry.force_chance = float(chance)

    entry.extra_fields = {k: v for k, v in raw.items()
                          if k not in KNOWN_ENTRY_KEYS}
    return entry


def load_songpack(path: str) -> Songpack:
    """Read a songpack. Raises SongpackFormatError (a ValueError) with every
    problem found instead of guessing: a malformed entry, a wrongly typed
    flag or a scalar where a list belongs is reported, never coerced or
    silently dropped.
    """
    if os.path.isdir(path):
        candidate = os.path.join(path, "ReactiveMusic.yaml")
        if not os.path.isfile(candidate):
            raise FileNotFoundError(f"No ReactiveMusic.yaml found in {path}")
        path = candidate

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    pack = Songpack()
    problems: List[str] = []

    if isinstance(data, list):
        raw_entries = data
        pack.entries_root_key = DEFAULT_ENTRIES_ROOT_KEY
    elif isinstance(data, dict):
        where = "Songpack"
        pack.name = _str_field(data, "name", where, problems, pack.name)
        pack.version = str(data.get("version", pack.version))
        pack.author = _str_field(data, "author", where, problems, pack.author)
        pack.description = _str_field(
            data, "description", where, problems, pack.description)
        pack.credits = _str_field(
            data, "credits", where, problems, pack.credits)
        pack.music_switch_speed = _str_field(
            data, "musicSwitchSpeed", where, problems, pack.music_switch_speed)
        pack.music_delay_length = _str_field(
            data, "musicDelayLength", where, problems, pack.music_delay_length)

        root_key = _find_entries_root_key(data)
        if root_key:
            pack.entries_root_key = root_key
            raw_entries = data[root_key] or []
        else:
            pack.entries_root_key = DEFAULT_ENTRIES_ROOT_KEY
            raw_entries = []
        pack.extra_top_level = {
            k: v for k, v in data.items()
            if k not in KNOWN_TOP_LEVEL_KEYS and k != root_key}
    else:
        raise SongpackFormatError("Unrecognised ReactiveMusic.yaml structure.")

    for position, raw in enumerate(raw_entries, start=1):
        if not _entry_looks_like_entry(raw):
            problems.append(
                f"Entry {position} in '{pack.entries_root_key}' is not an entry "
                f"with both 'events' and 'songs' (got {_describe(raw)}).")
            continue
        pack.entries.append(_parse_entry(raw, position, problems))
    if problems:
        shown = "\n".join(f"- {p}" for p in problems[:12])
        if len(problems) > 12:
            shown += f"\n- ... and {len(problems) - 12} more"
        raise SongpackFormatError(
            "This songpack cannot be loaded without changing its meaning:\n"
            + shown)

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
# combined when the YAML is written -- but ONLY when they are adjacent in
# priority order and identical in conditions, flags, scope and extra fields
# (entry_pools.merge_groups). Merging non-adjacent entries used to move a later
# entry's songs above the entries in between, changing what the mod plays.
# The simulator reads entry_pools.logical_view(), i.e. exactly what is
# written here, so the prediction and the file cannot drift apart.
# ---------------------------------------------------------------------------
merge_equivalent_entries = entry_pools.merge_equivalent_entries


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
    for key, value in (getattr(entry, "extra_fields", None) or {}).items():
        if key not in d:
            d[key] = value      # unknown keys survive load -> save unchanged
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
    }
    root = pack.entries_root_key or DEFAULT_ENTRIES_ROOT_KEY
    for key, value in (getattr(pack, "extra_top_level", None) or {}).items():
        if key not in data and key != root:
            data[key] = value
    data[root] = entry_dicts
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
