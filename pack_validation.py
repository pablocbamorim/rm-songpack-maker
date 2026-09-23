"""
pack_validation.py
-------------------
Save-time sanity checks. Pure logic (no tkinter, no files): app_core shows the
result in a dialog and lets the user decide; nothing here edits the pack.

What is checked, and why it is a *warning* rather than a refusal
-----------------------------------------------------------------
  * an entry with NO SONGS is written as ``songs: []`` (the biome case editor
    can create one);
  * an entry with NO CONDITIONS is written as ``events: []``.
    MAKING_SONGPACKS.md never says what an empty event list means, so it is
    not assumed to be safe;
  * ``forceChance`` outside 0..1 or not a number;
  * an entry that can never play because a broader entry above it has no
    allowFallback (priority.find_unreachable_hazards).

Combinations of the forceStop* flags are NOT reported: the spec documents
them as independent switches ("Changed" is shorthand for "Valid" plus
"Invalid"), so flagging e.g. Changed+Valid would be an invented restriction.

Target-version problems are reported separately by mod_versions.validate_pack.
"""

from __future__ import annotations

import math

import constants as C
from dataclasses import dataclass
from typing import List

import condition_logic
import entry_pools
import priority
from models import Songpack

WARNING = "warning"
ERROR = "error"


@dataclass(frozen=True)
class Issue:
    level: str
    message: str

    def __str__(self) -> str:
        return self.message


def _label(entry, position: int) -> str:
    return f"Entry {position} ({entry.display_name()})"


def _fixed_condition_contradictions(entry) -> List[str]:
    """Return fixed-event combinations that cannot be true simultaneously.

    ReactiveMusic combines different event-array items with AND, so choosing
    mutually exclusive time states in separate UI checkboxes creates an entry
    that can never match. This remains a warning because the YAML format does
    not forbid such combinations and the editor must not reject authored data.
    """
    selected = entry.selected.get(C.CATEGORY_TIME, set())
    contradictions = []
    for left, right in (("DAY", "NIGHT"), ("SUNRISE", "SUNSET")):
        if left in selected and right in selected:
            contradictions.append(f"{left} + {right}")
    return contradictions


def validate_pack(pack: Songpack) -> List[Issue]:
    issues: List[Issue] = []
    entries = pack.entries

    for position, entry in enumerate(entries, start=1):
        name = _label(entry, position)
        if not any(s.strip() for s in entry.songs):
            issues.append(Issue(
                WARNING, f"{name} has no songs; it would be saved as "
                         "'songs: []' and never play anything."))
        if not condition_logic.build_events(entry):
            issues.append(Issue(
                WARNING, f"{name} has no conditions; it would be saved as "
                         "'events: []'. The songpack format does not document "
                         "what an empty event list does."))
        contradictions = _fixed_condition_contradictions(entry)
        if contradictions:
            issues.append(Issue(
                WARNING,
                f"{name} has mutually exclusive time conditions: "
                + ", ".join(contradictions) + ". This entry can never match."
            ))
        chance = entry.force_chance
        if (isinstance(chance, bool) or not isinstance(chance, (int, float))
                or math.isnan(chance) or not 0.0 <= chance <= 1.0):
            issues.append(Issue(
                ERROR, f"{name} has forceChance {chance!r}; it must be a "
                       "number from 0 to 1."))

    view = entry_pools.logical_view(entries)
    for entry, blocker in priority.find_unreachable_hazards(entries):
        issues.append(Issue(
            WARNING,
            f"Entry {view.positions.get(entry.id, '?')} ({entry.display_name()}) "
            f"can never play: entry {view.positions.get(blocker.id, '?')} "
            f"({blocker.display_name()}) above it is valid whenever it is and "
            "has no allowFallback, so it repeats instead of falling through."))
    return issues
