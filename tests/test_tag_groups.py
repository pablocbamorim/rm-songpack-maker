"""Regression tests for custom biome-tag group semantics."""

import unittest

from models import BiomeCondition, Entry
import tag_groups


class TagGroupTests(unittest.TestCase):
    def test_add_group_adds_missing_tags_without_duplicates(self):
        entry = Entry(biomes=[BiomeCondition("HOT", True)])
        groups = {"basic": ["IS_HOT", "IS_FOREST"]}

        added = tag_groups.add_group(entry, groups, "basic")

        self.assertEqual(added, ["IS_FOREST"])
        self.assertEqual([b.value for b in entry.biomes], ["HOT", "IS_FOREST"])

    def test_applied_group_requires_all_tags(self):
        entry = Entry(biomes=[
            BiomeCondition("HOT", True),
            BiomeCondition("FOREST", True),
        ])
        groups = {"basic": ["IS_HOT", "IS_FOREST"], "other": ["IS_HOT"]}

        self.assertEqual(tag_groups.applied_groups(entry, groups), ["basic", "other"])

    def test_remove_group_keeps_tags_required_by_other_applied_group(self):
        entry = Entry(biomes=[
            BiomeCondition("IS_HOT", True),
            BiomeCondition("IS_FOREST", True),
            BiomeCondition("IS_RIVER", True),
        ])
        groups = {
            "basic": ["IS_HOT", "IS_FOREST"],
            "water": ["IS_FOREST", "IS_RIVER"],
        }

        removed = tag_groups.remove_group(entry, groups, "basic")

        self.assertEqual(removed, ["IS_HOT"])
        self.assertEqual(
            [b.value for b in entry.biomes],
            ["IS_FOREST", "IS_RIVER"],
        )

    def test_remove_group_drops_present_tags_even_when_group_is_partial(self):
        entry = Entry(biomes=[BiomeCondition("IS_HOT", True)])
        groups = {"basic": ["IS_HOT", "IS_FOREST"]}

        removed = tag_groups.remove_group(entry, groups, "basic")

        self.assertEqual(removed, ["IS_HOT"])
        self.assertEqual(entry.biomes, [])


if __name__ == "__main__":
    unittest.main()
