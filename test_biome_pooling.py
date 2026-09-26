"""Tests for biome_pooling: overlapping biome-tag entries become per-biome pools.

No GUI needed. The simulator is the oracle: after the transform, what it plays
in a biome must include every song of the overlapping entries.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import biome_customization
import biome_pooling
import condition_logic
import constants as C
import entry_pools
import simulation
import yaml_io
from models import Entry, Songpack


def mk(songs, events, **flags):
    entry = Entry(songs=list(songs), **flags)
    condition_logic.parse_events(entry, events)
    return entry


def pool_real(entries, **kw):
    """Run against the bundled tag table, as the app would."""
    return biome_pooling.pool_overlapping_biomes(
        entries, biomes=list(biome_customization.load_app_dimensions()),
        tags_of=simulation.biome_tags, **kw)


def reachable(entries, biome, flags, manual=""):
    state = simulation.make_state(
        biome, None, flags, simulation.parse_manual(manual))
    plan = simulation.build_plan(entries, state)
    return [item.song for item in plan.items if item.reachable]


class TestOverlap(unittest.TestCase):
    def setUp(self):
        # One entry per song, as the editor keeps them; B and C are adjacent
        # and identical, i.e. one logical pool.
        self.entries = [
            mk(["A"], ["DAY", "BIOMETAG=IS_TEMPERATE_OVERWORLD"]),
            mk(["B"], ["DAY", "BIOMETAG=IS_PLAINS"]),
            mk(["C"], ["DAY", "BIOMETAG=IS_PLAINS"]),
        ]

    def test_overlapping_biome_plays_every_song(self):
        before = reachable(self.entries, "plains", {"DAY"})
        self.assertEqual(before, ["A"])           # the reported bug
        result = pool_real(self.entries)
        self.assertEqual(reachable(result.entries, "plains", {"DAY"}),
                         ["A", "B", "C"])
        self.assertEqual(reachable(result.entries, "sunflower_plains", {"DAY"}),
                         ["A", "B", "C"])

    def test_biome_in_one_tag_only_is_unchanged(self):
        result = pool_real(self.entries)
        self.assertEqual(reachable(result.entries, "forest", {"DAY"}), ["A"])

    def test_modded_biome_walks_through_both_tag_pools(self):
        manual = "BIOMETAG=IS_TEMPERATE_OVERWORLD\nBIOMETAG=IS_PLAINS"
        before = reachable(self.entries, "mymod:meadowy", {"DAY"}, manual)
        self.assertEqual(before, ["A"])
        result = pool_real(self.entries)
        self.assertEqual(
            reachable(result.entries, "mymod:meadowy", {"DAY"}, manual),
            ["A", "B", "C"])

    def test_pool_count_is_distinct_contributor_sets_not_permutations(self):
        result = pool_real(self.entries)
        self.assertEqual(result.report.residuals, 2)
        self.assertEqual(len(result.report.groups), 1)
        biome_pools = [e for e in result.entries
                       if e.biomes and all(not b.is_tag for b in e.biomes)]
        self.assertGreaterEqual(len(biome_pools), 2)
        self.assertTrue(all(b.value.startswith("minecraft:")
                            for e in biome_pools for b in e.biomes))

    def test_residuals_come_after_their_pools_and_allow_fallback(self):
        result = pool_real(self.entries)
        kinds = ["pool" if e.biomes and not e.biomes[0].is_tag else "tag"
                 for e in result.entries]
        self.assertLess(max(i for i, k in enumerate(kinds) if k == "pool"),
                        min(i for i, k in enumerate(kinds) if k == "tag"))
        self.assertTrue(all(e.allow_fallback for e in result.entries
                            if e.biomes and e.biomes[0].is_tag))

    def test_residual_fallback_can_be_disabled(self):
        result = pool_real(self.entries, residual_fallback=False)
        self.assertFalse(any(e.allow_fallback for e in result.entries
                             if e.biomes and e.biomes[0].is_tag))

    def test_input_entries_are_not_modified(self):
        pool_real(self.entries)
        self.assertEqual([e.songs for e in self.entries], [["A"], ["B"], ["C"]])
        self.assertFalse(any(e.allow_fallback for e in self.entries))


class TestLeftAlone(unittest.TestCase):
    def test_different_situations_are_not_merged(self):
        entries = [mk(["A"], ["DAY", "BIOMETAG=IS_TEMPERATE_OVERWORLD"]),
                   mk(["B"], ["DAY", "RAIN", "BIOMETAG=IS_PLAINS"])]
        result = pool_real(entries)
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(result.report.pools, 0)

    def test_disjoint_tags_produce_nothing(self):
        entries = [mk(["A"], ["DAY", "BIOMETAG=IS_DESERT"]),
                   mk(["B"], ["DAY", "BIOMETAG=IS_SWAMP"])]
        result = pool_real(entries)
        self.assertEqual([e.songs for e in result.entries], [["A"], ["B"]])

    def test_force_flags_are_skipped_and_reported(self):
        entries = [
            mk(["A"], ["BIOMETAG=IS_TEMPERATE_OVERWORLD"],
               force_stop_on_changed=True),
            mk(["B"], ["BIOMETAG=IS_PLAINS"], force_stop_on_changed=True)]
        result = pool_real(entries)
        self.assertEqual(len(result.entries), 2)
        self.assertEqual(len(result.report.skipped), 1)

    def test_mixed_place_and_situation_clause_is_left_alone(self):
        entries = [mk(["A"], ["BIOME=plains || UNDERWATER"]),
                   mk(["B"], ["BIOMETAG=IS_PLAINS"])]
        result = pool_real(entries)
        self.assertEqual(result.report.pools, 0)

    def test_global_entries_are_not_touched(self):
        entries = [mk(["G"], ["DAY"], scope=C.SCOPE_GLOBAL),
                   mk(["A"], ["DAY", "BIOMETAG=IS_PLAINS"])]
        result = pool_real(entries)
        self.assertEqual(result.report.pools, 0)


class TestSyntheticTags(unittest.TestCase):
    BIOMES = ["plains", "savanna", "savanna_plateau"]
    TAGS = {"plains": {"A", "B"}, "savanna": {"A", "B"},
            "savanna_plateau": {"B"}}

    def run_pool(self, entries):
        return biome_pooling.pool_overlapping_biomes(
            entries, biomes=self.BIOMES,
            tags_of=lambda b: self.TAGS.get(b, set()))

    def test_prefix_biome_pool_is_moved_ahead(self):
        # minecraft:savanna is a substring of minecraft:savanna_plateau, so the
        # plateau's own pool must come first or the shared pool would steal it.
        entries = [mk(["x"], ["BIOMETAG=A"]), mk(["y"], ["BIOMETAG=B"])]
        result = self.run_pool(entries)
        pools = [e for e in result.entries
                 if e.biomes and not e.biomes[0].is_tag]
        self.assertEqual(pools[0].songs, ["y"])
        self.assertEqual([b.value for b in pools[0].biomes],
                         ["minecraft:savanna_plateau"])
        self.assertEqual(pools[1].songs, ["x", "y"])
        self.assertEqual(result.report.warnings, [])

    def test_uncovered_prefix_biome_is_reported(self):
        tags = {"plains": {"A", "B"}, "savanna": {"A", "B"}}
        result = biome_pooling.pool_overlapping_biomes(
            [mk(["x"], ["BIOMETAG=A"]), mk(["y"], ["BIOMETAG=B"])],
            biomes=self.BIOMES, tags_of=lambda b: tags.get(b, set()))
        self.assertEqual(len(result.report.warnings), 1)
        self.assertIn("savanna_plateau", result.report.warnings[0])

    def test_pool_events_are_one_or_item(self):
        result = self.run_pool([mk(["x"], ["DAY", "BIOMETAG=A"]),
                                mk(["y"], ["DAY", "BIOMETAG=B"])])
        shared = next(e for e in result.entries if e.songs == ["x", "y"])
        events = condition_logic.build_events(shared)
        self.assertEqual(events[0], "DAY")
        self.assertEqual(events[1],
                         "BIOME=minecraft:plains || BIOME=minecraft:savanna")


def pooler(entries):
    return pool_real(entries).entries


def overlapping_pack():
    return Songpack(entries=[
        mk(["A"], ["DAY", "BIOMETAG=IS_TEMPERATE_OVERWORLD"]),
        mk(["B"], ["DAY", "BIOMETAG=IS_PLAINS"]),
        mk(["C"], ["DAY", "BIOMETAG=IS_PLAINS"]),
        mk(["Z"], ["NIGHT"], extra_fields={"alwaysPlay": True}),
    ])


def read(folder, name="ReactiveMusic.yaml"):
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return f.read()


class TestSaveLoad(unittest.TestCase):
    """The compiled YAML is for the mod; the editor must get ITS entries back."""

    def test_yaml_is_compiled_and_editor_gets_authored_entries_back(self):
        pack = overlapping_pack()
        with tempfile.TemporaryDirectory() as tmp:
            yaml_io.save_songpack(pack, tmp, pooling=pooler)
            self.assertIn("BIOME=minecraft:plains", read(tmp))
            self.assertTrue(os.path.isfile(os.path.join(tmp, yaml_io.SOURCE_FILENAME)))
            back = yaml_io.load_songpack(tmp)
            self.assertEqual(entry_pools.semantic_snapshot(back.entries),
                             entry_pools.semantic_snapshot(pack.entries))
            self.assertTrue(any(b.is_tag for e in back.entries for b in e.biomes))
            self.assertEqual(back.entries[-1].extra_fields, {"alwaysPlay": True})

    def test_verification_view_of_the_compiled_file(self):
        # What ui_enhancements.save_config compares.
        pack = overlapping_pack()
        with tempfile.TemporaryDirectory() as tmp:
            yaml_io.save_songpack(pack, tmp, pooling=pooler)
            written = yaml_io.load_songpack(tmp, use_source=False)
            self.assertEqual(
                entry_pools.semantic_snapshot(pooler(pack.entries)),
                entry_pools.semantic_snapshot(written.entries))
            self.assertEqual(
                [s for e in written.entries for s in e.songs],
                yaml_io.expected_songs_after_save(pack, pooler))
            self.assertFalse(any(b.is_tag is False for e in pack.entries
                                 for b in e.biomes))    # editor entries untouched

    def test_hand_edited_yaml_wins_over_a_stale_sidecar(self):
        pack = overlapping_pack()
        with tempfile.TemporaryDirectory() as tmp:
            yaml_io.save_songpack(pack, tmp, pooling=pooler)
            text = read(tmp).replace('"Z"', '"Y"')
            with open(os.path.join(tmp, "ReactiveMusic.yaml"), "w",
                      encoding="utf-8") as f:
                f.write(text)
            back = yaml_io.load_songpack(tmp)
            songs = [s for e in back.entries for s in e.songs]
            self.assertIn("Y", songs)
            self.assertNotIn("Z", songs)
            self.assertTrue(any(not b.is_tag for e in back.entries
                                for b in e.biomes))     # compiled form was read

    def test_no_overlap_writes_no_sidecar_and_removes_a_stale_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            sidecar = os.path.join(tmp, yaml_io.SOURCE_FILENAME)
            yaml_io.save_songpack(overlapping_pack(), tmp, pooling=pooler)
            self.assertTrue(os.path.isfile(sidecar))
            yaml_io.save_songpack(overlapping_pack(), tmp)           # pooling off
            self.assertFalse(os.path.exists(sidecar))
            self.assertNotIn("BIOME=minecraft", read(tmp))
            plain = Songpack(entries=[mk(["A"], ["BIOMETAG=IS_DESERT"]),
                                      mk(["B"], ["BIOMETAG=IS_SWAMP"])])
            yaml_io.save_songpack(plain, tmp, pooling=pooler)
            self.assertFalse(os.path.exists(sidecar))

    def test_pooling_off_is_byte_identical_to_before(self):
        pack = overlapping_pack()
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            yaml_io.save_songpack(pack, a)
            yaml_io.save_songpack(pack, b, pooling=None)
            self.assertEqual(read(a), read(b))

    def test_global_entry_keeps_its_scope_through_a_pooled_save(self):
        pack = overlapping_pack()
        pack.entries.append(mk(["G"], ["FISHING"], scope=C.SCOPE_GLOBAL))
        with tempfile.TemporaryDirectory() as tmp:
            yaml_io.save_songpack(pack, tmp, pooling=pooler)
            for use_source in (True, False):
                back = yaml_io.load_songpack(tmp, use_source=use_source)
                glob = [e for e in back.entries if e.songs == ["G"]]
                self.assertEqual([e.scope for e in glob], [C.SCOPE_GLOBAL])


if __name__ == "__main__":
    unittest.main(verbosity=2)
