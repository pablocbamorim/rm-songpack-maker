"""Tests for the simulator's "focus on the matching case" helpers.

No GUI needed: the tab's _focus_cases() is just biome_cases() filtered by the
plan's valid ids and reduced by best_matching_cases(), so it is reproduced here
from the same public pieces.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import case_grouping
import condition_logic
import entry_pools
import simulation
from models import Entry, Songpack


def mk(song, events):
    entry = Entry(songs=[song])
    condition_logic.parse_events(entry, events)
    return entry


def focus(pack, name, flags, is_tag=False, biome="forest"):
    view = entry_pools.logical_view(pack.entries)
    state = (simulation.make_tag_state(name, {"minecraft:overworld"}, flags)
             if is_tag else simulation.make_state(biome, None, flags))
    plan = simulation.build_plan(view.entries, state, view.positions)
    valid = [e for e in case_grouping.biome_cases(pack, name, is_tag)
             if view.rep_of.get(e.id) in plan.valid_ids]
    return [e.songs[0] for e in case_grouping.best_matching_cases(valid)]


class TestFocus(unittest.TestCase):
    def setUp(self):
        self.pack = Songpack(entries=[
            mk("NightRain", ["BIOME=forest", "NIGHT", "RAIN"]),
            mk("Night", ["BIOME=forest", "NIGHT"]),
            mk("Day", ["BIOME=forest", "DAY"]),
            mk("Any", ["BIOME=forest"]),
            mk("GenericDay", ["DAY"]),                      # not a forest case
            mk("HotTag", ["BIOMETAG=IS_HOT", "DAY"]),       # tag case
        ])

    def test_most_specific_valid_case_wins(self):
        self.assertEqual(focus(self.pack, "forest", {"NIGHT", "RAIN"}), ["NightRain"])
        self.assertEqual(focus(self.pack, "forest", {"NIGHT"}), ["Night"])
        self.assertEqual(focus(self.pack, "forest", {"DAY"}), ["Day"])

    def test_falls_back_to_the_unconditioned_case(self):
        self.assertEqual(focus(self.pack, "forest", {"SUNSET"}), ["Any"])

    def test_generic_entries_are_not_cases_of_the_biome(self):
        self.assertNotIn("GenericDay", focus(self.pack, "forest", {"DAY"}))

    def test_no_valid_case_gives_empty_focus(self):
        pack = Songpack(entries=[mk("Night", ["BIOME=forest", "NIGHT"])])
        self.assertEqual(focus(pack, "forest", {"DAY"}), [])

    def test_tag_subject_uses_biometag_cases(self):
        self.assertEqual(focus(self.pack, "IS_HOT", {"DAY"}, is_tag=True), ["HotTag"])
        self.assertEqual(focus(self.pack, "IS_HOT", {"NIGHT"}, is_tag=True), [])

    def test_ties_are_all_kept(self):
        pack = Songpack(entries=[mk("A", ["BIOME=forest", "DAY"]),
                                 mk("B", ["BIOME=forest", "DAY"])])
        self.assertEqual(sorted(focus(pack, "forest", {"DAY"})), ["A", "B"])

    def test_place_clauses_do_not_count(self):
        self.assertEqual(case_grouping.situation_specificity(
            mk("X", ["BIOME=forest", "BIOMETAG=IS_HOT"])), 0)
        self.assertEqual(case_grouping.situation_specificity(
            mk("X", ["BIOME=ocean || UNDERWATER"])), 0)   # place OR situation: still place-bound
        self.assertEqual(case_grouping.situation_specificity(
            mk("X", ["BIOME=forest", "DAY", "RAIN"])), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
