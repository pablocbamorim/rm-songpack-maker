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
CATEGORY_UNDERWATER = "underwater"
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
        "options": ["UNDERGROUND", "DEEP_UNDERGROUND", "HIGH_UP"],
    },
    CATEGORY_UNDERWATER: {
        "label": "Underwater",
        "options": ["UNDERWATER"],
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
    CATEGORY_UNDERWATER,
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

# MAKING_SONGPACKS.md: "allowFallback (default false)". The editor follows that and
# never writes allowFallback: false by itself; users opt into fallback per entry.
# (An older comment here said the default was true, and the 0.5.0 release note
# quoted in mod_versions.py reads as if it changed; unconfirmed, see the note there.)
DEFAULT_ALLOW_FALLBACK = False
DEFAULT_FORCE_CHANCE = 1.0

MUSIC_SWITCH_SPEEDS = ["INSTANT", "SHORT", "NORMAL", "LONG"]
MUSIC_DELAY_LENGTHS = ["NONE", "SHORT", "NORMAL", "LONG"]

COMBINE_AND = "AND"
COMBINE_OR = "OR"

# ---------------------------------------------------------------------------
# Entry scope (editor-only; never written into ReactiveMusic.yaml itself, see
# scopes.py). A "global" or "default" entry has no BIOME= condition and is
# pinned BELOW every normal entry, so it is only reached in situations where
# no biome-specific entry wins -- or where the winning entries have
# allowFallback on and run out of songs.
#
#   normal  an ordinary entry
#   global  should play everywhere its conditions hold; the editor checks
#           that no entry above it blocks it (scopes.find_blockers)
#   default a gap filler: plays only where nothing above it handles the
#           situation. No blocker check, being blocked is the point.
# ---------------------------------------------------------------------------
SCOPE_NORMAL = "normal"
SCOPE_GLOBAL = "global"
SCOPE_DEFAULT = "default"
SCOPES = (SCOPE_NORMAL, SCOPE_GLOBAL, SCOPE_DEFAULT)
#: Lower rank = higher in the priority list.
SCOPE_RANK = {SCOPE_NORMAL: 0, SCOPE_GLOBAL: 1, SCOPE_DEFAULT: 2}
SCOPE_LABELS = {SCOPE_NORMAL: "Normal", SCOPE_GLOBAL: "Global",
                SCOPE_DEFAULT: "Default"}
SCOPE_BY_LABEL = {v: k for k, v in SCOPE_LABELS.items()}

# ---------------------------------------------------------------------------
# Rarity / priority weights.
#
# priority.score_entry() adds one flat weight per DISTINCT condition GROUP
# an entry touches (time, biome, height, underwater, weather, dimension,
# block, or "everything else"), once each -- no matter how many options
# inside that group are checked, and no matter whether they are combined
# with OR or AND.
#
# This used to divide a group's weight by how many options were OR'd
# together in it, on the theory that an easy-to-satisfy OR group is less
# rare. In practice that meant a song deliberately given a wide OR pool
# ("play in biome X or Y") could score LOWER than a second, unrelated song
# that is exclusive to biome X alone -- so the exclusive song always won
# the tie in biome X, and the pooled song's own turn there was never
# reached (the mod plays the first valid entry it finds top-to-bottom, and
# nothing below an entry with allowFallback off ever gets a look-in).
# Scoring by which groups are touched, not how many options are inside
# them, removes that trap: "biome X or Y" and "biome X only" now score
# identically, so they tie in priority instead of the OR'd one silently
# losing, and only entries that genuinely touch MORE groups (e.g. "biome X
# AND night") outrank a plainer one.
#
# Tying in score still doesn't make two entries SHARE a biome's rotation
# by itself -- the mod still only ever plays the first valid entry it
# finds, so a tie just changes which one of the two wins first (whichever
# was added to the editor first; see priority.auto_priority_order). For
# entries that should genuinely share a pool, use case_splitting.py's
# "Split OR conditions into cases" tool: it turns OR'd groups into
# separate AND-only cases and merges any that land on the exact same
# conditions across the WHOLE pack into one shared song pool, so two songs
# that both want "just biome X" end up in the same entry instead of one
# blocking the other.
#
# These numbers are starting points, not physics -- tweak freely.
# ---------------------------------------------------------------------------
CATEGORY_WEIGHTS = {
    CATEGORY_SPECIAL: 5.0,
    CATEGORY_TIME: 1.0,
    CATEGORY_WEATHER: 3.0,
    CATEGORY_HEIGHT: 3.0,
    CATEGORY_UNDERWATER: 3.0,
    CATEGORY_ENTITIES: 5.0,
    CATEGORY_ACTIONS: 5.0,
    CATEGORY_LOCATION: 5.0,
    CATEGORY_COMBAT: 5.0,
}

#: BIOME= and BIOMETAG= both count as the same "biome" group: a tag isn't
#: scored as broader/rarer than an exact name any more, only "a biome
#: condition was used at all" counts.
BIOME_GROUP_WEIGHT = 1.0
DIMENSION_GROUP_WEIGHT = 5.0
BLOCK_GROUP_WEIGHT = 5.0
#: Weight for any group not listed above (an unrecognised / verbatim token
#: conditions.py could not classify) -- still probably a real constraint,
#: so it is not scored as free.
DEFAULT_GROUP_WEIGHT = 5.0
