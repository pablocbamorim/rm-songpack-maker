"""Tests for time_pooling: place-conditioned time floaters become real per-time pools."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import biome_pooling
import condition_logic
import constants as C
import time_pooling
from models import Entry


def mk(songs, events, **flags):
    entry = Entry(songs=list(songs), **flags)
    condition_logic.parse_events(entry, events)
    return entry


class TestTimePooling(unittest.TestCase):
    def test_merges_existing_day_and_creates_missing_times(self):
        entries = [
            mk(["day-song"], ["DAY", "BIOMETAG=IS_FOREST"]),
            mk(["floater"], ["BIOMETAG=IS_FOREST"]),
        ]
        result = time_pooling.expand_time_floaters(entries)

        self.assertEqual(result.report.merged, 1)
        self.assertEqual(result.report.created, 3)
        self.assertEqual(result.report.dropped, 1)

        by_time = {}
        for entry in result.entries:
            events = condition_logic.build_events(entry)
            token = next(t for t in C.FIXED_CATEGORIES[C.CATEGORY_TIME]["options"]
                         if t in events)
            by_time[token] = entry.songs

        self.assertEqual(by_time["DAY"], ["day-song", "floater"])
        self.assertEqual(by_time["NIGHT"], ["floater"])
        self.assertEqual(by_time["SUNRISE"], ["floater"])
        self.assertEqual(by_time["SUNSET"], ["floater"])

    def test_no_matching_siblings_creates_four_entries(self):
        result = time_pooling.expand_time_floaters(
            [mk(["floater"], ["BIOMETAG=IS_FOREST"])]
        )
        self.assertEqual(result.report.created, 4)
        self.assertEqual(result.report.merged, 0)
        self.assertEqual(result.report.dropped, 1)
        self.assertEqual(len(result.entries), 4)
        self.assertEqual(
            sorted(condition_logic.build_events(e)[0] for e in result.entries),
            sorted(C.FIXED_CATEGORIES[C.CATEGORY_TIME]["options"]),
        )
        self.assertTrue(all(e.songs == ["floater"] for e in result.entries))

    def test_or_time_sibling_is_not_treated_as_exact_sibling(self):
        entries = [
            mk(["or-sibling"], ["DAY || NIGHT", "BIOMETAG=IS_FOREST"]),
            mk(["floater"], ["BIOMETAG=IS_FOREST"]),
        ]
        result = time_pooling.expand_time_floaters(entries)

        self.assertEqual(result.report.created, 4)
        self.assertEqual(result.report.merged, 0)
        self.assertEqual(result.report.dropped, 1)
        self.assertEqual(len(result.report.warnings), 1)
        self.assertEqual(len(result.entries), 5)
        self.assertIn(["DAY || NIGHT", "BIOMETAG=IS_FOREST"],
                      [condition_logic.build_events(e) for e in result.entries])

    def test_later_sibling_is_reported(self):
        entries = [
            mk(["floater"], ["BIOMETAG=IS_FOREST"]),
            mk(["day-song"], ["DAY", "BIOMETAG=IS_FOREST"]),
        ]
        result = time_pooling.expand_time_floaters(entries)
        self.assertEqual(result.report.merged, 1)
        self.assertTrue(any("later in priority order" in warning
                            for warning in result.report.warnings))

    def test_force_flags_are_left_untouched(self):
        original = mk(["floater"], ["BIOMETAG=IS_FOREST"],
                      force_stop_on_changed=True)
        result = time_pooling.expand_time_floaters([original])

        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].songs, ["floater"])
        self.assertEqual(result.report.created, 0)
        self.assertEqual(result.report.dropped, 0)
        self.assertEqual(len(result.report.skipped), 1)

    def test_input_is_not_mutated(self):
        original = mk(["floater"], ["BIOMETAG=IS_FOREST"])
        before = condition_logic.build_events(original)
        time_pooling.expand_time_floaters([original])
        self.assertEqual(condition_logic.build_events(original), before)
        self.assertEqual(original.songs, ["floater"])

    def test_time_expansion_runs_before_biome_pooling(self):
        entries = [
            mk(["floater"], ["BIOMETAG=IS_PLAINS"]),
            mk(["day-song"], ["DAY", "BIOMETAG=IS_PLAINS"]),
        ]
        time_result = time_pooling.expand_time_floaters(entries)
        biome_result = biome_pooling.pool_overlapping_biomes(
            time_result.entries,
            biomes=["plains"],
            tags_of=lambda biome: {"IS_PLAINS"} if biome == "plains" else set(),
            residual_fallback=False,
        )
        day_entries = [
            e for e in biome_result.entries
            if "DAY" in condition_logic.build_events(e)
        ]
        self.assertTrue(any(set(e.songs) == {"floater", "day-song"}
                            for e in day_entries))

    def test_non_place_time_agnostic_entry_is_untouched(self):
        original = mk(["globalish"], ["RAIN"])
        result = time_pooling.expand_time_floaters([original])
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].songs, ["globalish"])
        self.assertEqual(result.report.dropped, 0)
