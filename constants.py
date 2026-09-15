"""
constants.py
------------
Static data for the ReactiveMusic Songpack Editor: the fixed event
categories defined by MAKING_SONGPACKS.md, sensible defaults for the
dynamic (biome / dimension / block) condition types, and the tunable
weights used by the rarity-based priority algorithm (see priority.py).
 
Everything here is intentionally centralized and commented so a user who
wants to change the "rarity math" can do it in one place without touching
the GUI or YAML code.
"""

# ---------------------------------------------------------------------------
# Fixed event categories, straight from MAKING_SONGPACKS.md.
# Each is a simple checkbox group in the UI. Multiple checked items inside
# ONE category are combined with an OR ( "||" ) as documented:
#   "time - all time tags marked are listed in an OR list"
# Different categories are combined with AND (separate array items) unless
# the user chooses otherwise for the dynamic categories below.
# ---------------------------------------------------------------------------

CATEGORY_SPECIAL = "special"
CATEGORY_TIME = "time"
CATEGORY_WEATHER = "weather"
CATEGORY_HEIGHT = "height"
CATEGORY_ENTITIES = "entities"
CATEGORY_ACTIONS = "actions"
CATEGORY_LOCATION = "location"
CATEGORY_COMBAT = "combat"

FIXED_CATEGORIES = {
    CATEGORY_SPECIAL: {
        "label": "Special",
        "options": ["MAIN_MENU", "CREDITS", "HOME"],
    },
    CATEGORY_TIME: {
        "label": "Time",
        "options": ["DAY", "NIGHT", "SUNRISE", "SUNSET"],
    },
    CATEGORY_WEATHER: {
        "label": "Weather",
        "options": ["RAIN", "SNOW", "STORM"],
    },
    CATEGORY_HEIGHT: {
        "label": "World Height",
        "options": ["UNDERWATER", "UNDERGROUND", "DEEP_UNDERGROUND", "HIGH_UP"],
    },
    CATEGORY_ENTITIES: {
        "label": "Entities",
        "options": ["NEARBY_MOBS", "MINECART", "BOAT", "HORSE", "PIG"],
    },
    CATEGORY_ACTIONS: {
        "label": "Actions",
        "options": ["FISHING", "DYING"],
    },
    CATEGORY_LOCATION: {
        "label": "Location",
        "options": ["VILLAGE"],
    },
    CATEGORY_COMBAT: {
        "label": "Combat",
        "options": ["BOSS"],
    },
}

# Order the categories should be drawn in the editor.
FIXED_CATEGORY_ORDER = [
    CATEGORY_SPECIAL,
    CATEGORY_TIME,
    CATEGORY_WEATHER,
    CATEGORY_HEIGHT,
    CATEGORY_ENTITIES,
    CATEGORY_ACTIONS,
    CATEGORY_LOCATION,
    CATEGORY_COMBAT,
]

# A flat lookup: token -> category key, used when parsing an existing
# ReactiveMusic.yaml back into checkbox state.
TOKEN_TO_CATEGORY = {}
for _cat, _def in FIXED_CATEGORIES.items():
    for _opt in _def["options"]:
        TOKEN_TO_CATEGORY[_opt] = _cat

# ---------------------------------------------------------------------------
# Dynamic condition prefixes (documented in MAKING_SONGPACKS.md)
# ---------------------------------------------------------------------------
PREFIX_BIOME = "BIOME="
PREFIX_BIOMETAG = "BIOMETAG="
PREFIX_DIM = "DIM="
PREFIX_BLOCK = "BLOCK="

# Vanilla biome IDs, Minecraft Java Edition 1.16-1.21.x (verified against
# https://www.digminecraft.com/lists/biome_list_pc.php). Biome search also
# accepts free text (the mod does partial/soft matching, and modded biomes
# won't be in this list at all), so this is a convenience, not a hard
# limit -- see the "Import biome names…" button in the editor for adding
# a modpack's own biome names to this picker.
COMMON_BIOMES = [
    "badlands", "bamboo_jungle", "basalt_deltas", "beach", "birch_forest",
    "cherry_grove", "cold_ocean", "crimson_forest", "dark_forest",
    "deep_cold_ocean", "deep_dark", "deep_frozen_ocean", "deep_lukewarm_ocean",
    "deep_ocean", "desert", "dripstone_caves", "end_barrens", "end_highlands",
    "end_midlands", "eroded_badlands", "flower_forest", "forest",
    "frozen_ocean", "frozen_peaks", "frozen_river", "grove", "ice_spikes",
    "jagged_peaks", "jungle", "lukewarm_ocean", "lush_caves",
    "mangrove_swamp", "meadow", "mushroom_fields", "nether_wastes", "ocean",
    "old_growth_birch_forest", "old_growth_pine_taiga",
    "old_growth_spruce_taiga", "pale_garden", "plains", "river", "savanna",
    "savanna_plateau", "small_end_islands", "snowy_beach", "snowy_plains",
    "snowy_slopes", "snowy_taiga", "soul_sand_valley", "sparse_jungle",
    "stony_peaks", "stony_shore", "sunflower_plains", "swamp", "taiga",
    "the_end", "the_void", "warm_ocean", "warped_forest", "windswept_forest",
    "windswept_gravelly_hills", "windswept_hills", "windswept_savanna",
    "wooded_badlands",
]

# The full Fabric API "conventional biome tags" set (net.fabricmc.fabric.
# api.tag.convention.v2.ConventionalBiomeTags field names), verified
# against https://maven.fabricmc.net/docs/fabric-api-0.100.3+1.21/net/
# fabricmc/fabric/api/tag/convention/v2/ConventionalBiomeTags.html --
# these are the names MAKING_SONGPACKS.md means when it says "the IS_
# prefix is optional". Most mods that add custom biomes tag them with a
# subset of these, so a modded biome not in COMMON_BIOMES above will
# often still match a tag here.
COMMON_BIOME_TAGS = [
    "NO_DEFAULT_MONSTERS", "HIDDEN_FROM_LOCATOR_SELECTION", "IS_VOID",
    "IS_OVERWORLD", "IS_HOT", "IS_HOT_OVERWORLD", "IS_HOT_NETHER",
    "IS_TEMPERATE", "IS_TEMPERATE_OVERWORLD", "IS_COLD", "IS_COLD_OVERWORLD",
    "IS_COLD_END", "IS_WET", "IS_WET_OVERWORLD", "IS_DRY", "IS_DRY_OVERWORLD",
    "IS_DRY_NETHER", "IS_DRY_END", "IS_VEGETATION_SPARSE",
    "IS_VEGETATION_SPARSE_OVERWORLD", "IS_VEGETATION_DENSE",
    "IS_VEGETATION_DENSE_OVERWORLD", "IS_CONIFEROUS_TREE", "IS_SAVANNA_TREE",
    "IS_JUNGLE_TREE", "IS_DECIDUOUS_TREE", "IS_MOUNTAIN", "IS_MOUNTAIN_PEAK",
    "IS_MOUNTAIN_SLOPE", "IS_PLAINS", "IS_SNOWY_PLAINS", "IS_FOREST",
    "IS_BIRCH_FOREST", "IS_FLOWER_FOREST", "IS_TAIGA", "IS_OLD_GROWTH",
    "IS_HILL", "IS_WINDSWEPT", "IS_JUNGLE", "IS_SAVANNA", "IS_SWAMP",
    "IS_DESERT", "IS_BADLANDS", "IS_BEACH", "IS_STONY_SHORES", "IS_MUSHROOM",
    "IS_RIVER", "IS_OCEAN", "IS_DEEP_OCEAN", "IS_SHALLOW_OCEAN",
    "IS_UNDERGROUND", "IS_CAVE", "IS_WASTELAND", "IS_DEAD", "IS_FLORAL",
    "IS_SNOWY", "IS_ICY", "IS_AQUATIC", "IS_AQUATIC_ICY", "IS_NETHER",
    "IS_NETHER_FOREST", "IS_END", "IS_OUTER_END_ISLAND",
]

# ---------------------------------------------------------------------------
# Advanced per-entry flags, straight from MAKING_SONGPACKS.md.
# ---------------------------------------------------------------------------
COMMON_DIMENSIONS = [
    "minecraft:overworld", "minecraft:the_nether", "minecraft:the_end",
]

DEFAULT_ALLOW_FALLBACK = True  # see priority.py / README for why this
# default matters for the "don't loop the
# same rare song" requirement.
DEFAULT_FORCE_CHANCE = 1.0

MUSIC_SWITCH_SPEEDS = ["INSTANT", "SHORT", "NORMAL", "LONG"]
MUSIC_DELAY_LENGTHS = ["NONE", "SHORT", "NORMAL", "LONG"]

COMBINE_AND = "AND"
COMBINE_OR = "OR"

# ---------------------------------------------------------------------------
# Rarity / priority weights.
#
# The core idea (see priority.py for the full algorithm): every checked
# condition makes an entry *rarer* (harder to satisfy) and should push it
# *earlier* in the priority list, since the mod plays the first valid
# entry it finds top-to-bottom. Checking many options inside one OR-group
# makes that group easier to satisfy (less rare), so it should count for
# less. These numbers are starting points, not physics -- tweak freely.
# ---------------------------------------------------------------------------
CATEGORY_WEIGHTS = {
    CATEGORY_SPECIAL: 4.0,
    CATEGORY_TIME: 2.0,
    CATEGORY_WEATHER: 2.0,
    CATEGORY_HEIGHT: 3.0,
    CATEGORY_ENTITIES: 2.0,
    CATEGORY_ACTIONS: 3.0,
    CATEGORY_LOCATION: 3.0,
    CATEGORY_COMBAT: 6.0,
}

BIOME_NAME_WEIGHT = 5.0   # a specific named biome is fairly rare
BIOME_TAG_WEIGHT = 3.0    # a tag matches a whole family of biomes -> broader
DIMENSION_WEIGHT = 3.0
BLOCK_BASE_WEIGHT = 8.0   # nearby-block requirements are very specific
BLOCK_COUNT_LOG_BASE = 2  # higher required counts add a bit more rarity
