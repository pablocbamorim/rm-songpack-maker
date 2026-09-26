"""
time_pooling.py
---------------
Output-time transform: expand place-conditioned entries with no time-of-day
condition into one real pool for each possible time value.

ReactiveMusic treats DAY/NIGHT/SUNRISE/SUNSET as a closed, exactly-one-true
domain. An entry that names a biome or biome tag but leaves time unspecified
cannot share a rotation with the corresponding per-time entries: the mod
still stops at the first valid entry. This transform makes the unspecified
entry explicit on every time-axis value before biome pooling reasons about
place overlap.

Only NORMAL-scope entries with a place condition are considered. A matching
sibling must have exactly one bare time token as its entire time condition,
the same non-time clauses, the same flags/scope, and the same extra YAML
fields. More complicated time expressions are deliberately left alone and
reported as warnings.

The transform works on entry_pools.logical_view(), because that is the shape
ReactiveMusic will actually read and write. It never mutates the caller.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import condition_logic
import conditions
import constants as C
import entry_pools
from models import Entry


_TIME_TOKENS = tuple(C.FIXED_CATEGORIES[C.CATEGORY_TIME]["options"])
_TIME_TOKEN_SET = frozenset(_TIME_TOKENS)
_PLACE_KINDS = (conditions.KIND_BIOME, conditions.KIND_BIOMETAG)


@dataclass
class TimePoolingReport:
    """What the time-axis transform did, for save status / diagnostics."""
    created: int = 0
    merged: int = 0
    dropped: int = 0
    skipped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class TimePoolingResult:
    """The logical entries as they should be written, plus the report."""
    entries: List[Entry]
    report: TimePoolingReport


def _is_time_atom(atom) -> bool:
    """Return whether an atom is one of the four closed time values."""
    return (atom.kind == conditions.KIND_FIXED
            and atom.value.upper() in _TIME_TOKEN_SET)


def _has_place_condition(entry: Entry) -> bool:
    """Return whether the whole expression contains BIOME=/BIOMETAG=."""
    return any(
        atom.kind in _PLACE_KINDS
        for atom in condition_logic.entry_atoms(entry)
    )


def _has_time_atom(entry: Entry) -> bool:
    """Return whether any time atom occurs anywhere in the expression."""
    return any(_is_time_atom(atom) for atom in condition_logic.entry_atoms(entry))


def _non_time_key(entry: Entry) -> tuple:
    """Canonical key for every condition clause after removing time atoms."""
    clauses = []
    for clause in condition_logic.entry_clauses(entry):
        atoms = frozenset(atom.key for atom in clause if not _is_time_atom(atom))
        if atoms:
            clauses.append(atoms)
    return tuple(sorted(clauses, key=repr))


def _situation_key(entry: Entry) -> tuple:
    """Everything that must match before two time variants can share a pool."""
    return (
        _non_time_key(entry),
        bool(entry.allow_fallback),
        bool(entry.force_stop_on_changed),
        bool(entry.force_stop_on_valid),
        bool(entry.force_stop_on_invalid),
        bool(entry.force_start_on_valid),
        float(entry.force_chance),
        getattr(entry, "scope", C.SCOPE_NORMAL),
        entry_pools._extras_key(entry),
    )


def _bare_time_token(entry: Entry):
    """Return the sole time token when there is exactly one bare time clause.

    A time OR such as DAY || NIGHT and mixed clauses such as
    DAY || BIOME=forest are intentionally not siblings.
    """
    clauses = list(condition_logic.entry_clauses(entry))
    time_clauses = [
        clause for clause in clauses
        if any(_is_time_atom(atom) for atom in clause)
    ]
    if len(time_clauses) != 1:
        return None
    clause = time_clauses[0]
    if len(clause) != 1:
        return None
    atom = clause[0]
    if not _is_time_atom(atom):
        return None
    return atom.value.upper()


def _build_time_entry(template: Entry, token: str) -> Entry:
    """Copy template metadata and non-time conditions, then add one time."""
    events = []
    for clause in condition_logic.entry_clauses(template):
        atoms = [atom.text for atom in clause if not _is_time_atom(atom)]
        if atoms:
            events.append(" || ".join(atoms))
    events.insert(0, token)

    result = Entry(
        songs=list(template.songs),
        allow_fallback=template.allow_fallback,
        force_stop_on_changed=template.force_stop_on_changed,
        force_stop_on_valid=template.force_stop_on_valid,
        force_stop_on_invalid=template.force_stop_on_invalid,
        force_start_on_valid=template.force_start_on_valid,
        force_chance=template.force_chance,
        scope=template.scope,
        extra_fields=copy.deepcopy(template.extra_fields),
    )
    condition_logic.parse_events(result, events)
    return result


def expand_time_floaters(entries: List[Entry]) -> TimePoolingResult:
    """Expand eligible place-conditioned, time-agnostic logical entries."""
    report = TimePoolingReport()
    logical = entry_pools.logical_view(entries).entries
    working = [copy.deepcopy(entry) for entry in logical]

    by_situation: Dict[tuple, List[int]] = defaultdict(list)
    for index, entry in enumerate(logical):
        if (entry.scope == C.SCOPE_NORMAL and entry.songs
                and _has_place_condition(entry)):
            by_situation[_situation_key(entry)].append(index)

    sibling_by_key: Dict[Tuple[tuple, str], int] = {}
    ambiguous_by_situation = set()
    for key, indices in by_situation.items():
        for index in indices:
            token = _bare_time_token(logical[index])
            if token is not None:
                sibling_by_key.setdefault((key, token), index)
            elif _has_time_atom(logical[index]):
                ambiguous_by_situation.add(key)

    remove = set()
    created_at: Dict[int, List[Entry]] = defaultdict(list)
    late_sibling_warnings = set()

    for index, floater in enumerate(logical):
        if (floater.scope != C.SCOPE_NORMAL or not floater.songs
                or not _has_place_condition(floater)
                or _has_time_atom(floater)):
            continue

        if (floater.force_stop_on_changed or floater.force_stop_on_valid
                or floater.force_stop_on_invalid
                or floater.force_start_on_valid):
            report.skipped.append(
                f"{condition_logic.summarize_entry(floater, 70)}: time-agnostic "
                "entry uses forceStop*/forceStart*, so its own validity timing "
                "must remain unchanged.")
            continue

        key = _situation_key(floater)
        if key in ambiguous_by_situation:
            report.warnings.append(
                f"{condition_logic.summarize_entry(floater, 70)}: a sibling "
                "has a non-bare time expression; it was left untouched, so "
                "the generated single-time pools may overlap it.")

        for token in _TIME_TOKENS:
            sibling = sibling_by_key.get((key, token))
            if sibling is not None and sibling != index:
                if sibling > index and token not in late_sibling_warnings:
                    late_sibling_warnings.add(token)
                    report.warnings.append(
                        f"{condition_logic.summarize_entry(floater, 70)}: the "
                        f"{token} sibling occurs later in priority order; merging "
                        "into it can change reachability across intervening entries.")
                working[sibling].songs = list(
                    dict.fromkeys(working[sibling].songs + floater.songs))
                report.merged += 1
            else:
                created_at[index].append(_build_time_entry(floater, token))
                report.created += 1

        remove.add(index)
        report.dropped += 1

    out: List[Entry] = []
    for index, entry in enumerate(working):
        out.extend(created_at.get(index, ()))
        if index not in remove:
            out.append(entry)

    return TimePoolingResult(entries=out, report=report)
