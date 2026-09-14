"""
block_data.py
--------------
A curated list of common vanilla Minecraft block IDs (unlocalized names,
without the "minecraft:" namespace) to power the searchable block picker
in the "Block" condition section.

This list is NOT exhaustive -- Minecraft has 1000+ block states and this
tool doesn't call out to the game itself. The search box in the GUI also
accepts free typing, so any block id not listed here (including modded
ones) can still be entered manually; this list just makes the common
cases fast to find. Feel free to extend it.
"""

COMMON_BLOCK_IDS = [
    # Stone-ish / stronghold / structure signatures
    "stone", "cobblestone", "mossy_cobblestone", "deepslate", "cobbled_deepslate",
    "stone_bricks", "mossy_stone_bricks", "cracked_stone_bricks", "chiseled_stone_bricks",
    "andesite", "diorite", "granite", "smooth_stone", "bedrock",
    "end_stone", "end_stone_bricks", "purpur_block", "purpur_pillar",
    "prismarine", "prismarine_bricks", "dark_prismarine", "sea_lantern",

    # Nether
    "netherrack", "nether_bricks", "red_nether_bricks", "nether_brick_fence",
    "nether_brick_stairs", "nether_gold_ore", "nether_quartz_ore", "quartz_block",
    "soul_sand", "soul_soil", "basalt", "polished_basalt", "blackstone",
    "polished_blackstone", "polished_blackstone_bricks", "gilded_blackstone",
    "crimson_nylium", "warped_nylium", "nether_wart_block", "warped_wart_block",
    "glowstone", "magma_block", "obsidian", "crying_obsidian", "ancient_debris",
    "lodestone", "chain",

    # Ores / minerals
    "coal_ore", "deepslate_coal_ore", "iron_ore", "deepslate_iron_ore",
    "copper_ore", "deepslate_copper_ore", "gold_ore", "deepslate_gold_ore",
    "redstone_ore", "deepslate_redstone_ore", "lapis_ore", "deepslate_lapis_ore",
    "diamond_ore", "deepslate_diamond_ore", "emerald_ore", "deepslate_emerald_ore",
    "amethyst_block", "budding_amethyst", "raw_iron_block", "raw_copper_block",
    "raw_gold_block", "iron_block", "gold_block", "diamond_block", "emerald_block",
    "lapis_block", "coal_block", "redstone_block", "netherite_block",

    # Village / structures
    "bookshelf", "lectern", "bell", "hay_block", "composter", "cauldron",
    "brewing_stand", "chest", "barrel", "furnace", "blast_furnace", "smoker",
    "anvil", "chipped_anvil", "damaged_anvil", "grindstone", "loom", "cartography_table",
    "fletching_table", "smithing_table", "stonecutter", "crafting_table",

    # Ocean / river structures
    "kelp", "seagrass", "sea_pickle", "coral_block", "tube_coral_block",
    "brain_coral_block", "bubble_coral_block", "fire_coral_block", "horn_coral_block",
    "conduit",

    # End
    "end_portal_frame", "end_rod", "chorus_plant", "chorus_flower", "dragon_egg",

    # Caves / deep dark
    "sculk", "sculk_catalyst", "sculk_sensor", "sculk_shrieker", "sculk_vein",
    "reinforced_deepslate", "dripstone_block", "pointed_dripstone", "moss_block",
    "spore_blossom", "glow_lichen",

    # Natural / biome markers
    "grass_block", "dirt", "sand", "red_sand", "sandstone", "red_sandstone",
    "gravel", "clay", "ice", "packed_ice", "blue_ice", "snow_block", "snow",
    "cactus", "podzol", "mycelium", "mud", "mangrove_roots", "muddy_mangrove_roots",

    # Wood (one per family, common enough for base detection)
    "oak_log", "spruce_log", "birch_log", "jungle_log", "acacia_log",
    "dark_oak_log", "mangrove_log", "cherry_log", "crimson_stem", "warped_stem",
    "oak_planks", "spruce_planks", "birch_planks", "jungle_planks",
    "acacia_planks", "dark_oak_planks", "mangrove_planks", "cherry_planks",
    "crimson_planks", "warped_planks",

    # Redstone / functional
    "tnt", "redstone_wire", "repeater", "comparator", "observer", "piston",
    "sticky_piston", "dispenser", "dropper", "hopper", "beacon", "target",
    "spawner", "jukebox", "note_block", "campfire", "soul_campfire",
]
