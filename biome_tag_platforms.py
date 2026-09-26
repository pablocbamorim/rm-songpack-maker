"""
biome_tag_platforms.py
------------------------
Which BIOMETAG= tags actually exist on which modloader, so the editor can
stop suggesting a tag that a given platform never registers.

WHY THIS IS SEPARATE FROM constants.COMMON_BIOME_TAGS
-------------------------------------------------------
constants.COMMON_BIOME_TAGS is Fabric API's own "conventional biome tags"
set (see that constant's comment for the source), which is what the tag
picker offers today regardless of platform. Not every one of those tags is
registered the same way on Forge/NeoForge, and the namespace itself has
moved around over time:

  * Fabric has always used its own `c:`-namespaced conventional tags
    (ConventionalBiomeTags).
  * Forge historically registered its OWN `forge:`-namespaced set
    (net.minecraftforge.common.Tags.Biomes / the older BiomeDictionary),
    overlapping with Fabric's set but not identical to it.
  * NeoForge mirrored Forge's `forge:` tags at first.
  * From Minecraft 1.21 onward, Forge and NeoForge both moved onto the SAME
    `c:` namespace Fabric already used, so "Forge tags" and "Fabric tags"
    converge from that point on.

So a tag's availability is really a function of (platform, Minecraft
version), not platform alone -- and it's a *different* version axis than
mod_versions.py uses: mod_versions gates Reactive Music FEATURES against
the Reactive Music mod version; this gates biome TAGS against the
Minecraft version, since tag namespaces are a modloader/MC-ecosystem
question, not a Reactive Music release question. This module otherwise
follows mod_versions.py's shape on purpose (same "no data means
unrestricted" philosophy, same version comparison via
mod_versions.version_key) so the two read consistently.

HOW TO FILL THIS IN
--------------------
TAG_AVAILABILITY starts EMPTY on purpose. A tag with no row here -- or a
row with no entry for the platform being checked -- is treated as
available everywhere: the editor would rather offer a tag it has no
evidence against than hide one that actually works, the same stance
mod_versions.FEATURE_MIN_MOD_VERSION takes for feature gates. Filtering
only actually kicks in once a row exists AND names the platform being
checked, so this table can be filled in incrementally, tag by tag,
platform by platform, without ever over-restricting in the meantime.

Each row looks like:

    "IS_HOT": {
        "Fabric": "always",      # always available on Fabric
        "Forge": "1.21",         # available on Forge from MC 1.21 onward
                                  # (this is when Forge adopted c:)
        "NeoForge": "1.21",
    },

Rules for a row's values:
  * a platform key ABSENT from the row -> no data for that platform, so
    tag_available() does not restrict it there;
  * None -> explicitly known to NOT exist on that platform, at any version;
  * "always" (or "" ) -> exists on that platform with no version floor;
  * any other string -> the Minecraft version (not mod version!) the tag
    exists from onward, compared with mod_versions.version_key().

Platform keys are exactly the strings in mod_versions.PLATFORM_CHOICES
(minus the "Any / not sure" sentinel): "Fabric", "NeoForge", "Forge".

Add a row only once you have a source for it -- a Forge/NeoForge
Tags.Biomes / BiomeDictionary listing, a Fabric API ConventionalBiomeTags
listing, or the community `c:` biome-tag convention doc -- and comment the
source inline the same way mod_versions.FEATURE_MIN_MOD_VERSION does.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import mod_versions

# tag -> {platform: minimum Minecraft version string, "always", or None}.
# EMPTY ON PURPOSE -- see the module docstring for how (and why) to fill
# this in gradually rather than all at once.
TAG_AVAILABILITY: Dict[str, Dict[str, Optional[str]]] = {
    # --- BEGIN GENERATED (devtools/generate_biome_tag_data.py) ---
    'HIDDEN_FROM_LOCATOR_SELECTION': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_AQUATIC': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_AQUATIC_ICY': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_BADLANDS': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_BEACH': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_BIRCH_FOREST': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_CAVE': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_COLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_COLD_END': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_COLD_NETHER': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_COLD_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DARK_FOREST': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_DEAD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DEEP_OCEAN': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DENSE_VEGETATION': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DENSE_VEGETATION_END': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_DENSE_VEGETATION_NETHER': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_DENSE_VEGETATION_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DESERT': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DRY': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DRY_END': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DRY_NETHER': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_DRY_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_END': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_FLORAL': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_FLOWER_FOREST': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_FOREST': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_HILL': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_HOT': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_HOT_END': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_HOT_NETHER': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_HOT_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_ICY': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_JUNGLE': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_LUSH': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_MAGICAL': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_MOUNTAIN': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_MOUNTAIN_PEAK': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_MOUNTAIN_SLOPE': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_MUSHROOM': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_NETHER': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_NETHER_FOREST': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_OCEAN': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_OLD_GROWTH': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_OUTER_END_ISLAND': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_PLAINS': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_PLATEAU': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_RARE': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_RIVER': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SANDY': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_SAVANNA': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SHALLOW_OCEAN': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SNOWY': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SNOWY_PLAINS': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SPARSE_VEGETATION': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SPARSE_VEGETATION_END': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_SPARSE_VEGETATION_NETHER': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_SPARSE_VEGETATION_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SPOOKY': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_STONY_SHORES': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_SWAMP': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_TAIGA': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_TEMPERATE': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_TEMPERATE_END': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_TEMPERATE_NETHER': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_TEMPERATE_OVERWORLD': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_TREE_CONIFEROUS': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_TREE_DECIDUOUS': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_TREE_JUNGLE': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_TREE_SAVANNA': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_UNDERGROUND': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_VOID': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_WASTELAND': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_WET': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_WET_END': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_WET_NETHER': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'IS_WET_OVERWORLD': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'IS_WINDSWEPT': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'NO_DEFAULT_MONSTERS': {'Fabric': 'always', 'Forge': '1.21', 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_ACACIA': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_BAMBOO': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_BIRCH': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_CHERRY': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_CRIMSON': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_DARK_OAK': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_JUNGLE': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_MANGROVE': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_OAK': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_PALE_OAK': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_SPRUCE': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    'PRIMARY_WOOD_TYPE_WARPED': {'Fabric': 'always', 'Forge': None, 'NeoForge': '1.21'},
    # --- END GENERATED ---
}


def tag_available(tag: str, platform: str,
                  minecraft_version: Optional[str]) -> bool:
    """Can `tag` be offered for a songpack targeting `platform` (one of
    mod_versions.PLATFORM_CHOICES, or "" / not chosen) at
    `minecraft_version` (Songpack.minecraft_version, or "" / MC_ANY)?

    No platform chosen, no row for this tag, or no platform entry inside
    that row all mean "don't restrict" -- see the module docstring.
    """
    if not platform or platform == mod_versions.PLATFORM_ANY:
        return True
    row = TAG_AVAILABILITY.get(tag)
    if row is None or platform not in row:
        return True
    floor = row[platform]
    if floor is None:
        return False
    if not floor or floor == "always":
        return True
    version = (minecraft_version or "").strip()
    if not version or version == mod_versions.MC_ANY:
        return True
    return mod_versions.version_key(version) >= mod_versions.version_key(floor)


def filter_available(tags: Iterable[str], platform: str,
                     minecraft_version: Optional[str]) -> List[str]:
    """The subset of `tags` available on `platform`/`minecraft_version`,
    order preserved. Convenience wrapper around tag_available() for the
    picker lists (constants.COMMON_BIOME_TAGS and similar).
    """
    return [t for t in tags if tag_available(t, platform, minecraft_version)]
