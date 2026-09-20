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
in the list). "Don't loop the same rare song" is left to the user's
explicit choice of allowFallback per entry: MAKING_SONGPACKS.md documents
allowFallback as default FALSE, and the editor follows that (an older
comment here claimed it defaulted to true; it does not, and nothing writes
allowFallback: false on its own). An optional, explicit "variety mixing"
helper (see `find_broader_fallbacks`) lets the user knowingly copy a broader
entry's songs into a narrower entry's own song list, so the broader song has
a direct, immediate chance to be picked instead of waiting for full
exhaustion. Both are clearly surfaced in the UI rather than being a hidden
guess about the mod's internal randomness.

Every entry is scored from its WHOLE parsed condition (see conditions.py), so
cross-category / verbatim items such as "BIOME=ocean || UNDERWATER" count by
what they actually require instead of a flat bonus.
"""

from __future__ import annotations

import math
from typing import List

import condition_logic
import conditions
import constants as C
import entry_pools
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

    # Verbatim items (cross-category ORs, several OR groups in one category,
    # unrecognised tokens) are scored from what they actually contain.
    for item in entry.custom_raw_conditions:
        score += clause_score(conditions.parse_item(item))

    return round(score, 3)


def atom_weight(atom: conditions.Atom) -> float:
    """Rarity weight of one condition (same weights as the structured part)."""
    if atom.kind == conditions.KIND_FIXED:
        cat = C.TOKEN_TO_CATEGORY.get(atom.value)
        return C.CATEGORY_WEIGHTS.get(cat, 2.0)
    if atom.kind == conditions.KIND_BIOME:
        return C.BIOME_NAME_WEIGHT
    if atom.kind == conditions.KIND_BIOMETAG:
        return C.BIOME_TAG_WEIGHT
    if atom.kind == conditions.KIND_DIM:
        return C.DIMENSION_WEIGHT
    if atom.kind == conditions.KIND_BLOCK:
        return C.BLOCK_BASE_WEIGHT + math.log(
            max(atom.count, 1) + 1, C.BLOCK_COUNT_LOG_BASE)
    return 1.5          # unrecognised token: still probably a real constraint


def clause_score(clause: conditions.Clause) -> float:
    """Rarity of one OR-group: the average weight of its options, divided by
    how many there are (an OR of n options is n times easier to satisfy).
    For n options of one fixed category this is exactly weight / n, the same
    rule the structured checkboxes use.
    """
    if not clause:
        return 0.0
    weights = [atom_weight(a) for a in clause]
    return (sum(weights) / len(weights)) / len(weights)


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
    # Entries that are the same rule (same merge key) sort next to each other
    # inside their score tier. Otherwise two songs with identical conditions
    # could be separated by an unrelated entry of equal score, and would then
    # be saved as two separate entries instead of one song pool (entry_pools
    # only merges neighbours), leaving the second one unreachable unless it
    # has allowFallback.
    first_seen: dict = {}
    for index, entry in enumerate(entries):
        first_seen.setdefault(entry_pools.merge_key(entry), index)
    return sorted(entries, key=lambda e: (
        scope_rank(e), -score_entry(e), first_seen[entry_pools.merge_key(e)]))


def order_entries(entries: List[Entry]) -> List[Entry]:
    """Backward-compatible name used by the priority UI."""
    return auto_priority_order(entries)


def condition_categories_present(entry: Entry) -> set:
    """A coarse fingerprint of *which kinds* of condition an entry uses,
    ignoring the specific values. Not used by is_broader_than any more (see
    its docstring for why a category-subset test isn't sound), but kept
    around as a cheap fingerprint other call sites may still find useful.
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
    """True if `candidate` is guaranteed valid whenever `specific` is --
    i.e. `specific`'s condition logically IMPLIES `candidate`'s. This is
    what makes candidate a sensible "fallback filler" to mix into
    `specific`'s own song rotation: it can always play alongside it.

    This used to be approximated with a "candidate's condition categories
    are a subset of specific's, and matching categories' values are also a
    subset" heuristic. That heuristic is unsound: it only checks categories
    both entries share and never verifies that specific's OTHER conditions
    (categories candidate doesn't mention at all) can't rule candidate out.
    For example candidate={DAY} and specific={DAY-or-NIGHT, UNDERWATER}
    passed the old test (candidate's only category, time, has DAY subset of
    {DAY, NIGHT}) even though specific is satisfiable by NIGHT+UNDERWATER,
    where candidate is false. It also never looked at BLOCK= conditions.

    conditions.expression_implies is the real, general-purpose implication
    check (already used for reachability hazards -- see
    find_unreachable_hazards below) and covers every condition kind,
    including custom/verbatim items and blocks, uniformly.
    """
    return conditions.expression_implies(
        condition_logic.entry_clauses(specific),
        condition_logic.entry_clauses(candidate),
    )


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


# ---------------------------------------------------------------------------
# Reachability hazards (used by the save-time report)
# ---------------------------------------------------------------------------
def find_unreachable_hazards(entries: List[Entry]) -> List[tuple]:
    """[(entry, blocker)] pairs where `entry` can never play because an entry
    ABOVE it is valid whenever `entry` is and has no allowFallback (so it
    repeats its own songs and never falls through).

    Works on the logical entries the mod will read (entry_pools) and on the
    full parsed expressions (conditions.expression_implies, sound but not
    complete: it can miss a hazard, it does not invent one). Global/default
    entries are skipped: sitting below broader entries is what they are for
    (see scopes.py for the dedicated global check).
    """
    logical = entry_pools.logical_view(entries).entries
    exprs = [condition_logic.entry_clauses(e) for e in logical]
    hazards = []
    for j, entry in enumerate(logical):
        if not entry.songs or getattr(entry, "scope", C.SCOPE_NORMAL) != C.SCOPE_NORMAL:
            continue
        for i in range(j):
            above = logical[i]
            if not above.songs or above.allow_fallback:
                continue
            if conditions.expression_implies(exprs[j], exprs[i]):
                hazards.append((entry, above))
                break
    return hazards
