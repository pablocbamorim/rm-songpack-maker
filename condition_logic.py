"""
condition_logic.py
-------------------
Two-way conversion between an `Entry`'s structured condition state (the
checkboxes / lists the GUI edits) and the raw `events: [...]` string list
that actually gets written to / read from ReactiveMusic.yaml.

build_events(entry)   -> List[str]   (structured state -> yaml tokens)
parse_events(entry, events_list)     (yaml tokens -> structured state, in place)
entry_clauses(entry)  -> Expression  (the canonical AND-of-ORs, see conditions.py)

THE ROUND-TRIP RULE
-------------------
The structured fields are only a *projection* of the entry's real logic (the
`events` array is AND-of-ORs, see conditions.py). parse_events therefore moves
a group of conditions into a structured field ONLY when the widgets can write
it back with exactly the same meaning:

  * one YAML item ("a || b")                     -> that category, OR mode
  * several single-token items ("a", "b")        -> that category, AND mode
  * anything else, e.g. TWO OR groups in one category
    ("BIOME=a || BIOME=b", "BIOME=c || BIOME=d") -> kept VERBATIM, item by
    item, in entry.custom_raw_conditions

Keeping such items verbatim is lossless, and everything that analyses an entry
(simulator, priority, biome cases, version gating) reads them through
entry_clauses(), so they are not invisible to the rest of the app.
"""

from __future__ import annotations

from typing import List

import conditions
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
    documented behaviour. Items kept verbatim in custom_raw_conditions are
    appended unchanged (each is its own AND'd item).
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


def entry_clauses(entry: Entry) -> conditions.Expression:
    """The entry's WHOLE condition (structured fields + verbatim raw items) as
    the canonical AND-of-ORs expression. This is what analysis code must use
    instead of looking at individual GUI fields.
    """
    return conditions.parse_expression(build_events(entry))


def entry_atoms(entry: Entry) -> List[conditions.Atom]:
    """Every atom anywhere in the entry's condition (any clause)."""
    return list(conditions.iter_atoms(entry_clauses(entry)))


def canonical_events(entry: Entry) -> frozenset:
    """Order-insensitive logical form of the entry's condition."""
    return conditions.canonical(build_events(entry))


def _classify_token(token: str):
    """Return (kind, payload) for a single (already OR-split) token, where
    kind is what the STRUCTURED widgets can hold ("fixed", "biome",
    "biometag", "dim", "block") or "unknown" (-> kept verbatim).

    A token whose prefix is not written in the canonical upper case
    (``biome=forest``) is treated as unknown on purpose: re-emitting it from a
    widget would rewrite the user's text, so it stays verbatim (analysis code
    still understands it, see conditions.parse_atom).
    """
    token = token.strip()
    atom = conditions.parse_atom(token)
    if atom.kind == conditions.KIND_FIXED:
        # Exact-case tokens only; "day" stays verbatim.
        return ("fixed", token) if token in C.TOKEN_TO_CATEGORY else ("unknown", token)
    prefix = {
        conditions.KIND_BIOMETAG: C.PREFIX_BIOMETAG,
        conditions.KIND_BIOME: C.PREFIX_BIOME,
        conditions.KIND_DIM: C.PREFIX_DIM,
        conditions.KIND_BLOCK: C.PREFIX_BLOCK,
    }.get(atom.kind)
    if prefix is None or not token.startswith(prefix):
        return "unknown", token
    if atom.kind == conditions.KIND_BLOCK:
        return "block", (atom.value, atom.count)
    if atom.kind == conditions.KIND_BIOMETAG:
        return "biometag", token[len(prefix):]
    if atom.kind == conditions.KIND_BIOME:
        return "biome", token[len(prefix):]
    return "dim", token[len(prefix):]


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


def _representable(groups: list) -> bool:
    """Can ONE structured field + ONE combine mode reproduce these YAML items
    (each a list of OR'd tokens) exactly? Yes for a single item, or for items
    that are all single tokens (AND of them).
    """
    return len(groups) == 1 or all(len(g["tokens"]) == 1 for g in groups)


def parse_events(entry: Entry, events: List[str]) -> None:
    """Populate an Entry's structured fields from a raw `events` array.

    Whatever the widgets cannot represent *exactly* (an OR group mixing two
    categories, two OR groups in one category, an unrecognised token, ...) is
    kept verbatim, one array item at a time, in `entry.custom_raw_conditions`
    so neither text nor logic is ever changed (see the module docstring).

    Combine mode: a category filled from a single "a || b" item is OR; from
    several single-token items it is AND (separate items are always AND'd in
    the documented format).
    """
    # bucket -> list of {"raw": original item text, "tokens": [(kind, payload)]}
    buckets: dict = {}

    def add(bucket, raw_item, classified):
        buckets.setdefault(bucket, []).append(
            {"raw": raw_item, "tokens": classified})

    for raw_item in events:
        raw_item = str(raw_item)
        sub_tokens = [t.strip() for t in raw_item.split("||") if t.strip()]
        if not sub_tokens:
            # An empty item is still user data; keep it as it is.
            entry.custom_raw_conditions.append(raw_item)
            continue

        classified = [_classify_token(t) for t in sub_tokens]
        kinds = {k for k, _ in classified}

        if kinds == {"fixed"}:
            cats = {C.TOKEN_TO_CATEGORY[payload] for _, payload in classified}
            if len(cats) == 1:
                add(("fixed", next(iter(cats))), raw_item, classified)
                continue
        elif kinds and kinds <= {"biome", "biometag"}:
            add("biome", raw_item, classified)
            continue
        elif kinds == {"dim"}:
            add("dim", raw_item, classified)
            continue
        elif kinds == {"block"}:
            add("block", raw_item, classified)
            continue

        entry.custom_raw_conditions.append(raw_item)

    for bucket, groups in buckets.items():
        if not _representable(groups):
            # Lossless fallback: the exact original items.
            entry.custom_raw_conditions.extend(g["raw"] for g in groups)
            continue

        combine = (C.COMBINE_OR if len(groups) == 1 and len(groups[0]["tokens"]) > 1
                   else C.COMBINE_AND if len(groups) > 1
                   else None)          # one single token: mode is irrelevant

        if isinstance(bucket, tuple):               # fixed category
            cat = bucket[1]
            entry.selected.setdefault(cat, set())
            for g in groups:
                for _, payload in g["tokens"]:
                    entry.selected[cat].add(payload)
            entry.fixed_combine[cat] = combine or C.COMBINE_OR
        elif bucket == "biome":
            if combine:
                entry.biome_combine = combine
            for g in groups:
                for kind, payload in g["tokens"]:
                    entry.biomes.append(
                        BiomeCondition(value=payload, is_tag=(kind == "biometag")))
        elif bucket == "dim":
            if combine:
                entry.dimension_combine = combine
            for g in groups:
                for _, payload in g["tokens"]:
                    entry.dimensions.append(DimensionCondition(value=payload))
        elif bucket == "block":
            if combine:
                entry.block_combine = combine
            for g in groups:
                for _, payload in g["tokens"]:
                    entry.blocks.append(
                        BlockCondition(block_id=payload[0], min_count=payload[1]))
