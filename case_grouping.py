"""
case_grouping.py
-----------------
Shared helpers for the two "case" views over ``pack.entries`` that the
editor now offers side by side:

  * Song-centric cases (Music & Conditions tab): every Entry that shares
    the same primary song (``entry.songs[0]``) is a "case" of that song --
    one row in the song list, several tabs of conditions underneath it.

  * Biome-centric cases (Biome Simulator tab -> select a biome ->
    biome_case_editor.py): every Entry whose ``biomes`` list contains a
    plain (non-tag) ``BIOME=`` condition for a given biome name is a
    "case" of that biome -- the songs that can play there, one tab per
    situation (e.g. "day + sunrise", "night + sunset", "sun + rain").

  * Tag-centric cases (same tab, "Biome tags" map): the same idea for
    ``BIOMETAG=`` conditions. A tag case is an ordinary entry carrying the
    tag, so every biome the tag contains plays its songs without anything
    being copied onto those biomes (see simulation.biome_tags).

Both groupings are computed purely from each entry's own data (its
primary song text, its biome conditions) rather than a separate id kept
on the side. That is deliberate: there is only ONE underlying list,
``app.pack.entries``, and every view -- the song list, the priority list,
the biome map, the biome case editor -- is just a different lens on it.
Editing a case from either tab immediately shows up correctly in the
other, with nothing to keep in sync by hand.

Case *order* (which tab is "Case 1", which is "Case 2", ...) is simply
each entry's position in ``pack.entries`` -- i.e. priority order. That
also means "Auto-arrange by rarity" in the Priority Order tab reorders
case tabs sensibly instead of needing its own notion of order.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import constants as C
from models import BiomeCondition, Entry, Songpack
from simulation import normalize_tag


# ---------------------------------------------------------------------------
# Song-centric cases
# ---------------------------------------------------------------------------
def gid(entry: Entry) -> str:
    """Group key for song-centric cases: the entry's primary song, or its
    own id when it has none (so a still-blank entry never groups with
    anything just because both happen to be empty).
    """
    return entry.songs[0] if entry.songs else entry.id


def group_by_song(entries: List[Entry]) -> List[List[Entry]]:
    """One list per song -- ``[[case1, case2, ...], ...]`` -- songs in
    order of first appearance, cases kept in priority (``pack.entries``)
    order.
    """
    by_gid: Dict[str, List[Entry]] = {}
    for entry in entries:
        by_gid.setdefault(gid(entry), []).append(entry)
    return list(by_gid.values())


def group_of(pack: Songpack, entry_id: str) -> List[Entry]:
    """The cases (in priority order) of the song that ``entry_id``
    belongs to.
    """
    target = next((e for e in pack.entries if e.id == entry_id), None)
    if target is None:
        return []
    key = gid(target)
    return [e for e in pack.entries if gid(e) == key]


def add_case_to(pack: Songpack, entry_id: str) -> Optional[Entry]:
    """Append a new, empty case to the song of ``entry_id`` and return it.
    The new entry sits right after the song's other cases in the priority
    order (use Priority Order -> Auto-arrange once its conditions are set).
    """
    members = group_of(pack, entry_id)
    if not members:
        return None
    primary = members[0]
    new_entry = Entry(songs=list(primary.songs[:1]))
    member_ids = {m.id for m in members}
    last = max(i for i, e in enumerate(pack.entries) if e.id in member_ids)
    pack.entries.insert(last + 1, new_entry)
    return new_entry


def case_labels(pack: Songpack) -> Dict[str, str]:
    """{entry_id: "case 2/3"} for every entry that is one of several cases
    of the same song.
    """
    labels: Dict[str, str] = {}
    for members in group_by_song(pack.entries):
        if len(members) < 2:
            continue
        for number, entry in enumerate(members, start=1):
            labels[entry.id] = f"case {number}/{len(members)}"
    return labels


# ---------------------------------------------------------------------------
# Biome-centric cases
# ---------------------------------------------------------------------------
def biome_cases(pack: Songpack, biome_name: str,
                is_tag: bool = False) -> List[Entry]:
    """Entries whose ``biomes`` list contains a plain ``BIOME=`` match for
    ``biome_name`` (a biome *tag* condition doesn't count -- a tag can
    cover many biomes at once, so it isn't "a case of this one biome"),
    in priority order.

    With ``is_tag=True`` it is the mirror image: entries carrying a
    ``BIOMETAG=`` condition for the tag ``biome_name``. Tags compare the way
    the mod does, so ``IS_HOT``, ``is_hot`` and ``HOT`` are the same tag.
    """
    if is_tag:
        key = normalize_tag(biome_name)
        return [
            e for e in pack.entries
            if any(b.is_tag and normalize_tag(b.value) == key for b in e.biomes)
        ]
    return [
        e for e in pack.entries
        if any((not b.is_tag) and b.value == biome_name for b in e.biomes)
    ]


def add_biome_case(pack: Songpack, biome_name: str,
                   is_tag: bool = False) -> Entry:
    """Create a new, empty case (just the ``BIOME=`` -- or, with
    ``is_tag``, ``BIOMETAG=`` -- condition, no songs yet) for ``biome_name``,
    placed right after that biome's existing cases (or at the end of the
    pack if this is its first case).
    """
    existing = biome_cases(pack, biome_name, is_tag)
    new_entry = Entry(biomes=[BiomeCondition(value=biome_name, is_tag=is_tag)])
    if existing:
        last_id = existing[-1].id
        idx = next(i for i, e in enumerate(pack.entries) if e.id == last_id)
        pack.entries.insert(idx + 1, new_entry)
    else:
        pack.entries.append(new_entry)
    return new_entry


# ---------------------------------------------------------------------------
# Shared per-entry helpers
# ---------------------------------------------------------------------------
def entry_fixed_combine(entry: Entry) -> dict:
    """Return a mutable ``{category: OR|AND}`` map for the entry's fixed
    checkbox groups, creating it (with the safe OR default) if the entry
    doesn't have one yet.
    """
    fc = getattr(entry, "fixed_combine", None)
    if not isinstance(fc, dict):
        fc = {k: C.COMBINE_OR for k in C.FIXED_CATEGORY_ORDER}
        try:
            entry.fixed_combine = fc
        except Exception:
            pass
    else:
        for k in C.FIXED_CATEGORY_ORDER:
            fc.setdefault(k, C.COMBINE_OR)
    return fc
