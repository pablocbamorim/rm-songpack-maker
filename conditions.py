"""
conditions.py
--------------
The ONE interpretation of a ReactiveMusic ``events`` expression that every
part of the editor shares. Nothing in here touches tkinter, models or I/O.

THE MODEL
---------
MAKING_SONGPACKS.md defines an entry's ``events`` as an array in which

  * every array item must be true            (AND between items), and
  * inside one item, ``a || b`` is an OR     (any option is enough).

That is a conjunction of disjunctions, so the canonical expression here is

    Expression = List[Clause]          # AND of the clauses
    Clause     = List[Atom]            # OR  of the atoms

Atoms may be of ANY category, so ``"BIOME=ocean || UNDERWATER"`` is simply a
clause with a biome atom and a fixed-event atom. Nothing in the app needs to
guess with string heuristics: the simulator, priority scoring, biome case
discovery, chart highlighting, version gating and validation all ask this
module ("which atoms are in this entry?", "does this BIOME= match that biome?")
instead of each re-parsing text their own way.

The structured GUI fields on ``Entry`` (checkbox sets, biome lists, ...) are a
*projection* of this expression for the cases the widgets can represent
exactly; anything else is kept verbatim in ``Entry.custom_raw_conditions`` and
still flows through here (see condition_logic.entry_clauses).

SOFT MATCHING (BIOME= / DIM=)
-----------------------------
MAKING_SONGPACKS.md: ``BIOME=biomename`` "can be the full biome name or just a
part of it if you want to soft-search" ("any biome with cherry in the name"),
and ``BIOME=modname:custom_biome_name`` is the hyper-specific form; ``DIM=``
"can be the fully typed name or just a subset of it". soft_match() implements
exactly that in ONE place:

  * a value WITHOUT a namespace is a substring of the biome's path
    ("forest" matches forest, dark_forest, flower_forest, ...);
  * a value WITH a namespace ("minecraft:forest") is a substring of the full
    id, so it is NOT reduced to the broad substring "forest".

ASSUMPTION (not stated in the spec): the mod is assumed to test a
namespace-less value against the path only, not against "minecraft:...".
If the mod turns out to match the whole id, change soft_match() and every
view follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, List, Optional, Sequence, Tuple

import constants as C

KIND_FIXED = "fixed"
KIND_BIOME = "biome"
KIND_BIOMETAG = "biometag"
KIND_DIM = "dim"
KIND_BLOCK = "block"
KIND_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------
def normalize_tag(name: str) -> str:
    """'IS_HOT', 'is_hot' and 'HOT' are the same tag (the prefix is optional)."""
    text = str(name).strip().upper()
    return text[3:] if text.startswith("IS_") else text


def full_id(identifier: str) -> str:
    """Lower-cased ``namespace:path``; a bare name is a vanilla one."""
    text = str(identifier).strip().lower()
    if not text:
        return ""
    return text if ":" in text else "minecraft:" + text


def soft_match(want: str, identifier: str) -> bool:
    """Does a ``BIOME=`` / ``DIM=`` value match a biome / dimension id?
    See the module docstring for the rules and the one assumption.
    """
    want = str(want).strip().lower()
    have = full_id(identifier)
    if not want or not have:
        return False
    if ":" in want:
        return want in have
    return want in have.split(":", 1)[1]


def is_broad_biome_value(value: str) -> bool:
    """True for a value that is a bare substring rather than a specific id."""
    return ":" not in str(value)


# ---------------------------------------------------------------------------
# Atoms
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Atom:
    """One ``||``-free condition. ``value`` is the biome/tag/dim/block id (or
    the fixed token); ``count`` is only meaningful for blocks.
    """
    kind: str
    value: str
    count: int = 1
    text: str = ""            # the token exactly as written

    @property
    def key(self) -> str:
        """Normalised identity, for comparing/canonicalising expressions."""
        if self.kind == KIND_FIXED:
            return self.value.upper()
        if self.kind == KIND_BIOMETAG:
            return "biometag:" + normalize_tag(self.value)
        if self.kind == KIND_BLOCK:
            return f"block:{self.value.strip().lower()},{self.count}"
        if self.kind in (KIND_BIOME, KIND_DIM):
            return f"{self.kind}:{self.value.strip().lower()}"
        return "raw:" + self.text.strip().lower()

    @property
    def feature(self) -> Optional[str]:
        """The mod_versions feature key this atom depends on, if any. Fixed
        tokens are their own key; the dynamic kinds use the prefix name.
        """
        if self.kind == KIND_FIXED:
            return self.value.upper()
        if self.kind == KIND_BIOMETAG:
            return "BIOMETAG"
        if self.kind == KIND_BLOCK:
            return "BLOCK"
        return None


Clause = List[Atom]
Expression = List[Clause]


def _parse_block(payload: str) -> Tuple[str, int]:
    if "," in payload:
        block_id, count = payload.rsplit(",", 1)
        try:
            need = int(count.strip())
        except ValueError:
            need = 1
    else:
        block_id, need = payload, 1
    return block_id.strip(), need


def parse_atom(token: str) -> Atom:
    """Classify one ``||``-free token. Prefixes and fixed tokens are matched
    case-insensitively, the same way the simulator always did.
    """
    text = str(token).strip()
    up = text.upper()
    if up in C.TOKEN_TO_CATEGORY:
        return Atom(KIND_FIXED, up, text=text)
    # ("BIOMETAG=" does not start with "BIOME=", so the order is not
    # load-bearing; BIOMETAG is simply listed first for readability.)
    if up.startswith(C.PREFIX_BIOMETAG):
        return Atom(KIND_BIOMETAG, text[len(C.PREFIX_BIOMETAG):].strip(),
                    text=text)
    if up.startswith(C.PREFIX_BIOME):
        return Atom(KIND_BIOME, text[len(C.PREFIX_BIOME):].strip(), text=text)
    if up.startswith(C.PREFIX_DIM):
        return Atom(KIND_DIM, text[len(C.PREFIX_DIM):].strip(), text=text)
    if up.startswith(C.PREFIX_BLOCK):
        block_id, need = _parse_block(text[len(C.PREFIX_BLOCK):])
        return Atom(KIND_BLOCK, block_id, need, text=text)
    return Atom(KIND_UNKNOWN, text, text=text)


def parse_item(item: str) -> Clause:
    """One ``events`` array item -> its OR'd atoms (empty parts dropped)."""
    return [parse_atom(part) for part in str(item).split("||") if part.strip()]


def parse_expression(events: Iterable[str]) -> Expression:
    """A whole ``events`` array -> AND of clauses."""
    clauses = []
    for item in events:
        clause = parse_item(item)
        if clause:
            clauses.append(clause)
    return clauses


def iter_atoms(expression: Expression) -> Iterator[Atom]:
    for clause in expression:
        yield from clause


def canonical(expression_or_events) -> frozenset:
    """Order- and duplicate-insensitive form of an expression, for comparing
    logic across a save/load: ``frozenset({frozenset({atom key, ...}), ...})``.
    Accepts either an Expression or a raw ``events`` list of strings.
    """
    items = list(expression_or_events)
    if items and isinstance(items[0], str):
        items = parse_expression(items)
    return frozenset(frozenset(a.key for a in clause) for clause in items
                     if clause)


def features_used(expression: Expression) -> List[str]:
    """Version-gate feature keys used anywhere in the expression, in order,
    without duplicates.
    """
    found: List[str] = []
    for atom in iter_atoms(expression):
        feature = atom.feature
        if feature and feature not in found:
            found.append(feature)
    return found


# ---------------------------------------------------------------------------
# Implication (used to warn about entries that can never be reached)
# ---------------------------------------------------------------------------
def atom_implies(x: Atom, y: Atom) -> bool:
    """Sound (never over-claims) test that "x true" makes "y true"."""
    if x.kind != y.kind:
        return False
    if x.kind == KIND_FIXED:
        return x.value.upper() == y.value.upper()
    if x.kind == KIND_BIOMETAG:
        return normalize_tag(x.value) == normalize_tag(y.value)
    if x.kind == KIND_BLOCK:
        return (x.value.strip().lower() == y.value.strip().lower()
                and x.count >= y.count)
    if x.kind in (KIND_BIOME, KIND_DIM):
        xv, yv = x.value.strip().lower(), y.value.strip().lower()
        if not yv:
            return False
        if xv == yv:
            return True
        # Every id containing xv also contains yv when yv is a substring of
        # xv -- but only within the same matching domain (path vs full id).
        if ":" in yv:
            return yv in xv and ":" in xv
        return yv in (xv.split(":", 1)[1] if ":" in xv else xv)
    return x.key == y.key


def clause_implies(cx: Clause, cy: Clause) -> bool:
    """(x1 OR x2 ...) implies (y1 OR y2 ...) when each xi implies some yj."""
    return bool(cx) and all(any(atom_implies(x, y) for y in cy) for x in cx)


def expression_implies(ex: Expression, ey: Expression) -> bool:
    """Whenever ``ex`` is true, ``ey`` is certainly true (sound, incomplete):
    every clause of ey must be implied by some clause of ex.
    """
    return all(any(clause_implies(cx, cy) for cx in ex) for cy in ey)
