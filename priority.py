"""
priority.py
------------
The "how do we automatically decide priority order" and "how do we stop
the same rare song from looping" logic.

WHY THIS ALGORITHM
-------------------
The mod (per MAKING_SONGPACKS.md) evaluates entries top-to-bottom and
plays the *first* one whose conditions are all currently true. So an
entry's position in the list, not some separate "weight" field, is what
makes it "win" over broader entries. There's no documented probability
field for ordinary song selection -- the only levers the format actually
gives us are:
  * priority order (which entry wins),
  * allowFallback (once an entry's own song list is exhausted, fall
    through to the next valid entry instead of repeating),
  * forceChance (only affects forceStop/forceStart transitions).

So "rarest conditions first" is implemented as a specificity/rarity
*score* per entry (more, narrower conditions => higher score => earlier
in the list), and "don't loop the same rare song" is implemented by
defaulting allowFallback=True everywhere, plus an optional, explicit
"variety mixing" helper (see `find_broader_fallbacks`) that lets the user
knowingly copy a broader entry's songs into a narrower entry's own song
list, so the broader song has a direct, immediate chance to be picked
instead of waiting for full exhaustion. Both are clearly surfaced in the
UI rather than being a hidden guess about the mod's internal randomness.
"""

from __future__ import annotations

import math
from typing import List

import constants as C
from models import Entry, Songpack


def score_entry(entry: Entry) -> float:
    """Higher score = rarer / more specific = should play earlier."""
    score = 0.0

    for cat in C.FIXED_CATEGORY_ORDER:
        chosen = entry.selected.get(cat, set())
        n = len(chosen)
        if n == 0:
            continue
        weight = C.CATEGORY_WEIGHTS.get(cat, 2.0)
        # An OR group with many options checked is easier to satisfy, so
        # it contributes less rarity than a single, narrow selection.
        score += weight / n

    if entry.biomes:
        base = sum(
            C.BIOME_TAG_WEIGHT if b.is_tag else C.BIOME_NAME_WEIGHT
            for b in entry.biomes
        ) / len(entry.biomes)
        if entry.biome_combine == C.COMBINE_OR:
            score += base / \
                len(entry.biomes) if len(entry.biomes) > 1 else base
        else:
            score += base * len(entry.biomes)

    if entry.dimensions:
        n = len(entry.dimensions)
        if entry.dimension_combine == C.COMBINE_OR:
            score += C.DIMENSION_WEIGHT / n if n > 1 else C.DIMENSION_WEIGHT
        else:
            score += C.DIMENSION_WEIGHT * n

    if entry.blocks:
        block_score = 0.0
        for b in entry.blocks:
            block_score += C.BLOCK_BASE_WEIGHT + \
                math.log(max(b.min_count, 1) + 1, C.BLOCK_COUNT_LOG_BASE)
        if entry.block_combine == C.COMBINE_OR and len(entry.blocks) > 1:
            block_score /= len(entry.blocks)
        score += block_score

    # Custom/raw conditions we couldn't parse still likely represent real
    # constraints, so give them a small flat bonus each rather than zero.
    score += 1.5 * len(entry.custom_raw_conditions)

    return round(score, 3)


def scope_rank(entry: Entry) -> int:
    """0 for normal entries, 1 for global, 2 for default (see constants)."""
    return C.SCOPE_RANK.get(getattr(entry, "scope", C.SCOPE_NORMAL), 0)


def scope_sorted(entries: List[Entry]) -> List[Entry]:
    """Stable sort that only moves global/default entries below normal ones,
    keeping every manual order inside each tier.
    """
    return sorted(entries, key=scope_rank)


def enforce_scope_order(entries: List[Entry]) -> bool:
    """In-place scope_sorted(). Returns True if anything moved."""
    ordered = scope_sorted(entries)
    if all(a is b for a, b in zip(ordered, entries)):
        return False
    entries[:] = ordered
    return True


def auto_priority_order(entries: List[Entry]) -> List[Entry]:
    """Return a new list: normal entries first, then global, then default;
    inside each tier rarest (highest score) first. Ties keep their existing
    relative order (stable sort) so re-running this after a manual tweak
    doesn't needlessly shuffle unrelated entries.
    """
    return sorted(entries, key=lambda e: (scope_rank(e), -score_entry(e)))


def order_entries(entries: List[Entry]) -> List[Entry]:
    """Backward-compatible name used by the priority UI."""
    return auto_priority_order(entries)


def condition_categories_present(entry: Entry) -> set:
    """A coarse fingerprint of *which kinds* of condition an entry uses,
    ignoring the specific values. Used to detect "entry B's requirements
    look like a subset of entry A's" for the variety-mixing helper below.
    """
    cats = {cat for cat in C.FIXED_CATEGORY_ORDER if entry.selected.get(cat)}
    if entry.biomes:
        cats.add("biome")
    if entry.dimensions:
        cats.add("dimension")
    if entry.blocks:
        cats.add("block")
    return cats


def is_broader_than(candidate: Entry, specific: Entry) -> bool:
    """True if `candidate`'s condition *categories* are a strict subset of
    `specific`'s, AND wherever both specify the same category, candidate's
    values are contained in specific's (so candidate is guaranteed valid
    whenever specific is). This is what makes candidate a sensible
    "fallback filler" to mix into `specific`'s own song rotation.
    """
    cand_cats = condition_categories_present(candidate)
    spec_cats = condition_categories_present(specific)
    if not cand_cats or not (cand_cats < spec_cats):
        return False

    for cat in C.FIXED_CATEGORY_ORDER:
        cand_vals = candidate.selected.get(cat, set())
        spec_vals = specific.selected.get(cat, set())
        if cand_vals and not cand_vals.issubset(spec_vals):
            return False

    if candidate.dimensions:
        cand_dims = {d.value for d in candidate.dimensions}
        spec_dims = {d.value for d in specific.dimensions}
        if not cand_dims.issubset(spec_dims):
            return False

    if candidate.biomes:
        cand_biomes = {(b.value, b.is_tag) for b in candidate.biomes}
        spec_biomes = {(b.value, b.is_tag) for b in specific.biomes}
        if not cand_biomes.issubset(spec_biomes):
            return False

    return True


def find_broader_fallbacks(target: Entry, all_entries: List[Entry], limit: int = 5) -> List[Entry]:
    """Entries whose conditions are implied by `target`'s conditions --
    i.e. they'd also be valid in every situation `target` is valid in.
    These are good "variety filler" candidates for `target` (see the
    module docstring). Sorted broadest (fewest conditions) first, since
    the broadest fallback is the safest one to mix in.
    """
    candidates = [
        e for e in all_entries
        if e.id != target.id and is_broader_than(e, target)
    ]
    candidates.sort(key=score_entry)
    return candidates[:limit]
