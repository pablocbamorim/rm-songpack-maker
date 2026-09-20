"""
mod_versions.py
----------------
Which ReactiveMusic features exist in which mod version, which mod
version is the newest one known for a given Minecraft version, and the
small JSON sidecar that remembers a songpack's intended target.

WHY THIS EXISTS
---------------
MAKING_SONGPACKS.md documents the songpack format as it stands *today*,
but a songpack is always written for a particular installed mod build.
The doc itself only version-gates one thing explicitly ("In version
1.2.0 and above, you can detect nearby blocks"), so the rest of the
matrix below comes from the mod's own Modrinth release notes.

HONESTY ABOUT THIS DATA
-----------------------
Everything in FEATURE_MIN_MOD_VERSION is backed by a release note or by
MAKING_SONGPACKS.md itself, and each line says which. Anything that
isn't backed by a source is deliberately NOT listed, which means it's
treated as "always supported" -- this editor would rather let you write
a condition your mod might not understand than block one it does.

The same applies to MC_TARGETS: it lists the newest build this editor
knows about per Minecraft version, not necessarily the newest build that
exists. The Minecraft version box is free-text and the mod version can
always be set by hand, so a newer release never locks you out.

Sources (checked 2026-09):
  https://modrinth.com/mod/reactive-music
  https://modrinth.com/mod/reactive-music/version/0.4.0+1.21
  https://modrinth.com/mod/reactive-music/version/0.5.0+1.21
  https://modrinth.com/mod/reactive-music/version/1.1.0+1.20.1
  https://modrinth.com/mod/reactive-music/version/1.2.1+1.21.9
  https://modrinth.com/mod/reactive-music/version/1.3.5+1.21.11-fabric
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple

import conditions

TARGET_FILENAME = "songpack_target.json"

# ---------------------------------------------------------------------------
# Platforms (metadata only -- see module docstring)
# ---------------------------------------------------------------------------
PLATFORM_ANY = "Any / not sure"
PLATFORM_CHOICES = [PLATFORM_ANY, "Fabric", "NeoForge", "Forge"]

PLATFORM_NOTE = (
    "Recorded for your own reference only. No documented songpack event differs between\n"
    "Fabric, Forge and NeoForge, so this never changes which conditions you can use."
)

# ---------------------------------------------------------------------------
# Minecraft version -> newest mod build this editor knows about
# ---------------------------------------------------------------------------
MC_ANY = "Any / not specified"


@dataclass(frozen=True)
class McTarget:
    mc: str
    latest_mod: Optional[str]   # None -> unknown to this editor
    note: str = ""


# Newest Minecraft first. `latest_mod` is the newest mod version this
# editor has a source for; see the module docstring.
MC_TARGETS: List[McTarget] = [
    McTarget("1.21.11", "1.3.5", "1.3.5+1.21.11-fabric (1.21.9-1.21.11)"),
    McTarget("1.21.10", "1.3.5",
             "covered by the 1.3.5+1.21.11-fabric build (1.21.9-1.21.11)"),
    McTarget("1.21.9", "1.3.5",
             "covered by the 1.3.5+1.21.11-fabric build (1.21.9-1.21.11)"),
    McTarget("1.21.8", "1.1.0", "1.1.0+1.21.8"),
    McTarget("1.21.7", "1.0.4",
             "covered by the 1.0.4+1.21.6 build (1.21.6-1.21.7)"),
    McTarget("1.21.6", "1.0.4", "1.0.4+1.21.6"),
    McTarget("1.21.5", "1.0.3",
             "covered by the 1.0.3+1.21.4 build (1.21.4-1.21.5)"),
    McTarget("1.21.4", "1.0.3", "1.0.3+1.21.4 (1.21.4-1.21.5)"),
    McTarget("1.21.3", None,
             "no build known to this editor -- set the mod version by hand"),
    McTarget("1.21.2", None,
             "no build known to this editor -- set the mod version by hand"),
    McTarget("1.21.1", "1.3.5", "1.3.5+1.21.1-fabric (1.21-1.21.1)"),
    McTarget("1.21", "1.3.5",
             "covered by the 1.3.5+1.21.1-fabric build (1.21-1.21.1)"),
    McTarget("1.20.6", "1.1.0",
             "covered by the 1.1.0+1.20.1 build (1.20.1-1.20.6)"),
    McTarget("1.20.4", "1.1.0",
             "covered by the 1.1.0+1.20.1 build (1.20.1-1.20.6)"),
    McTarget("1.20.2", "1.1.0",
             "covered by the 1.1.0+1.20.1 build (1.20.1-1.20.6)"),
    McTarget("1.20.1", "1.3.5", "1.3.5+1.20.1-fabric (1.20-1.20.1)"),
    McTarget("1.20", "1.3.5",
             "covered by the 1.3.5+1.20.1-fabric build (1.20-1.20.1)"),
    McTarget("1.19.2", "1.3.5", "1.3.5+1.19.2-fabric"),
]

MC_CHOICES = [MC_ANY] + [t.mc for t in MC_TARGETS]

# Mod versions that actually change what a songpack may contain, newest
# first. Offered in the manual-override dropdown; any other string can
# still be typed.
KNOWN_MOD_VERSIONS = ["1.3.5", "1.2.2", "1.2.1", "1.2.0", "1.1.0",
                      "1.0.4", "1.0.3", "1.0.2", "1.0.1", "0.5.0", "0.4.0", "0.3.0"]

MOD_VERSION_AUTO = "Auto (newest known for this Minecraft version)"

# ---------------------------------------------------------------------------
# Feature gates
#
# Keys are either a fixed event token (as written in the YAML), one of the
# dynamic condition prefixes without its "=", or an Entry attribute name
# for the advanced per-entry flags. A feature NOT listed here is treated
# as available in every version.
# ---------------------------------------------------------------------------
FEATURE_MIN_MOD_VERSION = {
    # 0.4.0 release notes: "Added ~50 new songpack events you can use in
    # the form of biome tags."
    "BIOMETAG": "0.4.0",

    # 0.5.0 release notes: "Added VILLAGE, BOSS, and NEARBY_MOBS as new
    # events!" and "Changed default behaviour of music picking to
    # 'fallback' ... can be disabled on entries with allowFallback: false"
    #
    # NOTE (unresolved discrepancy): that release note reads as if fallback
    # became the default in 0.5.0, while the current MAKING_SONGPACKS.md states
    # "allowFallback (default false)". The editor follows the canonical spec
    # (constants.DEFAULT_ALLOW_FALLBACK = False) and never writes
    # "allowFallback: false" by itself. Confirm against the mod's source or a
    # test build before changing either.
    "VILLAGE": "0.5.0",
    "BOSS": "0.5.0",
    "NEARBY_MOBS": "0.5.0",
    "allow_fallback": "0.5.0",

    # MAKING_SONGPACKS.md: "In version 1.2.0 and above, you can detect
    # nearby blocks in a square 25 block radius." Confirmed by the 1.2.1
    # release notes ("new BLOCK event").
    "BLOCK": "1.2.0",
}

# Human labels for the validation report.
FEATURE_LABELS = {
    "BIOMETAG": "BIOMETAG= biome tag conditions",
    "BLOCK": "BLOCK= nearby-block conditions",
    "allow_fallback": "the allowFallback flag",
}


def feature_label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, f"the {feature} event")


def requirement(feature: str) -> Optional[str]:
    """The oldest mod version that has this feature, or None if it has
    always been available (as far as this editor knows).
    """
    return FEATURE_MIN_MOD_VERSION.get(feature)


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------
def version_key(value: str) -> Tuple[int, ...]:
    """Loose numeric sort key. '1.2.1+1.21.9' -> (1, 2, 1); anything
    non-numeric in a part is dropped so hand-typed values still sort.
    """
    head = str(value).split("+")[0].split("-")[0].strip()
    parts = []
    for chunk in head.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def supports(mod_version: Optional[str], feature: str) -> bool:
    """Can a songpack aimed at `mod_version` use `feature`?

    An empty/unknown mod version means "no target chosen", and an unknown
    target never restricts anything -- the editor only ever narrows the
    UI when it actually knows the target is too old.
    """
    minimum = FEATURE_MIN_MOD_VERSION.get(feature)
    if not minimum:
        return True
    if not mod_version:
        return True
    return version_key(mod_version) >= version_key(minimum)


def latest_mod_version(mc_version: str) -> Optional[str]:
    for target in MC_TARGETS:
        if target.mc == mc_version:
            return target.latest_mod
    return None


def target_note(mc_version: str) -> str:
    for target in MC_TARGETS:
        if target.mc == mc_version:
            return target.note
    return ""


def resolve(mc_version: str, mod_version_override: str) -> Tuple[Optional[str], str]:
    """Work out which mod version a songpack is actually aimed at.

    Returns (version_or_None, explanation) where the explanation is what
    the Songpack Info tab shows next to the picker.
    """
    override = (mod_version_override or "").strip()
    if override and override != MOD_VERSION_AUTO:
        return override, f"Reactive Music {override} (set by hand)"

    mc = (mc_version or "").strip()
    if not mc or mc == MC_ANY:
        return None, ("No target set -- every documented condition stays available. "
                      "Pick a Minecraft version to have the editor check for you.")

    latest = latest_mod_version(mc)
    if latest:
        note = target_note(mc)
        suffix = f" ({note})" if note else ""
        return latest, f"Reactive Music {latest} -- newest known for Minecraft {mc}{suffix}"

    return None, (f"This editor has no release on file for Minecraft {mc}, so nothing is "
                  "restricted. Set the mod version by hand if you want it checked.")


# ---------------------------------------------------------------------------
# Validation of a whole songpack against a target
# ---------------------------------------------------------------------------
def unsupported_in_entry(entry, mod_version: Optional[str]) -> List[str]:
    """Feature keys this entry uses that the target mod version predates.

    Reads the entry's WHOLE parsed condition expression (conditions.py), not
    just the GUI fields, so a gated event hiding inside a cross-category OR
    ("BIOMETAG=IS_HOT || UNDERWATER") or a verbatim item is still found. Atoms
    are classified, never substring-searched, so "BIOMETAGS" or a biome whose
    name merely contains a token cannot cause a false positive.
    """
    if not mod_version:
        return []

    import condition_logic  # local import keeps this module dependency-free

    found = []
    for feature in conditions.features_used(condition_logic.entry_clauses(entry)):
        if not supports(mod_version, feature) and feature not in found:
            found.append(feature)
    if entry.allow_fallback and not supports(mod_version, "allow_fallback"):
        found.append("allow_fallback")

    return found


def validate_pack(pack, mod_version: Optional[str]) -> List[str]:
    """Human-readable lines describing every entry that uses something
    its target mod version doesn't have. Empty list = all good.
    """
    if not mod_version:
        return []
    problems = []
    for index, entry in enumerate(pack.entries, start=1):
        bad = unsupported_in_entry(entry, mod_version)
        if bad:
            details = ", ".join(
                f"{feature_label(f)} (needs {requirement(f)}+)" for f in bad)
            problems.append(f"{index}. {entry.display_name()}: {details}")
    return problems


# ---------------------------------------------------------------------------
# Sidecar file
#
# This is NOT written into ReactiveMusic.yaml: the mod parses that file
# into its own structures and an unknown top-level key is a needless risk.
# It sits next to it as editor metadata, exactly like
# biome_customization.json does.
# ---------------------------------------------------------------------------
def load(folder: str) -> dict:
    """Read the target sidecar. A missing or broken file just means "no
    target recorded" and must never stop a songpack from loading.
    """
    try:
        with open(os.path.join(folder, TARGET_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "minecraft_version": str(data.get("minecraft_version", "") or ""),
        "mod_version": str(data.get("mod_version", "") or ""),
        "platform": str(data.get("platform", "") or ""),
    }


def apply_to_pack(pack, data: dict) -> None:
    pack.minecraft_version = data.get("minecraft_version", "") or MC_ANY
    pack.mod_version = data.get("mod_version", "") or ""
    pack.platform = data.get("platform", "") or PLATFORM_ANY


def save(folder: str, pack) -> str:
    """Write songpack_target.json into the songpack folder, atomically."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, TARGET_FILENAME)
    fd, tmp = tempfile.mkstemp(
        prefix=".songpack_target_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "minecraft_version": pack.minecraft_version,
                    "mod_version": pack.mod_version,
                    "platform": pack.platform,
                },
                f, indent=2, ensure_ascii=False,
            )
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return target
