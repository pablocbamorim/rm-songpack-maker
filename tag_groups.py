"""
tag_groups.py
-------------
Pure logic for custom biome-tag groups.

A group is only a shortcut for adding/removing plain BIOMETAG= conditions.
No group membership is stored on an Entry, so the YAML format and ReactiveMusic
remain unaware of this editor-only convenience. Whether a group is applied is
derived from the tags currently present on the entry.
"""

from __future__ import annotations

from typing import Dict, List

import conditions
from models import BiomeCondition, Entry


Groups = Dict[str, List[str]]


def _entry_tag_keys(entry: Entry) -> set[str]:
    """Return normalized BIOMETAG values currently present on an entry."""
    return {
        conditions.normalize_tag(b.value)
        for b in entry.biomes
        if b.is_tag
    }


def applied_groups(entry: Entry, groups: Groups) -> List[str]:
    """Return groups whose complete tag set is present, sorted by name."""
    present = _entry_tag_keys(entry)
    return sorted(
        (
            name for name, tags in groups.items()
            if tags and all(
                conditions.normalize_tag(tag) in present for tag in tags
            )
        ),
        key=str.lower,
    )


def add_group(entry: Entry, groups: Groups, name: str) -> List[str]:
    """Add missing BIOMETAG values from a named group and return additions."""
    present = _entry_tag_keys(entry)
    added: List[str] = []
    for tag in groups.get(name, []):
        key = conditions.normalize_tag(tag)
        if key in present:
            continue
        entry.biomes.append(BiomeCondition(value=tag, is_tag=True))
        present.add(key)
        added.append(tag)
    return added


def remove_group(entry: Entry, groups: Groups, name: str) -> List[str]:
    """Remove a group's tags unless another applied group still requires them.

    The target group does not need to be completely applied for removal to
    work: any of its currently present tags are candidates for removal.
    """
    other_groups = [
        group_name
        for group_name in applied_groups(entry, groups)
        if group_name != name
    ]
    keep = {
        conditions.normalize_tag(tag)
        for group_name in other_groups
        for tag in groups[group_name]
    }
    drop = {
        conditions.normalize_tag(tag)
        for tag in groups.get(name, [])
    } - keep
    if not drop:
        return []

    removed = [
        b.value
        for b in entry.biomes
        if b.is_tag and conditions.normalize_tag(b.value) in drop
    ]
    entry.biomes = [
        b for b in entry.biomes
        if not (b.is_tag and conditions.normalize_tag(b.value) in drop)
    ]
    return removed
