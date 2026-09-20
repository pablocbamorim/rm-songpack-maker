"""
simulation.py
--------------
The "what would the mod play here?" engine behind the Biome Simulator tab.
Nothing in here touches tkinter, so it is easy to unit test.

MODEL (from MAKING_SONGPACKS.md)
--------------------------------
* Entries are evaluated top to bottom and the FIRST valid one plays.
* Every item of an entry's ``events`` array must be true (AND); inside one
  item, options joined with ``||`` are OR'd.
* ``allowFallback`` (default false): once every song of an entry has been
  played, fall through to the next valid entry. Without it the entry just
  repeats, so entries below it can never play in that situation.
* ``BIOME=x`` / ``DIM=x`` are soft matches (substring; a value with a
  namespace such as ``minecraft:forest`` is NOT reduced to the broad
  substring "forest" -- see conditions.soft_match, the single implementation
  every view shares), ``BIOMETAG=x`` may omit the ``IS_`` prefix,
  ``BLOCK=id,n`` needs n nearby blocks.

WHAT THE SIMULATOR CAN AND CAN'T KNOW
-------------------------------------
The situation is described by "facts": the fixed events switched on in the
UI, the biome picked on the map (and its dimension / tags), and whatever the
user typed into the manual box. Things the simulator cannot infer (nearby
blocks, tags missing from the built-in table, unknown tokens) are only true
when the user states them as a fact, and entries blocked *only* by such
unknowns are reported as "pending" instead of silently disappearing.

Simplifications, on purpose: songs of an entry are played in list order (the
mod may pick at random), and the silence gap between songs
(``musicDelayLength``) is ignored.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import condition_logic
import conditions
import constants as C
from models import Entry


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------
def normalize_biome(name: str) -> str:
    text = str(name).strip().lower()
    if text.startswith("minecraft:"):
        text = text[len("minecraft:"):]
    return text


# One implementation, shared with every other view (see conditions.py).
normalize_tag = conditions.normalize_tag


# ---------------------------------------------------------------------------
# Biome -> tag table
#
# The authoritative source is the "biome_tags" block of the bundled
# default_biome_colors.json (tag -> the biomes it contains), which is also
# what the Biome Tag map is drawn from -- so a song added to a tag on that map
# plays in exactly the biomes the map says the tag contains. See _tag_table().
#
# TAG_MEMBERS below is the FALLBACK for a missing / old-format JSON and for any
# tag the JSON doesn't list. It is APPROXIMATE, modelled on Fabric's
# conventional biome tags for the vanilla biomes in constants.COMMON_BIOMES.
# Tags found in neither simply never match automatically, and the UI flags
# entries that depend on them. Anything can be forced from the simulator's
# manual box with "BIOMETAG=IS_WET". Keys are normalized (no IS_ prefix).
# ---------------------------------------------------------------------------
_NETHER = {"nether_wastes", "soul_sand_valley", "crimson_forest",
           "warped_forest", "basalt_deltas"}
_END = {"the_end", "small_end_islands", "end_midlands", "end_highlands",
        "end_barrens"}
_VOID = {"the_void"}
_OVERWORLD = set(C.COMMON_BIOMES) - _NETHER - _END - _VOID

_OCEAN_SHALLOW = {"ocean", "cold_ocean", "frozen_ocean", "lukewarm_ocean",
                  "warm_ocean"}
_OCEAN_DEEP = {"deep_ocean", "deep_cold_ocean", "deep_frozen_ocean",
               "deep_lukewarm_ocean"}
_RIVER = {"river", "frozen_river"}
_PEAK = {"jagged_peaks", "frozen_peaks", "stony_peaks"}
_SLOPE = {"snowy_slopes", "meadow", "grove", "cherry_grove"}
_CAVE = {"dripstone_caves", "lush_caves", "deep_dark"}
_TAIGA = {"taiga", "snowy_taiga", "old_growth_pine_taiga",
          "old_growth_spruce_taiga"}
_JUNGLE = {"jungle", "sparse_jungle", "bamboo_jungle"}
_SAVANNA = {"savanna", "savanna_plateau", "windswept_savanna"}
_BADLANDS = {"badlands", "eroded_badlands", "wooded_badlands"}
_WINDSWEPT = {"windswept_hills", "windswept_forest",
              "windswept_gravelly_hills", "windswept_savanna"}
_ICY = {"frozen_ocean", "deep_frozen_ocean", "frozen_river", "ice_spikes",
        "frozen_peaks"}
_SNOWY = {"snowy_plains", "ice_spikes", "snowy_taiga", "snowy_beach",
          "snowy_slopes", "grove", "frozen_peaks", "jagged_peaks"}
_HOT_OVERWORLD = {"desert"} | _BADLANDS | _SAVANNA | _JUNGLE
_COLD_OVERWORLD = (_SNOWY | _ICY | _TAIGA | {"cold_ocean", "deep_cold_ocean"})

TAG_MEMBERS: Dict[str, Set[str]] = {
    "VOID": _VOID,
    "OVERWORLD": _OVERWORLD,
    "NETHER": _NETHER,
    "END": _END,
    "OUTER_END_ISLAND": _END - {"the_end"},
    "OCEAN": _OCEAN_SHALLOW | _OCEAN_DEEP,
    "DEEP_OCEAN": _OCEAN_DEEP,
    "SHALLOW_OCEAN": _OCEAN_SHALLOW,
    "RIVER": _RIVER,
    "AQUATIC": _OCEAN_SHALLOW | _OCEAN_DEEP | _RIVER,
    "AQUATIC_ICY": {"frozen_ocean", "deep_frozen_ocean", "frozen_river"},
    "BEACH": {"beach", "snowy_beach"},
    "STONY_SHORES": {"stony_shore"},
    "FOREST": {"forest", "flower_forest", "birch_forest",
               "old_growth_birch_forest", "dark_forest", "windswept_forest"},
    "BIRCH_FOREST": {"birch_forest", "old_growth_birch_forest"},
    "FLOWER_FOREST": {"flower_forest"},
    "TAIGA": _TAIGA,
    "OLD_GROWTH": {"old_growth_birch_forest", "old_growth_pine_taiga",
                   "old_growth_spruce_taiga"},
    "JUNGLE": _JUNGLE,
    "SAVANNA": _SAVANNA,
    "SWAMP": {"swamp", "mangrove_swamp"},
    "DESERT": {"desert"},
    "BADLANDS": _BADLANDS,
    "PLAINS": {"plains", "sunflower_plains"},
    "SNOWY_PLAINS": {"snowy_plains", "ice_spikes"},
    "MOUNTAIN": _PEAK | _SLOPE,
    "MOUNTAIN_PEAK": _PEAK,
    "MOUNTAIN_SLOPE": _SLOPE,
    "HILL": {"windswept_hills", "windswept_forest",
             "windswept_gravelly_hills"},
    "WINDSWEPT": _WINDSWEPT,
    "MUSHROOM": {"mushroom_fields"},
    "CAVE": _CAVE,
    "UNDERGROUND": _CAVE,
    "SNOWY": _SNOWY,
    "ICY": _ICY,
    "HOT_OVERWORLD": _HOT_OVERWORLD,
    "HOT_NETHER": _NETHER,
    "HOT": _HOT_OVERWORLD | _NETHER,
    "COLD_OVERWORLD": _COLD_OVERWORLD,
    "COLD": _COLD_OVERWORLD,
    "NO_DEFAULT_MONSTERS": {"mushroom_fields"},
}

_TABLE_CACHE: Optional[Dict[str, Set[str]]] = None


def _tag_table() -> Dict[str, Set[str]]:
    """{normalized tag: {normalized biome, ...}}: the bundled JSON's tag lists
    layered over the built-in fallback (the JSON wins for any tag it lists).
    Built once; imported lazily so this module stays cheap to import in tests.
    """
    global _TABLE_CACHE
    if _TABLE_CACHE is None:
        table = {tag: set(members) for tag, members in TAG_MEMBERS.items()}
        try:
            import biome_customization
            for tag, biomes in biome_customization.load_app_tag_members().items():
                table[normalize_tag(tag)] = {normalize_biome(b) for b in biomes}
        except Exception:  # noqa: BLE001 - a broken data file must not stop the simulator
            pass
        _TABLE_CACHE = table
    return _TABLE_CACHE


def known_tags() -> frozenset:
    """Normalized names of every tag the simulator can evaluate."""
    return frozenset(_tag_table())


def biome_tags(name: str) -> Set[str]:
    key = normalize_biome(name)
    return {tag for tag, members in _tag_table().items() if key in members}


def tag_supertags(tag: str) -> Set[str]:
    """`tag` plus every tag that contains all of its biomes. A biome known
    only to be "in tag T" is necessarily in each of these too (e.g. anything
    in IS_HOT_NETHER is also IS_NETHER), so they are all certainly true.
    """
    table = _tag_table()
    key = normalize_tag(tag)
    members = table.get(key)
    if not members:
        return {key}
    return {t for t, m in table.items() if members <= m}


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
@dataclass
class ManualFacts:
    """What the user typed into the manual box, sorted by kind."""
    flags: Set[str] = field(default_factory=set)      # DAY, HOME, ...
    tags: Set[str] = field(default_factory=set)       # normalized BIOMETAGs
    dims: Set[str] = field(default_factory=set)       # extra DIM= facts
    blocks: Dict[str, int] = field(default_factory=dict)
    raw: Set[str] = field(default_factory=set)        # lower-cased lines
    ignored: List[str] = field(default_factory=list)


def _parse_block(payload: str) -> Tuple[str, int]:
    if "," in payload:
        block_id, count = payload.rsplit(",", 1)
        try:
            need = int(count.strip())
        except ValueError:
            need = 1
    else:
        block_id, need = payload, 1
    return normalize_biome(block_id), need


def parse_manual(text: str) -> ManualFacts:
    facts = ManualFacts()
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        line = line.lstrip("-").strip().strip(",").strip().strip("\"'").strip()
        if not line:
            continue
        up = line.upper()
        facts.raw.add(line.lower())
        if up in C.TOKEN_TO_CATEGORY:
            facts.flags.add(up)
        elif up.startswith(C.PREFIX_BIOMETAG):
            facts.tags.add(normalize_tag(line[len(C.PREFIX_BIOMETAG):]))
        elif up.startswith(C.PREFIX_BIOME):
            facts.ignored.append(f"{line} (the biome comes from the map)")
        elif up.startswith(C.PREFIX_DIM):
            facts.dims.add(line[len(C.PREFIX_DIM):].strip().lower())
        elif up.startswith(C.PREFIX_BLOCK):
            block_id, count = _parse_block(line[len(C.PREFIX_BLOCK):])
            facts.blocks[block_id] = max(count, facts.blocks.get(block_id, 0))
    return facts


@dataclass
class SimState:
    biome: str
    dimension: str
    flags: Set[str]
    tags: Set[str]
    dims: Set[str]
    blocks: Dict[str, int]
    raw: Set[str]


def make_state(biome: str, dimension: Optional[str], flags: Set[str],
               manual: Optional[ManualFacts] = None) -> SimState:
    manual = manual or ManualFacts()
    return SimState(
        biome=conditions.full_id(biome),
        dimension=(dimension or "minecraft:overworld").lower(),
        flags=set(flags) | manual.flags,
        tags=biome_tags(biome) | manual.tags,
        dims=set(manual.dims),
        blocks=dict(manual.blocks),
        raw=set(manual.raw),
    )


def make_tag_state(tag: str, dimensions: Set[str], flags: Set[str],
                   manual: Optional[ManualFacts] = None) -> SimState:
    """The situation "somewhere inside a biome of tag `tag`", for the Biome
    Tag map, where no single biome is picked.

    The biome name is unknown, so BIOME= conditions can't match (entries
    that need one are simply not part of a tag's list). What IS certain: the
    tag itself and the tags that contain all of its biomes, and the
    dimension(s) those biomes live in. A tag spanning several dimensions is
    treated as "in any of them", so a DIM= entry is kept when at least one
    of the tag's biomes satisfies it.
    """
    manual = manual or ManualFacts()
    dims = {d.lower() for d in dimensions}
    return SimState(
        biome="",
        dimension=next(iter(dims)) if len(dims) == 1 else "",
        flags=set(flags) | manual.flags,
        tags=tag_supertags(tag) | manual.tags,
        dims=dims | manual.dims,
        blocks=dict(manual.blocks),
        raw=set(manual.raw),
    )


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------
def eval_atom(token: str, st: SimState) -> Tuple[bool, Optional[str]]:
    """(is_true, note). `note` is set when a False result may just mean the
    simulator lacks the information (see module docstring).
    """
    atom = conditions.parse_atom(token)
    if not atom.text:
        return False, None

    if atom.kind == conditions.KIND_FIXED:
        return atom.value in st.flags, None

    if atom.kind == conditions.KIND_BIOMETAG:
        tag = normalize_tag(atom.value)
        if tag in st.tags:
            return True, None
        return False, (None if tag in known_tags()
                       else f"BIOMETAG={atom.value} (tag not in the built-in table)")

    if atom.kind == conditions.KIND_BIOME:
        return conditions.soft_match(atom.value, st.biome), None

    if atom.kind == conditions.KIND_DIM:
        ok = (conditions.soft_match(atom.value, st.dimension)
              or any(conditions.soft_match(atom.value, d) for d in st.dims))
        return ok, None

    if atom.kind == conditions.KIND_BLOCK:
        block_id, need = normalize_biome(atom.value), atom.count
        if st.blocks.get(block_id, 0) >= need:
            return True, None
        return False, f"BLOCK={block_id},{need} (nearby blocks are unknown)"

    if atom.text.lower() in st.raw:
        return True, None
    return False, f"'{atom.text}' (unrecognised condition)"


def evaluate_entry(entry: Entry, st: SimState) -> Tuple[bool, List[str]]:
    """(valid, pending_notes). `pending_notes` is non-empty only when the
    entry is invalid *solely* because of conditions the simulator can't know.
    """
    unknown_notes: List[str] = []
    hard_fail = False
    for item in condition_logic.build_events(entry):
        satisfied = False
        notes: List[str] = []
        for atom in str(item).split("||"):
            ok, note = eval_atom(atom, st)
            if ok:
                satisfied = True
                break
            if note:
                notes.append(note)
        if not satisfied:
            if notes:
                unknown_notes.extend(notes)
            else:
                hard_fail = True
    valid = not hard_fail and not unknown_notes
    pending = unknown_notes if (not valid and not hard_fail) else []
    return valid, pending


# ---------------------------------------------------------------------------
# Plan: the ordered list of songs the mod could pick in a situation
# ---------------------------------------------------------------------------
@dataclass
class PlanItem:
    song: str
    entry_id: str
    entry_index: int          # 1-based position in the priority order
    allow_fallback: bool
    reachable: bool           # False: an entry above never falls through
    also_in: List[int] = field(default_factory=list)
    scope: str = "normal"     # "global" / "default" entries: see scopes.py


@dataclass
class Plan:
    items: List[PlanItem] = field(default_factory=list)
    valid_ids: Set[str] = field(default_factory=set)
    valid_count: int = 0
    pending: List[Tuple[int, List[str]]] = field(default_factory=list)
    terminal_entry_id: Optional[str] = None  # entry that ends the chain

    def playable(self) -> List[int]:
        return [i for i, it in enumerate(self.items) if it.reachable]

    def first_playable(self) -> Optional[int]:
        pl = self.playable()
        return pl[0] if pl else None

    def first_item_of(self, entry_id: str) -> Optional[int]:
        """Index of the first song of an entry, whether or not the fallback
        chain reaches it -- forceStartMusicOnValid plays "this event" directly.
        """
        for i, it in enumerate(self.items):
            if it.entry_id == entry_id:
                return i
        return None

    def find_song(self, song: Optional[str]) -> Optional[int]:
        for i, it in enumerate(self.items):
            if it.song == song:
                return i
        return None

    def next_playable(self, current: Optional[int]) -> Optional[int]:
        """Index of the song that follows `current`. Songs go in priority
        order; after the last one the list wraps -- unless the chain ends in
        an entry without allowFallback, which then just repeats itself.
        """
        pl = self.playable()
        if not pl:
            return None
        if current is None or current not in pl:
            return pl[0]
        pos = pl.index(current)
        if pos + 1 < len(pl):
            return pl[pos + 1]
        if self.terminal_entry_id is not None:
            loop = [i for i in pl
                    if self.items[i].entry_id == self.terminal_entry_id]
            if loop:
                return loop[0]
        return pl[0]


def build_plan(entries: List[Entry], st: SimState,
               positions: Optional[Dict[str, int]] = None) -> Plan:
    """The ordered song list for a situation.

    `entries` must be what the mod will read: pass entry_pools.logical_view(
    pack.entries).entries, not the raw list, so entries that are saved as one
    song pool are simulated as one. `positions` ({entry id: number}) lets the
    plan show the numbers of the editor's own list (the Priority tab) instead
    of positions in the logical list.
    """
    plan = Plan()
    seen: Dict[str, PlanItem] = {}
    chain = True
    for index, entry in enumerate(entries, start=1):
        if positions is not None:
            index = positions.get(entry.id, index)
        valid, notes = evaluate_entry(entry, st)
        if not valid:
            if notes and entry.songs:
                plan.pending.append((index, notes))
            continue
        plan.valid_ids.add(entry.id)
        plan.valid_count += 1
        for song in entry.songs:
            if song in seen:            # e.g. a song "mixed in" from below
                seen[song].also_in.append(index)
                continue
            item = PlanItem(song=song, entry_id=entry.id, entry_index=index,
                            allow_fallback=entry.allow_fallback,
                            reachable=chain,
                            scope=getattr(entry, "scope", "normal"))
            plan.items.append(item)
            seen[song] = item
        if chain and entry.songs and not entry.allow_fallback:
            chain = False
            plan.terminal_entry_id = entry.id
    return plan


# ---------------------------------------------------------------------------
# forceStop* rules
# ---------------------------------------------------------------------------
def should_force_stop(old_valid: Set[str], new_valid: Set[str],
                      entries: List[Entry],
                      rand: Callable[[], float] = random.random
                      ) -> Optional[Entry]:
    """When the situation changes, does an entry's forceStopMusicOn* flag
    cut the current song short? Returns the entry responsible, if any.
    forceChance is honoured.
    """
    became_valid = new_valid - old_valid
    became_invalid = old_valid - new_valid
    for entry in entries:
        if entry.id in became_valid:
            wanted = entry.force_stop_on_changed or entry.force_stop_on_valid
        elif entry.id in became_invalid:
            wanted = entry.force_stop_on_changed or entry.force_stop_on_invalid
        else:
            continue
        if wanted and rand() < entry.force_chance:
            return entry
    return None


# ---------------------------------------------------------------------------
# forceStart* / full transition model
#
# MAKING_SONGPACKS.md:
#   forceStopMusicOnChanged/Valid/Invalid  stop the current music when the
#       entry becomes valid and/or invalid;
#   forceStartMusicOnValid  "If this event becomes valid, and the music stops
#       naturally or because of forceStop, then play this event immediately.";
#   forceChance  "If forceStop/Start is enabled, what is the chance it happens?"
#
# So a situation change has up to three separate effects, kept separate here
# so they can be tested one at a time:
#   1. an entry became valid / invalid            (became_valid / became_invalid)
#   2. a forceStop* flag cuts the current song     (stop_entry)
#   3. a forceStart flag is ARMED                  (armed_start): the entry
#      became valid and its forceChance roll succeeded. It fires later, when
#      the music stops (naturally, or right now if a forceStop just happened)
#      and the entry is still valid -- see choose_force_start.
# The documentation does not say whether the chance is rolled when the entry
# becomes valid or when the music stops; it is rolled once, when it becomes
# valid.
# ---------------------------------------------------------------------------
@dataclass
class Transition:
    became_valid: Set[str] = field(default_factory=set)
    became_invalid: Set[str] = field(default_factory=set)
    stop_entry: Optional[Entry] = None
    armed_start: List[str] = field(default_factory=list)   # entry ids


def evaluate_transition(old_valid: Set[str], new_valid: Set[str],
                        entries: List[Entry],
                        rand: Callable[[], float] = random.random
                        ) -> Transition:
    """Everything a change of situation does, given the entries the mod will
    read (logical entries, see entry_pools).
    """
    result = Transition(became_valid=new_valid - old_valid,
                        became_invalid=old_valid - new_valid)
    result.stop_entry = should_force_stop(old_valid, new_valid, entries, rand)
    for entry in entries:
        if (entry.id in result.became_valid and entry.force_start_on_valid
                and entry.songs and rand() < entry.force_chance):
            result.armed_start.append(entry.id)
    return result


def choose_force_start(armed: Iterable[str], valid_ids: Set[str],
                       entries: List[Entry]) -> Optional[Entry]:
    """The armed entry that fires now that the music has stopped: the first
    one in priority order that is still valid.
    """
    armed = set(armed)
    for entry in entries:
        if entry.id in armed and entry.id in valid_ids and entry.songs:
            return entry
    return None
