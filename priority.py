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
*score* per entry (more, rarer condition GROUPS touched => higher score
=> earlier in the list). "Don't loop the same rare song" is left to the
user's explicit choice of allowFallback per entry: MAKING_SONGPACKS.md
documents allowFallback as default FALSE, and the editor follows that (an
older comment here claimed it defaulted to true; it does not, and nothing
writes allowFallback: false on its own). An optional, explicit "variety
mixing" helper (see `find_broader_fallbacks`) lets the user knowingly copy a
broader entry's songs into a narrower entry's own song list, so the broader
song has a direct, immediate chance to be picked instead of waiting for
full exhaustion. Both are clearly surfaced in the UI rather than being a
hidden guess about the mod's internal randomness.

Every entry is scored from its WHOLE parsed condition (see conditions.py), so
cross-category / verbatim items such as "BIOME=ocean || UNDERWATER" count by
what they actually require instead of a flat bonus.

SCORING: DISTINCT GROUPS, NOT OPTION COUNT
-------------------------------------------
score_entry() adds one flat weight per distinct condition GROUP an entry
touches (time, biome, height, underwater, weather, dimension, block, or
"everything else" -- see constants.CATEGORY_WEIGHTS), once each, no matter
how many options inside a group are checked or whether they are OR'd or
AND'd together. See constants.py's own comment on CATEGORY_WEIGHTS for why
this replaced the older "divide by how many options are OR'd together"
approach (short version: it made a song deliberately pooled across two
biomes score LOWER than an unrelated, single-biome-exclusive song, so the
exclusive song always won the tie and the pooled song's own turn in that
biome was never reached).

Scoring by group does not, on its own, make two same-scored entries SHARE
a biome's rotation -- the mod still only plays the first valid entry it
finds, so a tie is still won outright by just one of them (whichever the
user added to the editor first). For entries that should genuinely share a
pool, see case_splitting.py.
"""

from __future__ import annotations

from typing import List

import condition_logic
import conditions
import constants as C
import entry_pools
from models import Entry, Songpack

#: Group keys (other than a FIXED category name) that get their own weight
#: instead of C.DEFAULT_GROUP_WEIGHT.
_GROUP_WEIGHT_OVERRIDES = {
    "biome": C.BIOME_GROUP_WEIGHT,
    "dimension": C.DIMENSION_GROUP_WEIGHT,
    "block": C.BLOCK_GROUP_WEIGHT,
}


def atom_group(atom: conditions.Atom) -> str:
    """Which SCORING group this atom belongs to: a fixed-category key (see
    constants.FIXED_CATEGORY_ORDER), or "biome" (BIOME=/BIOMETAG= alike,
    scored the same -- see constants.py), "dimension", "block", or
    "unknown" for anything conditions.py couldn't classify at all (still
    probably a real, hand-written constraint, so it still counts).
    """
    if atom.kind == conditions.KIND_FIXED:
        return C.TOKEN_TO_CATEGORY.get(atom.value, "unknown")
    if atom.kind in (conditions.KIND_BIOME, conditions.KIND_BIOMETAG):
        return "biome"
    if atom.kind == conditions.KIND_DIM:
        return "dimension"
    if atom.kind == conditions.KIND_BLOCK:
        return "block"
    return "unknown"


def group_weight(group: str) -> float:
    """Rarity weight of one scoring group (see atom_group) -- the SAME
    weight whether the group came from a structured widget or a verbatim /
    cross-category condition, so e.g. "BIOME=ocean || UNDERWATER" scores
    exactly as if BIOME and UNDERWATER had been ticked in the widgets.
    """
    if group in C.CATEGORY_WEIGHTS:
        return C.CATEGORY_WEIGHTS[group]
    return _GROUP_WEIGHT_OVERRIDES.get(group, C.DEFAULT_GROUP_WEIGHT)


def score_entry(entry: Entry) -> float:
    """Higher score = touches more, rarer condition GROUPS = should play
    earlier. Counts each DISTINCT group at most once, regardless of how
    many options within it are selected or whether they are OR'd or AND'd
    -- see constants.py's CATEGORY_WEIGHTS comment for why.
    """
    groups = {atom_group(a) for a in condition_logic.entry_atoms(entry)}
    return round(sum(group_weight(g) for g in groups), 3)


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
