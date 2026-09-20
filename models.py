"""
models.py
---------
Plain data classes for a songpack. Kept free of any GUI or YAML-specific
code so they're easy to unit test and reuse.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import List, Tuple

import constants as C

_id_counter = itertools.count(1)


def _new_id() -> str:
    return f"entry-{next(_id_counter)}"


@dataclass
class BiomeCondition:
    value: str
    is_tag: bool = False  # False -> BIOME=, True -> BIOMETAG=

    def to_token(self) -> str:
        prefix = C.PREFIX_BIOMETAG if self.is_tag else C.PREFIX_BIOME
        return f"{prefix}{self.value}"


@dataclass
class DimensionCondition:
    value: str

    def to_token(self) -> str:
        return f"{C.PREFIX_DIM}{self.value}"


@dataclass
class BlockCondition:
    block_id: str
    min_count: int = 1

    def to_token(self) -> str:
        return f"{C.PREFIX_BLOCK}{self.block_id},{self.min_count}"


@dataclass
class Entry:
    """One songpack entry. In this tool an entry is centered on a single
    music file, though the underlying format allows a list of songs, so
    `songs` stays a list -- the editor's main list just treats the first
    song as "the" song for that row, and lets extra songs (e.g. fallback
    filler tracks mixed in deliberately, see README) be appended.
    """

    id: str = field(default_factory=_new_id)
    songs: List[str] = field(default_factory=list)

    # Fixed categories: category_key -> set of selected option strings
    selected: dict = field(default_factory=lambda: {
                           k: set() for k in C.FIXED_CATEGORY_ORDER})

    biomes: List[BiomeCondition] = field(default_factory=list)
    biome_combine: str = C.COMBINE_OR

    dimensions: List[DimensionCondition] = field(default_factory=list)
    dimension_combine: str = C.COMBINE_OR

    blocks: List[BlockCondition] = field(default_factory=list)
    block_combine: str = C.COMBINE_AND

    # Anything loaded from an existing file that doesn't map cleanly onto
    # the structured UI (e.g. a hand-written mixed OR group spanning two
    # categories) is preserved verbatim here so nothing is lost on save.
    custom_raw_conditions: List[str] = field(default_factory=list)

    fixed_combine: dict = field(default_factory=lambda: {
        k: C.COMBINE_OR for k in C.FIXED_CATEGORY_ORDER})

    allow_fallback: bool = C.DEFAULT_ALLOW_FALLBACK
    force_stop_on_changed: bool = False
    force_stop_on_valid: bool = False
    force_stop_on_invalid: bool = False
    force_start_on_valid: bool = False
    force_chance: float = C.DEFAULT_FORCE_CHANCE

    # Editor-only marker: "normal", "global" or "default" (see constants.py
    # and scopes.py). Persisted in songpack_scopes.json, not in the YAML.
    scope: str = C.SCOPE_NORMAL

    def display_name(self) -> str:
        if not self.songs:
            return "(no song assigned)"
        if len(self.songs) > 1:
            return f"{self.songs[0]} (+{len(self.songs) - 1} more)"
        return self.songs[0]

    def has_any_condition(self) -> bool:
        any_fixed = any(v for v in self.selected.values())
        return bool(
            any_fixed or self.biomes or self.dimensions or self.blocks
            or self.custom_raw_conditions
        )


@dataclass
class Songpack:
    name: str = "My Awesome Songpack"
    version: str = "1.0"
    author: str = ""
    description: str = ""
    credits: str = ""
    music_switch_speed: str = "NORMAL"
    music_delay_length: str = "NORMAL"

    # Which mod build this songpack is aimed at. Not part of the
    # ReactiveMusic.yaml format -- it's editor metadata kept in
    # songpack_target.json so the condition editor can hide events the
    # target mod version predates. See mod_versions.py.
    minecraft_version: str = ""   # "" / "Any ..." -> no target chosen
    mod_version: str = ""         # "" -> derive from minecraft_version
    platform: str = ""            # Fabric / NeoForge / Forge, metadata only

    entries: List[Entry] = field(default_factory=list)

    # The top-level YAML key entries were found under when loading an
    # existing file (e.g. "entries" or "songs"), so we can round-trip it.
    # Defaults to "entries" for newly created songpacks.
    entries_root_key: str = "entries"

    music_folder: str = ""  # last folder mp3s were loaded from, for convenience

    def find(self, entry_id: str) -> Entry:
        for e in self.entries:
            if e.id == entry_id:
                return e
        raise KeyError(entry_id)

    def move_entry(self, entry_id: str, new_index: int) -> None:
        idx = next(i for i, e in enumerate(self.entries) if e.id == entry_id)
        entry = self.entries.pop(idx)
        new_index = max(0, min(new_index, len(self.entries)))
        self.entries.insert(new_index, entry)
