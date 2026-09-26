"""
scopes.py
----------
"Global" and "default" songs: entries that are meant to play in every biome
(or fill the gaps left by biome-specific entries) without being copied into
each biome's own cases.

HOW IT WORKS (no special output format needed)
----------------------------------------------
A global/default entry is an ordinary entry with NO ``BIOME=`` condition,
e.g. ``events: ["FISHING"]``. ReactiveMusic plays the first valid entry from
the top, so if such an entry sits BELOW all the biome-specific ones:

  * where a biome has no valid entry of its own, the generic entry plays
    (that is what a "default" is for);
  * where a biome's entry is valid but runs out of songs, it falls through to
    the generic entry only if that entry has ``allowFallback`` on.

So the only extra machinery is:

  1. ``Entry.scope`` ("normal" / "global" / "default"), kept in a sidecar file
     (SIDECAR_FILENAME) because the mod does not know about it,
  2. priority pinning (priority.enforce_scope_order / auto_priority_order),
  3. this module's blocker check: which entries above a GLOBAL song stop it
     from being reached in which biomes, and a one-step fix that turns
     ``allowFallback`` on for them.

WHAT THE BLOCKER CHECK COVERS
-----------------------------
For every way of satisfying the global entry's own conditions on their own
(each option of an OR group is one scenario) and every known biome, it asks
simulation.build_plan whether the global entry is reachable. The situation
is "only these conditions are true": a rarer combination (say FISHING & DAY
when the global is just DAY) is not tried, so a higher entry that only
matches that combination can still block it. Default entries are never
checked; being blocked is what "default" means.
"""

from __future__ import annotations

import itertools
import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import condition_logic
import conditions
import constants as C
import entry_pools
import simulation
from models import Entry

SIDECAR_FILENAME = "songpack_scopes.json"

#: Upper bound on OR-group combinations tried per global entry.
_MAX_SCENARIOS = 24


# ---------------------------------------------------------------------------
# Identifying an entry across a save / load round trip
# ---------------------------------------------------------------------------
def entry_signature(entry: Entry, songs: Optional[List[str]] = None) -> tuple:
    """(sorted event requirements, songs). Same normalisation as
    yaml_io._merge_key, so an entry saved as part of a merged song pool
    finds its scope again when the YAML is read back.
    """
    events = tuple(sorted(
        " || ".join(sorted(p.strip() for p in str(ev).split("||") if p.strip()))
        for ev in condition_logic.build_events(entry)
    ))
    return events, tuple(entry.songs if songs is None else songs)


# ---------------------------------------------------------------------------
# Sidecar file
# ---------------------------------------------------------------------------
def load(folder: str) -> List[dict]:
    """Records [{"events": [...], "songs": [...], "scope": "global"}].
    A missing or broken file means "no scopes" and never blocks loading.
    """
    try:
        with open(os.path.join(folder, SIDECAR_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return []
    records = data.get("entries", []) if isinstance(data, dict) else []
    clean = []
    for rec in records if isinstance(records, list) else []:
        if not isinstance(rec, dict) or rec.get("scope") not in C.SCOPES:
            continue
        events, songs = rec.get("events"), rec.get("songs")
        if isinstance(events, list) and isinstance(songs, list):
            clean.append({"events": [str(e) for e in events],
                          "songs": [str(s) for s in songs],
                          "scope": rec["scope"]})
    return clean


def apply_to_entries(entries: Iterable[Entry], records: List[dict]) -> None:
    """Set ``entry.scope`` on every entry a record matches."""
    wanted = {}
    for rec in records:
        events = tuple(sorted(
            " || ".join(sorted(p.strip() for p in ev.split("||") if p.strip()))
            for ev in rec["events"]))
        wanted[(events, tuple(rec["songs"]))] = rec["scope"]
    for entry in entries:
        entry.scope = wanted.get(entry_signature(entry), C.SCOPE_NORMAL)


def save(folder: str, groups: List[Tuple[Entry, List[str]]]) -> Optional[str]:
    """Write the sidecar for the merged (entry, songs) groups that
    yaml_io writes. With nothing scoped an old sidecar is removed instead, so
    stale scopes cannot come back after the user turns them all off.
    """
    records = []
    for entry, songs in groups:
        scope = getattr(entry, "scope", C.SCOPE_NORMAL)
        if scope == C.SCOPE_NORMAL:
            continue
        records.append({"events": condition_logic.build_events(entry),
                        "songs": list(songs), "scope": scope})
    target = os.path.join(folder, SIDECAR_FILENAME)
    if not records:
        try:
            os.unlink(target)
        except OSError:
            pass
        return None
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".songpack_scopes_", suffix=".tmp",
                               dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": records}, f, indent=2,
                      ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target


# ---------------------------------------------------------------------------
# Blocker analysis
# ---------------------------------------------------------------------------
@dataclass
class Blocker:
    """Entry ``blocker`` stops global entry ``scoped`` from being reached in
    every biome of ``biomes``.
    """
    scoped: Entry
    blocker: Entry
    biomes: List[str] = field(default_factory=list)


def _has_biome_condition(entry: Entry) -> bool:
    """Does this entry require a specific biome/biome-tag in ANY way?

    A "global" entry is only meaningful when it plays in every biome, so a
    BIOME= or BIOMETAG= condition disqualifies it -- but that condition may
    not live in the structured ``entry.biomes`` list. It can be hiding
    inside a cross-category OR ("BIOME=ocean || UNDERWATER") or any other
    item condition_logic.parse_events had to keep verbatim in
    custom_raw_conditions (see condition_logic.py's round-trip rule). Such
    items are still parsed on demand by conditions.py, so read the WHOLE
    canonical expression (entry_atoms) rather than trusting the GUI field
    alone -- otherwise a hand-written or edited entry with an embedded
    biome requirement is analyzed as though it were biome-independent.
    """
    return any(
        a.kind in (conditions.KIND_BIOME, conditions.KIND_BIOMETAG)
        for a in condition_logic.entry_atoms(entry)
    )


#: Time-of-day tokens -- exactly one is always true in-game.
_TIME_TOKENS = tuple(C.FIXED_CATEGORIES[C.CATEGORY_TIME]["options"])


def _has_time_condition(entry: Entry) -> bool:
    """Does this entry require a specific time of day in ANY way?"""
    wanted = {t.upper() for t in _TIME_TOKENS}
    return any(a.kind == conditions.KIND_FIXED and a.value.upper() in wanted
               for a in condition_logic.entry_atoms(entry))


def _time_scenarios(entry: Entry):
    """Return no extra flag when time is pinned, otherwise test every time."""
    if _has_time_condition(entry):
        return [frozenset()]
    return [frozenset({token}) for token in _TIME_TOKENS]


def _where_label(biome: str, time_flags) -> str:
    """Describe a checked biome/time situation for the blocker report."""
    return biome if not time_flags else f"{biome} at {next(iter(time_flags))}"


def _is_reachability_candidate(entry: Entry) -> bool:
    """Return whether the reachability sweep should test this entry.

    Global entries without a place are swept across biomes; place-specific
    entries without a time condition are swept across all time tokens.
    Default and time-only entries are deliberately excluded.
    """
    if not entry.songs:
        return False
    scope = getattr(entry, "scope", C.SCOPE_NORMAL)
    if scope == C.SCOPE_DEFAULT:
        return False
    if scope == C.SCOPE_GLOBAL and not _has_biome_condition(entry):
        return True
    return _has_biome_condition(entry) and not _has_time_condition(entry)


def has_checkable_entry(entries) -> bool:
    """Is there anything ``find_blockers`` would actually sweep?"""
    return any(_is_reachability_candidate(e) for e in entries)

def biome_dimensions(custom_attributes: Optional[dict] = None) -> Dict[str, str]:
    """{biome: dimension id} for every biome the editor knows about (bundled
    plus this songpack's custom ones, which are assumed to be overworld).
    """
    import biome_customization  # lazy: keeps this module cheap to import
    dims = biome_customization.load_app_dimensions()
    return {name: dims.get(name) or "minecraft:overworld"
            for name in biome_customization.all_attributes(custom_attributes)}


def _scenarios(entry: Entry) -> List[List[str]]:
    """Each way of making the entry's own conditions true: one option from
    every OR group.
    """
    groups = []
    for item in condition_logic.build_events(entry):
        options = [a.strip() for a in str(item).split("||") if a.strip()]
        if options:
            groups.append(options)
    if not groups:
        return [[]]
    return [list(c) for c in itertools.islice(
        itertools.product(*groups), _MAX_SCENARIOS)]


def find_blockers(entries: List[Entry],
                  biomes: Dict[str, str]) -> List[Blocker]:
    """Which entries keep a GLOBAL entry from being reached, and where.

    Works on the logical entries (entry_pools): what the mod will read, i.e.
    neighbouring entries that are saved as one song pool count as one. The
    returned Blocker entries are those logical entries (same ``id`` as their
    first real entry); use enable_fallback_on_blockers to change the real ones.
    """
    logical = entry_pools.logical_view(entries).entries
    found: Dict[Tuple[str, str], Blocker] = {}
    for scoped in logical:
        if (getattr(scoped, "scope", None) != C.SCOPE_GLOBAL
                or not scoped.songs or _has_biome_condition(scoped)):
            continue
        for atoms in _scenarios(scoped):
            manual = simulation.parse_manual("\n".join(atoms))
            for biome, dimension in biomes.items():
                state = simulation.make_state(biome, dimension, set(), manual)
                plan = simulation.build_plan(logical, state)
                if scoped.id not in plan.valid_ids:
                    continue      # e.g. DIM= mismatch: not this biome's business
                items = [i for i in plan.items if i.entry_id == scoped.id]
                if not items or any(i.reachable for i in items):
                    continue
                blocker = next((e for e in logical
                                if e.id == plan.terminal_entry_id), None)
                if blocker is None:
                    continue
                item = found.setdefault(
                    (scoped.id, blocker.id), Blocker(scoped, blocker))
                if biome not in item.biomes:
                    item.biomes.append(biome)
    return list(found.values())


def enable_fallback_on_blockers(entries: List[Entry],
                                biomes: Dict[str, str]) -> List[Entry]:
    """Turn allowFallback on for blocking entries until no global entry is
    blocked any more (one blocker can hide the next one below it). Returns
    the real entries that were changed, in the order they were changed. A
    blocker that is a merged song pool is changed on every one of its members,
    so they stay mergeable.
    """
    changed: List[Entry] = []
    for _ in range(len(entries) + 1):
        view = entry_pools.logical_view(entries)
        progressed = False
        for item in find_blockers(entries, biomes):
            for member in view.members.get(item.blocker.id, [item.blocker]):
                if not member.allow_fallback:
                    member.allow_fallback = True
                    changed.append(member)
                    progressed = True
        if not progressed:
            break
    return changed


def describe_blockers(entries: List[Entry], blockers: List[Blocker],
                      max_biomes: int = 6) -> str:
    """Plain-text report for a dialog."""
    index = {e.id: n for n, e in enumerate(entries, start=1)}
    lines = []
    for item in blockers:
        shown = ", ".join(item.biomes[:max_biomes])
        if len(item.biomes) > max_biomes:
            shown += f", +{len(item.biomes) - max_biomes} more"
        lines.append(
            f"\u2022 Global '{item.scoped.display_name()}' is blocked by entry "
            f"#{index.get(item.blocker.id, '?')} '{item.blocker.display_name()}' "
            f"({condition_logic.summarize_entry(item.blocker, 50)}) in: {shown}")
    return "\n".join(lines)
