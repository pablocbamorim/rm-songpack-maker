"""
biome_pooling.py
-----------------
Output-time transform: make every song that can play in a biome reachable there,
even when several entries with the same situation overlap on that biome.

THE PROBLEM
-----------
ReactiveMusic plays the FIRST valid entry. With

    - events: ["DAY", "BIOMETAG=IS_TEMPERATE_OVERWORLD"]   songs: [A]
    - events: ["DAY", "BIOMETAG=IS_PLAINS"]                songs: [B, C]

a plains biome is valid for both, so only A ever plays there (B, C are reached
only through allowFallback, which is off by default). Priority order cannot fix
this: the two entries are equally specific, one of them just has to win.

THE TRANSFORM
-------------
1. Only entries whose place part is *pure* are considered: every clause that
   mentions BIOME=/BIOMETAG= mentions nothing else (so "BIOME=ocean || UNDERWATER"
   is left alone). Their coverage is resolved against the KNOWN biomes (BIOME=
   through conditions.soft_match, BIOMETAG= through the tag table).
2. Entries are grouped by their *situation*: the non-place clauses plus every
   flag, scope and unknown YAML field (the same idea as entry_pools.merge_key,
   minus the place). Only entries with an identical situation are ever merged;
   "DAY" and "DAY & RAIN" stay separate, so specificity keeps working.
3. A group is transformed only if some known biome is covered by two or more of
   its entries. Every entry that takes part is then expanded: the biomes it covers
   are partitioned by WHICH entries cover them, and each partition becomes one new
   entry -- situation clauses + "BIOME=ns:a || BIOME=ns:b || ..." -- whose song pool
   is the union (first-seen order, no duplicates) of its contributors. The number of
   new entries is the number of distinct contributor sets, not the number of
   permutations of tags.
4. The original entries stay, right where they were, as RESIDUALS below the new
   pools. Every known biome is taken by a pool first, so residuals only decide
   for biomes this editor does not know (modded ones): those still match their
   tag, and residual_fallback turns allowFallback on for them so a modded biome
   in two overlapping tags walks through both pools instead of looping the first.
   Residuals keep their original position (no reordering by size): moving one up
   would put its songs above entries that used to beat it.

WHERE A NEW ENTRY GOES
----------------------
Right before the first entry that contributed to it. A biome that used to be
won by that entry is now won by the new entry at the same spot, so nothing that
sat below it changes; only the pool got bigger.

WHAT IS DELIBERATELY NOT TRANSFORMED
------------------------------------
* groups with forceStop*/forceStart flags: those fire when an ENTRY's validity
  flips, and splitting one entry into several per-biome entries would make it flip
  when walking between biomes that used to be one continuous valid area. They
  are reported in PoolingReport.skipped and left as they are;
* global/default scope entries (they carry no biome by definition);
* entries with no known coverage (empty tag lists in default_biome_colors.json
  such as IS_FOREST or IS_BEACH, or modded-only biomes): the transform is only
  as good as the membership table.

ASSUMPTIONS (not stated in MAKING_SONGPACKS.md)
------------------------------------------------
* "BIOME=minecraft:plains" is a soft match against the FULL id (the spec's
  "BIOME=modname:custom_biome_name" form), the reading conditions.soft_match already
  uses. A bare "plains" would also hit sunflower_plains, so it is never emitted.
* Even so, a full id can be a prefix of another id ("minecraft:savanna" is inside
  "minecraft:savanna_plateau"). When that other biome has its own pool in the same
  group, that pool is moved ahead of the over-matching one; when nothing in the
  group covers it, a warning is reported instead of silently leaking songs.

Nothing here touches tkinter or files. The tag lookup and the biome universe are
injected (see pool_overlapping_biomes) so the module stays unit-testable.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Set, Tuple

import condition_logic
import conditions
import constants as C
import entry_pools
from models import Entry

_PLACE_KINDS = (conditions.KIND_BIOME, conditions.KIND_BIOMETAG)


@dataclass
class PoolingReport:
    """What the transform did, for a dialog / status line."""
    pools: int = 0          # generated per-biome pool entries
    residuals: int = 0      # original entries kept below them
    groups: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class PoolingResult:
    #: The entries as they should be WRITTEN (logical entries, priority order).
    entries: List[Entry]
    report: PoolingReport


@dataclass
class _Pool:
    key: tuple
    anchor: int                 # index of the first contributing entry
    contrib: Tuple[int, ...]    # indices of every contributing entry
    biomes: List[str]
    entry: Entry
    late: bool = False          # over-matches a biome of another pool


# ---------------------------------------------------------------------------
# Reading an entry
# ---------------------------------------------------------------------------
def _place_split(entry: Entry):
    """(place clauses, other clauses), or None when a clause mixes place atoms
    with anything else ("BIOME=ocean || UNDERWATER"): that cannot be expressed
    as a set of biomes, so the entry is left alone.
    """
    place, other = [], []
    for clause in condition_logic.entry_clauses(entry):
        flags = [atom.kind in _PLACE_KINDS for atom in clause]
        if all(flags):
            place.append(clause)
        elif not any(flags):
            other.append(clause)
        else:
            return None
    return place, other


def _covers(clause, biomes: List[str], tags_of: Callable) -> Set[str]:
    """Known biomes for which at least one atom of this OR clause holds."""
    found: Set[str] = set()
    for atom in clause:
        if atom.kind == conditions.KIND_BIOME:
            found |= {b for b in biomes if conditions.soft_match(atom.value, b)}
        else:
            tag = conditions.normalize_tag(atom.value)
            found |= {b for b in biomes if tag in tags_of(b)}
    return found


def _has_force_flag(entry: Entry) -> bool:
    return any((entry.force_stop_on_changed, entry.force_stop_on_valid,
                entry.force_stop_on_invalid, entry.force_start_on_valid))


def _situation_key(entry: Entry, other) -> tuple:
    """Two entries may share a pool only if this is equal (see module docstring)."""
    return (
        frozenset(frozenset(a.key for a in clause) for clause in other),
        bool(entry.allow_fallback), bool(entry.force_stop_on_changed),
        bool(entry.force_stop_on_valid), bool(entry.force_stop_on_invalid),
        bool(entry.force_start_on_valid), float(entry.force_chance),
        entry.scope, entry_pools._extras_key(entry),
    )


def _label(other) -> str:
    text = " & ".join(" || ".join(a.text for a in clause) for clause in other)
    return text or "no other conditions"


def _build_pool(template: Entry, other, biome_ids: List[str],
                songs: List[str]) -> Entry:
    """A fresh entry: the situation clauses of `template` + a biome OR item."""
    events = [" || ".join(a.text for a in clause) for clause in other]
    events.append(" || ".join(C.PREFIX_BIOME + b for b in biome_ids))
    pool = Entry(songs=songs, allow_fallback=template.allow_fallback,
                 force_chance=template.force_chance, scope=template.scope,
                 extra_fields=copy.deepcopy(template.extra_fields))
    condition_logic.parse_events(pool, events)
    return pool


# ---------------------------------------------------------------------------
# The transform
# ---------------------------------------------------------------------------
def pool_overlapping_biomes(entries: List[Entry], *, biomes: Iterable[str],
                            tags_of: Callable[[str], Set[str]],
                            residual_fallback: bool = True) -> PoolingResult:
    """The entries as they should be written, with overlapping biome / biome-tag
    entries expanded into per-biome pools (see the module docstring).

    biomes             the KNOWN biomes (bare names, e.g. the keys of
                       biome_customization.load_app_dimensions()); anything not
                       listed is treated as modded and is left to the residuals
    tags_of            biome -> set of NORMALIZED tags it belongs to
                       (simulation.biome_tags), so the transform reads the very
                       table the simulator does
    residual_fallback  turn allowFallback on for the kept originals; pass
                       mod_versions.supports(target, "allow_fallback")

    Works on entry_pools.logical_view(entries) -- what will really be written --
    and never edits `entries`.
    """
    report = PoolingReport()
    logical = entry_pools.logical_view(entries).entries
    names = sorted(set(biomes))
    ids = {b: conditions.full_id(b) for b in names}

    info: Dict[int, tuple] = {}     # index -> (situation key, coverage, other)
    for index, entry in enumerate(logical):
        if entry.scope != C.SCOPE_NORMAL or not entry.songs:
            continue
        split = _place_split(entry)
        if split is None or not split[0]:
            continue
        place, other = split
        cover = set(names)
        for clause in place:
            cover &= _covers(clause, names, tags_of)
        if cover:
            info[index] = (_situation_key(entry, other), cover, other)

    by_key: Dict[tuple, List[int]] = defaultdict(list)
    for index, (key, _cover, _other) in info.items():
        by_key[key].append(index)

    pools_by_key: Dict[tuple, List[_Pool]] = {}
    residual_of: Dict[int, Entry] = {}
    for key, members in by_key.items():
        owners: Dict[str, List[int]] = defaultdict(list)
        for index in members:
            for biome in info[index][1]:
                owners[biome].append(index)
        involved = sorted({i for lst in owners.values() if len(lst) > 1
                           for i in lst})
        if not involved:
            continue
        template = logical[involved[0]]
        other = info[involved[0]][2]
        if _has_force_flag(template):
            report.skipped.append(
                f"{_label(other)}: {len(involved)} entries overlap on the same "
                "biomes but use forceStop/forceStart, which pooling would change.")
            continue

        partition: Dict[Tuple[int, ...], List[str]] = defaultdict(list)
        for biome in names:
            contrib = tuple(i for i in involved if biome in info[i][1])
            if contrib:
                partition[contrib].append(biome)
        group_pools = []
        for contrib, group in partition.items():
            songs = list(dict.fromkeys(
                s for i in contrib for s in logical[i].songs))
            group_pools.append(_Pool(
                key=key, anchor=contrib[0], contrib=contrib, biomes=group,
                entry=_build_pool(template, other, [ids[b] for b in group],
                                  songs)))
        pools_by_key[key] = group_pools
        for index in involved:
            residual = copy.deepcopy(logical[index])
            if residual_fallback:
                residual.allow_fallback = True
            residual_of[index] = residual
        report.pools += len(group_pools)
        report.residuals += len(involved)
        report.groups.append(
            f"{_label(other)}: {len(involved)} overlapping entries -> "
            f"{len(group_pools)} biome pool(s).")

    _resolve_overmatch(pools_by_key, names, ids, report)

    at: Dict[int, List[_Pool]] = defaultdict(list)
    for group_pools in pools_by_key.values():
        for pool in group_pools:
            at[pool.anchor].append(pool)
    out: List[Entry] = []
    for index, entry in enumerate(logical):
        # Pools of one group cover disjoint biomes, so their order only matters
        # for the prefix case handled by `late`.
        out.extend(p.entry for p in sorted(at.get(index, ()),
                                           key=lambda p: (p.late, p.contrib)))
        out.append(residual_of.get(index, entry))
    return PoolingResult(entries=out, report=report)


def _resolve_overmatch(pools_by_key, names, ids, report) -> None:
    """A full id is a substring of longer ids ("minecraft:savanna" is inside
    "minecraft:savanna_plateau"), so its pool would also be valid there. If the
    longer biome has its own pool in the same group, that pool goes first; if
    nothing in the group covers it, warn (its songs would leak into it).
    """
    warned: Set[Tuple[str, str]] = set()
    for group_pools in pools_by_key.values():
        pool_of = {b: p for p in group_pools for b in p.biomes}
        for pool in group_pools:
            for biome in pool.biomes:
                for other in names:
                    if other in pool.biomes or not conditions.soft_match(
                            ids[biome], other):
                        continue
                    neighbour = pool_of.get(other)
                    if neighbour is not None:
                        neighbour.anchor = min(neighbour.anchor, pool.anchor)
                        pool.late = True
                    elif (biome, other) not in warned:
                        warned.add((biome, other))
                        report.warnings.append(
                            f"BIOME={ids[biome]} also matches {ids[other]}, which "
                            "no entry of that group covers: its songs would play "
                            "there too.")
