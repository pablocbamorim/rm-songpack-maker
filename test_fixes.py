"""Regression tests for the four fixes:

1. priority.is_broader_than() -- real implication check
2. scopes.find_blockers() -- catches BIOME=/BIOMETAG= in verbatim items
3. entry_pools.logical_view() -- positions match the scope-sorted order
4. yaml_io.load_songpack() -- top-level scalar fields are type-checked
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import constants as C
import priority
import scopes
import entry_pools
import yaml_io
from models import Entry, Songpack


def mk(songs=None, scope=C.SCOPE_NORMAL, selected=None, biomes=None,
       custom=None):
    e = Entry()
    e.songs = songs or ["Song"]
    e.scope = scope
    if selected:
        for cat, opts in selected.items():
            e.selected[cat] = set(opts)
    if biomes:
        from models import BiomeCondition
        e.biomes = [BiomeCondition(value=v, is_tag=tag) for v, tag in biomes]
    if custom:
        e.custom_raw_conditions = list(custom)
    return e


class TestIsBroaderThan(unittest.TestCase):
    def test_old_reproduction_was_never_broken(self):
        # candidate=DAY, specific=DAY||NIGHT (single category). Whenever
        # specific holds it could be NIGHT, where candidate (DAY) does not
        # hold -- so candidate is correctly NOT broader here. This matches
        # what the old category-subset heuristic also returned (False, via
        # its strict-subset-of-categories guard), which is why this
        # particular reproduction never actually demonstrated the bug --
        # see test_disjoint_category_bug_is_fixed for a case that does.
        candidate = mk(selected={C.CATEGORY_TIME: {"DAY"}})
        specific = mk(selected={C.CATEGORY_TIME: {"DAY", "NIGHT"}})
        self.assertFalse(priority.is_broader_than(candidate, specific))

    def test_disjoint_category_bug_is_fixed(self):
        # candidate=DAY, specific=(DAY||NIGHT) AND UNDERWATER.
        # specific is satisfiable by NIGHT+UNDERWATER, where candidate
        # (DAY-only) is false -- candidate must NOT be considered broader.
        candidate = mk(selected={C.CATEGORY_TIME: {"DAY"}})
        specific = mk(selected={
            C.CATEGORY_TIME: {"DAY", "NIGHT"},
            C.CATEGORY_HEIGHT: {"UNDERWATER"},
        })
        self.assertFalse(priority.is_broader_than(candidate, specific))

    def test_true_implication_across_categories_still_works(self):
        # candidate=DAY only; specific=DAY AND UNDERWATER. Whenever specific
        # holds, DAY holds -- this really is a valid broader fallback.
        candidate = mk(selected={C.CATEGORY_TIME: {"DAY"}})
        specific = mk(selected={
            C.CATEGORY_TIME: {"DAY"},
            C.CATEGORY_HEIGHT: {"UNDERWATER"},
        })
        self.assertTrue(priority.is_broader_than(candidate, specific))

    def test_block_conditions_are_now_considered(self):
        # candidate needs no blocks; specific needs a block, AND time.
        # candidate is broader (implied) since specific implies DAY.
        candidate = mk(selected={C.CATEGORY_TIME: {"DAY"}})
        specific = mk(selected={C.CATEGORY_TIME: {"DAY"}})
        from models import BlockCondition
        specific.blocks = [BlockCondition(block_id="chest", min_count=1)]
        self.assertTrue(priority.is_broader_than(candidate, specific))


class TestScopesFindBlockers(unittest.TestCase):
    def test_structured_biome_field_detected(self):
        e = mk(biomes=[("ocean", False)])
        self.assertTrue(scopes._has_biome_condition(e))

    def test_verbatim_cross_category_biome_detected(self):
        # BIOME=ocean || UNDERWATER can't be represented structurally and
        # is kept verbatim -- must still be detected as a biome condition.
        e = mk(custom=["BIOME=ocean || UNDERWATER"])
        self.assertTrue(scopes._has_biome_condition(e))

    def test_verbatim_biometag_detected(self):
        e = mk(custom=["BIOMETAG=IS_HOT || DAY"])
        self.assertTrue(scopes._has_biome_condition(e))

    def test_no_biome_condition(self):
        e = mk(selected={C.CATEGORY_TIME: {"DAY"}})
        self.assertFalse(scopes._has_biome_condition(e))

    def test_global_with_verbatim_biome_is_skipped_as_blocker_candidate(self):
        # A GLOBAL entry whose only biome requirement is hidden in a
        # verbatim cross-category item must not be treated as reachable
        # "everywhere" -- it should be skipped by find_blockers, same as
        # one using the structured .biomes field.
        glob = mk(songs=["GlobalSong"], scope=C.SCOPE_GLOBAL,
                  custom=["BIOME=ocean || UNDERWATER"])
        blockers = scopes.find_blockers([glob], {"plains": "minecraft:overworld"})
        self.assertEqual(blockers, [])

    def test_time_agnostic_place_entry_is_swept_across_time_tokens(self):
        # A DAY+forest entry above a plain forest entry blocks the latter
        # during DAY. The old blocker check never set a time flag, so it
        # missed this valid blocking situation.
        day_forest = mk(songs=["DaySong"], selected={C.CATEGORY_TIME: {"DAY"}},
                        biomes=[("forest", False)])
        any_time_forest = mk(songs=["AnyTimeSong"], biomes=[("forest", False)])
        blockers = scopes.find_blockers(
            [day_forest, any_time_forest], {"forest": "minecraft:overworld"})
        self.assertEqual(len(blockers), 1)
        self.assertIn("forest at DAY", blockers[0].biomes)

    def test_entry_with_both_axes_named_is_not_swept(self):
        day_forest = mk(songs=["DaySong"], selected={C.CATEGORY_TIME: {"DAY"}},
                        biomes=[("forest", False)])
        self.assertFalse(scopes._is_reachability_candidate(day_forest))

    def test_time_only_entry_is_not_swept(self):
        day_only = mk(songs=["DaySong"], selected={C.CATEGORY_TIME: {"DAY"}})
        self.assertFalse(scopes._is_reachability_candidate(day_only))

class TestLogicalViewPositions(unittest.TestCase):
    def test_positions_follow_scope_sorted_order(self):
        # Constructed in [GLOBAL, NORMAL] order -- the saved/simulated
        # order is [NORMAL, GLOBAL], and positions must reflect THAT order.
        g = mk(songs=["G"], scope=C.SCOPE_GLOBAL)
        n = mk(songs=["N"], scope=C.SCOPE_NORMAL)
        view = entry_pools.logical_view([g, n])
        self.assertEqual(view.positions[n.id], 1)
        self.assertEqual(view.positions[g.id], 2)
        # And the logical entries list itself must be in that order too.
        self.assertEqual([e.songs[0] for e in view.entries], ["N", "G"])


class TestTopLevelValidation(unittest.TestCase):
    def _write(self, tmpdir, data_text):
        path = os.path.join(tmpdir, "ReactiveMusic.yaml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(data_text)
        return tmpdir

    def test_bad_name_type_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "name:\n  - totally\n  - not\n  - a string\n"
                             "entries: []\n")
            with self.assertRaises(yaml_io.SongpackFormatError):
                yaml_io.load_songpack(tmp)

    def test_bad_credits_type_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "credits: {a: b}\nentries: []\n")
            with self.assertRaises(yaml_io.SongpackFormatError):
                yaml_io.load_songpack(tmp)

    def test_valid_scalars_still_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                tmp,
                'name: "My Pack"\nauthor: "Someone"\n'
                'description: "desc"\ncredits: "thanks"\n'
                'musicSwitchSpeed: NORMAL\nmusicDelayLength: SHORT\n'
                'entries: []\n')
            pack = yaml_io.load_songpack(tmp)
            self.assertEqual(pack.name, "My Pack")
            self.assertEqual(pack.author, "Someone")
            self.assertEqual(pack.music_switch_speed, "NORMAL")

    def test_unquoted_number_name_is_coerced_not_rejected(self):
        # A bare scalar (not a list/mapping) is still coerced to text --
        # only list/mapping values are rejected.
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, "name: 2024\nentries: []\n")
            pack = yaml_io.load_songpack(tmp)
            self.assertEqual(pack.name, "2024")


if __name__ == "__main__":
    unittest.main(verbosity=2)
