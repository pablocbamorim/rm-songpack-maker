"""
condition_logic.py
-------------------
Two-way conversion between an `Entry`'s structured condition state (the
checkboxes / lists the GUI edits) and the raw `events: [...]` string list
that actually gets written to / read from ReactiveMusic.yaml.

build_events(entry)   -> List[str]   (structured state -> yaml tokens)
parse_events(entry, events_list)     (yaml tokens -> structured state, in place)

Kept separate from models.py so the round-trip parsing logic (which has to
be defensive about hand-written / unfamiliar yaml) doesn't clutter the
plain data classes.
"""

from __future__ import annotations

from typing import List

import constants as C
from models import Entry, BiomeCondition, DimensionCondition, BlockCondition


def _or_join(tokens: List[str]) -> str:
    return " || ".join(tokens)


def build_events(entry: Entry) -> List[str]:
    """Turn an Entry's checkbox/list state into the `events` array that
    goes in the YAML file. Each fixed category becomes at most one array
    item (its selections OR'd together). Dynamic categories (biome,
    dimension, block) become one OR'd item or several AND'd items
    depending on that category's combine mode. Different categories are
    always AND'd against each other (separate array items), matching the
    documented behaviour.
    """
    events: List[str] = []

    for cat in C.FIXED_CATEGORY_ORDER:
        chosen = sorted(entry.selected.get(cat, set()))
        if not chosen:
            continue
        combine = getattr(entry, "fixed_combine", {}).get(cat, C.COMBINE_OR)
        if combine == C.COMBINE_AND:
            events.extend(chosen)
        else:
            events.append(_or_join(chosen))

    if entry.biomes:
        tokens = [b.to_token() for b in entry.biomes]
        if entry.biome_combine == C.COMBINE_OR:
            events.append(_or_join(tokens))
        else:
            events.extend(tokens)

    if entry.dimensions:
        tokens = [d.to_token() for d in entry.dimensions]
        if entry.dimension_combine == C.COMBINE_OR:
            events.append(_or_join(tokens))
        else:
            events.extend(tokens)

    if entry.blocks:
        tokens = [b.to_token() for b in entry.blocks]
        if entry.block_combine == C.COMBINE_OR:
            events.append(_or_join(tokens))
        else:
            events.extend(tokens)

    events.extend(entry.custom_raw_conditions)

    return events


def _classify_token(token: str):
    """Return (kind, payload) for a single (already OR-split) token."""
    token = token.strip()
    if token.startswith(C.PREFIX_BIOMETAG):
        return "biometag", token[len(C.PREFIX_BIOMETAG):]
    if token.startswith(C.PREFIX_BIOME):
        return "biome", token[len(C.PREFIX_BIOME):]
    if token.startswith(C.PREFIX_DIM):
        return "dim", token[len(C.PREFIX_DIM):]
    if token.startswith(C.PREFIX_BLOCK):
        payload = token[len(C.PREFIX_BLOCK):]
        if "," in payload:
            block_id, count = payload.rsplit(",", 1)
            try:
                count_i = int(count.strip())
            except ValueError:
                count_i = 1
            return "block", (block_id.strip(), count_i)
        return "block", (payload.strip(), 1)
    if token in C.TOKEN_TO_CATEGORY:
        return "fixed", token
    return "unknown", token


def summarize_entry(entry: Entry, max_len: int = 60) -> str:
    """A short, human-readable summary of an entry's trigger conditions,
    for display next to it in list views (e.g. "DAY & BIOME=MOUNTAIN").
    """
    events = build_events(entry)
    if not events:
        return "(no conditions -- always matches)"
    text = " & ".join(events)
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def parse_events(entry: Entry, events: List[str]) -> None:
    """Populate an Entry's structured fields from a raw `events` array.
    Anything that can't be cleanly represented by the structured UI
    (e.g. an OR group mixing two different categories, or an unrecognised
    token) is preserved verbatim in `entry.custom_raw_conditions` so
    nothing is silently dropped on save.

    Combine-mode detection: if a dynamic category's values all came from
    a single array element joined with "||", that's OR. If they came from
    two or more *separate* array elements, that's AND (separate elements
    are always AND'd per the documented format). This is a best-effort
    heuristic for hand-written files; anything genuinely ambiguous falls
    back to AND, the more common real-world pattern (e.g. the fortress
    example in MAKING_SONGPACKS.md).
    """
    biome_groups: List[list] = []
    dim_groups: List[list] = []
    block_groups: List[list] = []
    fixed_groups: dict = {
        cat: [] for cat in C.FIXED_CATEGORY_ORDER
    }

    for raw_item in events:
        raw_item = str(raw_item)
        sub_tokens = [t.strip() for t in raw_item.split("||") if t.strip()]
        if not sub_tokens:
            continue

        classified = [_classify_token(t) for t in sub_tokens]
        kinds = {k for k, _ in classified}

        # Simple, single-category group -> map onto the structured UI.
        if kinds == {"fixed"}:
            cats = {C.TOKEN_TO_CATEGORY[payload] for _, payload in classified}
            if len(cats) == 1:
                cat = next(iter(cats))
                fixed_groups[cat].append(classified)
                continue

        if kinds <= {"biome", "biometag"} and kinds:
            biome_groups.append(classified)
            continue

        if kinds == {"dim"}:
            dim_groups.append(classified)
            continue

        if kinds == {"block"}:
            block_groups.append(classified)
            continue

        # Mixed / unrecognised group -> preserve verbatim.
        entry.custom_raw_conditions.append(raw_item)

    def _finalize(groups, combine_attr, append_fn):
        if not groups:
            return
        if len(groups) == 1:
            setattr(entry, combine_attr, C.COMBINE_OR if len(
                groups[0]) > 1 else getattr(entry, combine_attr))
        else:
            setattr(entry, combine_attr, C.COMBINE_AND)
        for group in groups:
            for kind, payload in group:
                append_fn(kind, payload)

    for cat, groups in fixed_groups.items():
        if not groups:
            continue
        entry.selected.setdefault(cat, set())
        for group in groups:
            for _, payload in group:
                entry.selected[cat].add(payload)
        # One YAML array item containing several tokens is OR. Separate
        # array items are AND, even when they happen to belong to the same
        # fixed checkbox category.
        entry.fixed_combine[cat] = (
            C.COMBINE_OR if len(groups) == 1 and len(groups[0]) > 1
            else C.COMBINE_AND if len(groups) > 1
            else C.COMBINE_OR
        )

    _finalize(
        biome_groups, "biome_combine",
        lambda kind, payload: entry.biomes.append(
            BiomeCondition(value=payload, is_tag=(kind == "biometag"))),
    )
    _finalize(
        dim_groups, "dimension_combine",
        lambda kind, payload: entry.dimensions.append(
            DimensionCondition(value=payload)),
    )
    _finalize(
        block_groups, "block_combine",
        lambda kind, payload: entry.blocks.append(
            BlockCondition(block_id=payload[0], min_count=payload[1])),
    )
