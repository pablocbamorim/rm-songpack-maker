"""
entry_pools.py
---------------
"Logical entries": the entries as they will exist in ReactiveMusic.yaml.

WHY THIS EXISTS
---------------
The editor keeps one Entry per song (that is what the song list shows), but
MAKING_SONGPACKS.md lets one YAML entry hold a POOL of songs. Entries that are
the same rule with different songs are therefore combined when the YAML is
written. If that combining changed *what the mod does*, the simulator (which
used to read the un-merged list) and the saved file would disagree.

THE RULE
--------
Only entries that are ADJACENT in priority order (after the global/default
tiers are pinned to the bottom, see priority.py) and have the same logical
conditions AND the same flags/scope/extra fields are merged. Merging a run of
neighbours cannot change which entry wins anywhere, because nothing sits
between them. Non-adjacent duplicates stay separate YAML entries, exactly as
the editor lists them (the "A(BIOME=x) / B(DAY) / C(BIOME=x)" case no longer
moves C's song above B).

Everything that predicts the mod's behaviour (simulator, blocker check, save
verification) must work on logical_view(), never on the raw list, so that the
prediction and the saved file cannot drift apart.

Nothing here touches tkinter or files.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import conditions
import constants as C
from models import Entry


def _scope_rank(entry: Entry) -> int:
    return C.SCOPE_RANK.get(getattr(entry, "scope", C.SCOPE_NORMAL), 0)


def scope_ordered(entries: List[Entry]) -> List[Entry]:
    """Stable sort that only moves global/default entries below normal ones
    (same rule as priority.scope_sorted, kept here to avoid an import cycle).
    """
    return sorted(entries, key=_scope_rank)


def _extras_key(entry: Entry) -> str:
    try:
        return json.dumps(getattr(entry, "extra_fields", {}) or {},
                          sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(getattr(entry, "extra_fields", None))


def merge_key(entry: Entry) -> tuple:
    """Two entries may share a song pool only if this is equal: same logical
    conditions, same advanced flags (merging entries that differ in
    allowFallback or forceStop* would silently change how one behaves), same
    scope and same unknown YAML fields.
    """
    import condition_logic  # local: condition_logic imports models only
    return (
        condition_logic.canonical_events(entry),
        bool(entry.allow_fallback),
        bool(entry.force_stop_on_changed),
        bool(entry.force_stop_on_valid),
        bool(entry.force_stop_on_invalid),
        bool(entry.force_start_on_valid),
        float(entry.force_chance),
        getattr(entry, "scope", C.SCOPE_NORMAL),
        _extras_key(entry),
    )


def merge_groups(entries: List[Entry]) -> List[List[Entry]]:
    """Runs of adjacent, mergeable entries (each run is one YAML entry), in
    the order they are written.
    """
    groups: List[List[Entry]] = []
    last_key = None
    for entry in scope_ordered(entries):
        key = merge_key(entry)
        if groups and key == last_key:
            groups[-1].append(entry)
        else:
            groups.append([entry])
            last_key = key
    return groups


def expand_song_pools(entries: List[Entry]) -> List[Entry]:
    """Expand YAML song pools into the editor's one-entry-per-song view.

    ReactiveMusic allows several songs in one YAML entry, but the editor's
    raw ``entries`` list is intentionally one Entry per song. A loaded pool
    therefore has to be expanded before a music-folder scan can decide which
    files are genuinely new; otherwise songs that are only secondary members
    of a pool look absent from the song list while still making the scan say
    "added 0".

    The first song keeps the original Entry object and additional songs get a
    deep copy with a fresh Entry id, preserving conditions, flags, scope and
    unknown fields without sharing mutable condition state between rows.
    Saving still merges adjacent equivalent rows back into a YAML song pool.
    """
    import copy

    expanded: List[Entry] = []
    for entry in entries:
        if not entry.songs:
            expanded.append(entry)
            continue
        songs = list(entry.songs)
        entry.songs = [songs[0]]
        expanded.append(entry)
        for song in songs[1:]:
            clone = copy.deepcopy(entry)
            clone.id = Entry().id
            clone.songs = [song]
            expanded.append(clone)
    return expanded


def reconcile_music_folder_entries(entries: List[Entry], stems: List[str]) -> tuple[List[Entry], int, int]:
    """Reconcile scanned audio stems with the editor's one-entry-per-song view.

    ``entries`` may contain YAML song pools because a loaded file represents
    the mod's format, where one entry can hold several songs. Expand those
    pools first, then add exactly one blank entry for every scanned stem that
    is not represented. Existing conditions and flags are never replaced.

    Returns ``(entries, expanded_count, added_count)`` so the UI can report
    what changed without duplicating the reconciliation rules in callbacks.
    """
    before_count = len(entries)
    reconciled = expand_song_pools(entries)
    expanded = len(reconciled) - before_count
    existing = {song for entry in reconciled for song in entry.songs}
    added = 0
    for stem in stems:
        if stem not in existing:
            reconciled.append(Entry(songs=[stem]))
            existing.add(stem)
            added += 1
    return reconciled, expanded, added


def pooled_songs(members: List[Entry]) -> List[str]:
    """Every song of the run, in order, without duplicates."""
    songs: List[str] = []
    for member in members:
        for song in member.songs:
            if song not in songs:
                songs.append(song)
    return songs


def merge_equivalent_entries(entries: List[Entry]) -> List[Tuple[Entry, List[str]]]:
    """[(representative entry, pooled songs)] in write order."""
    return [(members[0], pooled_songs(members))
            for members in merge_groups(entries)]


@dataclass
class LogicalView:
    """The pack as ReactiveMusic will read it.

    entries    one Entry per YAML entry, in priority order. A single-member run
               is the real Entry object; a merged run is a shallow copy of its
               first member carrying the pooled songs (same ``id``), so it is
               read-only for analysis -- edit ``members`` instead.
    members    {logical entry id: the real entries it was made from}
    rep_of     {any real entry id: id of the logical entry containing it}
    positions  {logical entry id: 1-based position of its first member in the
               editor's own list, which is the number the Priority tab shows}
    """
    entries: List[Entry] = field(default_factory=list)
    members: Dict[str, List[Entry]] = field(default_factory=dict)
    rep_of: Dict[str, str] = field(default_factory=dict)
    positions: Dict[str, int] = field(default_factory=dict)


def logical_view(entries: List[Entry]) -> LogicalView:
    # merge_groups() (via scope_ordered()) evaluates entries in scope order
    # (normal, then global, then default), not necessarily the order the
    # caller passed in. `positions` must number entries in that SAME order,
    # or a caller whose list isn't already scope-sorted (e.g. the simulator,
    # which reads app.pack.entries directly) gets stale numbers -- an entry
    # can report a position that belonged to a different entry before the
    # scope sort moved things around. Building raw_index from the sorted
    # sequence keeps this helper correct on its own, without depending on
    # every call site having already called priority.enforce_scope_order.
    ordered = scope_ordered(entries)
    raw_index = {e.id: n for n, e in enumerate(ordered, start=1)}
    view = LogicalView()
    for members in merge_groups(ordered):
        rep = members[0]
        if len(members) == 1:
            logical = rep
        else:
            logical = dataclasses.replace(rep, songs=pooled_songs(members))
        view.entries.append(logical)
        view.members[rep.id] = list(members)
        view.positions[rep.id] = raw_index.get(rep.id, len(view.entries))
        for member in members:
            view.rep_of[member.id] = rep.id
    return view


def semantic_snapshot(entries: List[Entry]) -> list:
    """What the saved file means, as comparable data: for every logical entry
    in order (canonical conditions, song pool, flags, scope, extra fields).
    Used by save verification to catch any reordering or merging surprise.
    """
    return [
        (merge_key(logical), tuple(logical.songs))
        for logical in logical_view(entries).entries
    ]
