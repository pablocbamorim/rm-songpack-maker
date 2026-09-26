"""
case_splitting.py
------------------
Turns an entry's OR'd condition groups into separate, fully-AND'd "cases",
then merges cases that land on the exact same condition set -- across the
WHOLE pack, not just neighbours -- into one shared song pool.

WHY THIS EXISTS
---------------
The mod plays the first entry (top to bottom) whose whole `events` array is
true. Two entries that are both valid in the same situation do NOT share
airtime: whichever sits higher wins outright, and the other only gets a
turn if the winner has allowFallback on and its own songs run out (see
priority.py / scopes.py). Rarity scoring (priority.score_entry) decides
which one sits higher, but even a tied score still picks a single winner --
a tie just falls back to whichever entry the user added to the editor
first (see priority.auto_priority_order).

That is surprising for a very common case: a song is added under "BIOME=X
or Y" (one OR'd entry, one editor case), and a second, different song is
added under "BIOME=X" alone. Both songs would be perfectly happy sharing
biome X's rotation, but as two separate entries only one of them can ever
be "the" entry that wins there -- the other is fully blocked in biome X
unless the winner has allowFallback on and exhausts its own songs first.

merge_split_pack() fixes this by construction rather than by priority
order: it expands every entry's OR'd groups into the Cartesian product of
single-valued ("AND only") cases, then merges every case across the WHOLE
pack that ends up with the identical canonical condition set (same
canonical events, same flags, same scope, same extra fields --
entry_pools.merge_key, reused unchanged here) into ONE entry whose song
pool is the union of the songs that wanted that exact situation. Two songs
that both want "just BIOME=X" land in the same entry and genuinely share
its rotation; a song that also wants BIOME=Y keeps a second, separate entry
for that case.

This is a one-shot, user-invoked transform (the "Split OR conditions into
cases..." button on the Priority Order tab), not something the editor does
automatically on every edit: it rewrites entry boundaries and throws away
the original OR groupings, so it is easiest to reason about as an explicit
action the user asks for and can inspect afterwards, exactly like
"Auto-arrange by rarity". It cannot be undone (the editor has no undo/redo
yet -- see ARCHITECTURE.md), so the caller should confirm with the user
first.

POOLS ARE A FILE CONCEPT, NOT AN EDITOR ONE
--------------------------------------------
SplitResult.entries holds the merged song pools (one Entry, several songs),
which is exactly what ReactiveMusic will read. The editor's own model is one
Entry per song (Music & Conditions shows one row per song), so the caller
(PriorityTab._split_or_conditions) runs entry_pools.expand_song_pools() on the
result: each pooled song becomes its own Entry -- a case of that song -- right
next to its siblings. Adjacent entries with identical conditions are written
back as one YAML song pool on save, so nothing is lost by expanding.

WHAT COUNTS AS "OR'd" AND GETS SPLIT
-------------------------------------
* A fixed category (Time, Weather, ...) combined with OR and more than one
  option selected -- one case per option.
* entry.biomes / entry.dimensions / entry.blocks combined with OR and more
  than one item -- one case per item.
* A custom_raw_conditions line containing "||" -- one case per "||"-joined
  token (this is exactly what the token already means in the YAML).
A category/list combined with AND, or with only one item, is never split:
there is nothing to break apart, so it is carried into every generated
case unchanged.

Splitting multiplies: an entry with an OR'd 3-option category AND an OR'd
2-biome list produces 3*2 = 6 cases. MAX_CASES_PER_ENTRY caps this so one
entry can never explode the whole pack or freeze the UI; an entry whose
predicted case count exceeds the cap is left completely untouched (see
SplitResult.skipped).
"""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

import constants as C
import entry_pools
import priority
from models import Entry

#: Hard cap on how many cases one entry may expand into. An entry whose
#: predicted case count exceeds this is left completely unsplit (see
#: SplitResult.skipped) rather than silently exploding the pack.
MAX_CASES_PER_ENTRY = 200


def _fixed_choice_lists(entry: Entry) -> List[Tuple[str, List[set]]]:
    """One (category, [choice, choice, ...]) pair per fixed category that
    has anything selected. AND'd (or single-option) categories contribute
    one choice -- themselves, unchanged; an OR'd category with more than
    one option contributes one choice PER option.
    """
    out = []
    for cat in C.FIXED_CATEGORY_ORDER:
        chosen = entry.selected.get(cat, set())
        if not chosen:
            continue
        combine = getattr(entry, "fixed_combine", {}).get(cat, C.COMBINE_OR)
        if combine == C.COMBINE_AND or len(chosen) <= 1:
            out.append((cat, [set(chosen)]))
        else:
            out.append((cat, [{opt} for opt in sorted(chosen)]))
    return out


def _dynamic_choice_lists(items: Sequence, combine: str) -> List[list]:
    """Same idea as _fixed_choice_lists for a plain list field (biomes,
    dimensions, blocks): AND'd or single-item lists are one choice (the
    whole list, unchanged); an OR'd list of more than one item is one
    choice per item. An empty list is one choice: itself.
    """
    if not items:
        return [[]]
    if combine == C.COMBINE_AND or len(items) <= 1:
        return [list(items)]
    return [[item] for item in items]


def _raw_choice_lists(entry: Entry) -> List[List[str]]:
    """One slot per custom_raw_conditions line. A line without "||" has one
    choice: itself. A line with "||" has one choice per "||"-joined token.
    """
    slots = []
    for raw in entry.custom_raw_conditions:
        parts = [p.strip() for p in str(raw).split("||") if p.strip()]
        slots.append(parts or [str(raw)])
    return slots


def predicted_case_count(entry: Entry) -> int:
    """How many cases split_entry_to_cases() would produce for `entry`,
    without actually building them -- used to decide whether an entry
    should be skipped (see MAX_CASES_PER_ENTRY) before doing the work.
    """
    total = 1
    for _cat, choices in _fixed_choice_lists(entry):
        total *= len(choices)
    total *= len(_dynamic_choice_lists(entry.biomes, entry.biome_combine))
    total *= len(_dynamic_choice_lists(entry.dimensions,
                 entry.dimension_combine))
    total *= len(_dynamic_choice_lists(entry.blocks, entry.block_combine))
    for slot in _raw_choice_lists(entry):
        total *= len(slot)
    return total


def split_entry_to_cases(entry: Entry) -> List[Entry]:
    """Every fully-AND'd case implied by `entry`'s OR'd groups, as fresh
    Entry copies that each carry entry's songs/flags/scope/extra fields
    unchanged. Returns [a deep copy of entry] unchanged when there is
    nothing to split, or when splitting would exceed MAX_CASES_PER_ENTRY
    (the caller decides whether that counts as "skipped" -- see
    merge_split_pack).
    """
    if predicted_case_count(entry) > MAX_CASES_PER_ENTRY:
        return [copy.deepcopy(entry)]

    fixed = _fixed_choice_lists(entry)
    biome_choices = _dynamic_choice_lists(entry.biomes, entry.biome_combine)
    dim_choices = _dynamic_choice_lists(
        entry.dimensions, entry.dimension_combine)
    block_choices = _dynamic_choice_lists(entry.blocks, entry.block_combine)
    raw_slots = _raw_choice_lists(entry)

    fixed_iters = [choices for _cat, choices in fixed]
    n_fixed = len(fixed_iters)

    cases: List[Entry] = []
    for combo in itertools.product(
        *fixed_iters, biome_choices, dim_choices, block_choices, *raw_slots
    ):
        fixed_values = combo[:n_fixed]
        biomes_v, dims_v, blocks_v = combo[n_fixed:n_fixed + 3]
        raw_values = list(combo[n_fixed + 3:])

        case = copy.deepcopy(entry)
        case.id = Entry().id
        case.selected = {k: set() for k in C.FIXED_CATEGORY_ORDER}
        for (cat, _choices), value in zip(fixed, fixed_values):
            case.selected[cat] = set(value)
        # Deep-copied: the choice lists hold the ORIGINAL entry's objects, so
        # without this every sibling case would share (and could mutate) them.
        case.biomes = copy.deepcopy(list(biomes_v))
        case.dimensions = copy.deepcopy(list(dims_v))
        case.blocks = copy.deepcopy(list(blocks_v))
        case.custom_raw_conditions = raw_values
        cases.append(case)
    return cases


@dataclass
class SplitResult:
    #: The rebuilt pack, in priority order (rarest / most-specific first).
    entries: List[Entry] = field(default_factory=list)
    #: Original entries left completely untouched because splitting them
    #: would have exceeded MAX_CASES_PER_ENTRY.
    skipped: List[Entry] = field(default_factory=list)
    #: {representative entry id: how many original cases were folded into
    #: it}. A value of 1 means nothing merged into that entry.
    merged_counts: Dict[str, int] = field(default_factory=dict)


def merge_split_pack(entries: List[Entry]) -> SplitResult:
    """Expand every entry's OR'd groups into AND-only cases, then merge
    every case across the WHOLE pack that lands on the same canonical
    condition set (entry_pools.merge_key: same canonical events, flags,
    scope, extra fields -- the exact rule adjacent song-pool merging
    already uses, just without the "adjacent" requirement) into one entry
    whose songs are the union of the merged cases' songs, in first-seen
    order with duplicates dropped.

    The result is ordered by rarity score (priority.score_entry, highest /
    most-specific first), ties kept in the order the cases were first
    produced in -- the same rule priority.auto_priority_order uses, since
    after splitting there is nothing left for OR-vs-AND structure to
    distinguish within a tie.
    """
    result = SplitResult()
    all_cases: List[Entry] = []
    for entry in entries:
        if predicted_case_count(entry) > MAX_CASES_PER_ENTRY:
            result.skipped.append(entry)
            all_cases.append(copy.deepcopy(entry))
        else:
            all_cases.extend(split_entry_to_cases(entry))

    buckets: Dict[tuple, Entry] = {}
    order: List[tuple] = []
    for case in all_cases:
        key = entry_pools.merge_key(case)
        rep = buckets.get(key)
        if rep is None:
            buckets[key] = case
            order.append(key)
            result.merged_counts[case.id] = 1
        else:
            for song in case.songs:
                if song not in rep.songs:
                    rep.songs.append(song)
            result.merged_counts[rep.id] += 1

    merged = [buckets[key] for key in order]
    first_seen = {id(e): i for i, e in enumerate(merged)}
    # Scope tier first (normal < global < default), as in
    # priority.auto_priority_order, so a high-scoring global entry can never
    # jump above normal ones.
    merged.sort(key=lambda e: (priority.scope_rank(e),
                               -priority.score_entry(e), first_seen[id(e)]))
    result.entries = merged
    return result
