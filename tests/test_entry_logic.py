"""Regression tests for SONGPACK_ENTRY_LOGIC_FIX_PLAN.md.

Run from the project folder:   python -m unittest discover -s tests -v
No GUI libraries are needed: everything tested here is pure logic.
"""

import os
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import case_grouping
import condition_logic
import conditions
import constants as C
import entry_pools
import mod_versions
import pack_validation
import priority
import scopes
import simulation
import yaml_io
from models import BiomeCondition, Entry, Songpack


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def write_pack(text: str) -> str:
    folder = tempfile.mkdtemp()
    with open(os.path.join(folder, "ReactiveMusic.yaml"), "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(text))
    return folder


def load_text(text: str) -> Songpack:
    return yaml_io.load_songpack(write_pack(text))


def entry_of(events, songs=("Example",), **flags) -> Entry:
    entry = Entry(songs=list(songs))
    condition_logic.parse_events(entry, list(events))
    for key, value in flags.items():
        setattr(entry, key, value)
    return entry


def roundtrip(pack: Songpack) -> Songpack:
    folder = tempfile.mkdtemp()
    yaml_io.save_songpack(pack, folder)
    return yaml_io.load_songpack(folder)


def plan_for(entries, biome, flags=(), dim="minecraft:overworld"):
    state = simulation.make_state(biome, dim, set(flags))
    view = entry_pools.logical_view(entries)
    return simulation.build_plan(view.entries, state, view.positions)


def songs_playing(entries, biome, flags=()):
    return [i.song for i in plan_for(entries, biome, flags).items if i.reachable]


class EventRoundTrip(unittest.TestCase):
    """P0: parse -> build must never change the boolean meaning."""

    CASES = {
        "or_group_plus_tag": ["BIOME=forest || BIOME=plains", "BIOMETAG=IS_HOT"],
        "dim_or_plus_dim": ["DIM=NETHER || DIM=END", "DIM=OVERWORLD"],
        "block_or_plus_block": ["BLOCK=stone,10 || BLOCK=dirt,10", "BLOCK=diamond_ore,2"],
        "two_or_groups_one_category": ["BIOME=forest || BIOME=plains",
                                      "BIOME=cherry || BIOME=ocean"],
        "single_token_groups_and": ["BIOME=forest", "BIOME=plains"],
        "single_group_single_token": ["BIOME=forest"],
        "fixed_or_group": ["DAY || SUNSET"],
        "two_fixed_or_groups": ["DAY || SUNSET", "NIGHT || SUNRISE"],
        "fixed_and_dynamic": ["DAY || SUNSET", "BIOME=forest || BIOME=plains", "DIM=NETHER"],
        "custom_raw": ["FISHING", "SOMETHING_NEW", "BIOME=ocean || UNDERWATER"],
        "mixed_singleton_and_group": ["BIOME=a || BIOME=b", "BIOME=c"],
        "lowercase_prefix_kept_verbatim": ["biome=forest", "day"],
        "cross_category_or": ["BIOME=ocean || UNDERWATER"],
        "three_way_cross_category": ["BIOME=ocean || BIOME=forest || UNDERWATER", "DAY"],
    }

    def test_parse_build_is_logically_identical(self):
        for name, events in self.CASES.items():
            with self.subTest(name):
                entry = entry_of(events)
                self.assertEqual(
                    conditions.canonical(events),
                    conditions.canonical(condition_logic.build_events(entry)))

    def test_save_load_save_is_stable(self):
        for name, events in self.CASES.items():
            with self.subTest(name):
                pack = Songpack(entries=[entry_of(events)])
                once = roundtrip(pack)
                twice = roundtrip(once)
                want = conditions.canonical(events)
                self.assertEqual(want, condition_logic.canonical_events(once.entries[0]))
                self.assertEqual(want, condition_logic.canonical_events(twice.entries[0]))
                self.assertEqual(
                    yaml_io.songpack_to_dict(once), yaml_io.songpack_to_dict(twice))

    def test_the_documented_flattening_bug(self):
        entry = entry_of(["BIOME=forest || BIOME=plains", "BIOMETAG=IS_HOT"])
        built = condition_logic.build_events(entry)
        # (forest OR plains) AND hot, never forest AND plains AND hot
        self.assertIn("BIOME=forest || BIOME=plains", built)
        self.assertIn("BIOMETAG=IS_HOT", built)
        self.assertEqual(len(built), 2)

    def test_simple_cases_still_use_the_structured_fields(self):
        entry = entry_of(["DAY || SUNSET", "BIOME=forest || BIOME=plains", "DIM=NETHER"])
        self.assertEqual(entry.selected[C.CATEGORY_TIME], {"DAY", "SUNSET"})
        self.assertEqual([b.value for b in entry.biomes], ["forest", "plains"])
        self.assertEqual(entry.biome_combine, C.COMBINE_OR)
        self.assertEqual(entry.custom_raw_conditions, [])
        entry = entry_of(["BIOME=forest", "BIOME=plains"])
        self.assertEqual(entry.biome_combine, C.COMBINE_AND)
        self.assertEqual(entry.custom_raw_conditions, [])


class CrossCategoryOr(unittest.TestCase):
    """P1: the template's "BIOME=ocean || UNDERWATER" is understood everywhere."""

    def setUp(self):
        self.entry = entry_of(["BIOME=ocean || UNDERWATER"], songs=["Eventide"])
        self.pack = Songpack(entries=[self.entry])

    def test_kept_verbatim_through_load_save(self):
        out = roundtrip(self.pack)
        self.assertEqual(yaml_io.songpack_to_dict(self.pack)["entries"][0]["events"],
                         ["BIOME=ocean || UNDERWATER"])
        self.assertEqual(out.entries[0].custom_raw_conditions,
                         ["BIOME=ocean || UNDERWATER"])

    def test_simulation(self):
        self.assertEqual(songs_playing([self.entry], "deep_ocean"), ["Eventide"])
        self.assertEqual(songs_playing([self.entry], "desert", ["UNDERWATER"]), ["Eventide"])
        self.assertEqual(songs_playing([self.entry], "desert"), [])

    def test_biome_views_see_the_biome_part(self):
        self.assertEqual(case_grouping.biome_cases(self.pack, "ocean"), [self.entry])
        self.assertEqual(case_grouping.biome_cases(self.pack, "deep_ocean"), [self.entry])
        self.assertEqual(case_grouping.biome_cases(self.pack, "desert"), [])

    def test_priority_score_reflects_the_content(self):
        score = priority.score_entry(self.entry)
        self.assertGreater(score, 0)
        # An OR is easier to satisfy than the strictest single member...
        self.assertLess(score, priority.score_entry(entry_of(["BIOME=ocean"])))
        # ...and a flat "1.5 per raw string" is gone: content matters.
        self.assertNotEqual(score, priority.score_entry(entry_of(["MYSTERY || OTHER"])) )

    def test_version_gating_sees_tokens_inside(self):
        gated = entry_of(["BIOMETAG=IS_HOT || UNDERWATER"])
        self.assertEqual(mod_versions.unsupported_in_entry(gated, "0.3.0"), ["BIOMETAG"])
        self.assertEqual(mod_versions.unsupported_in_entry(gated, "0.4.0"), [])
        village = entry_of(["VILLAGE || DAY"])
        self.assertEqual(mod_versions.unsupported_in_entry(village, "0.4.0"), ["VILLAGE"])

    def test_every_gated_feature_structured_and_embedded(self):
        structured = {
            "BIOMETAG": entry_of(["BIOMETAG=IS_HOT"]),
            "VILLAGE": entry_of(["VILLAGE"]),
            "BOSS": entry_of(["BOSS"]),
            "NEARBY_MOBS": entry_of(["NEARBY_MOBS"]),
            "BLOCK": entry_of(["BLOCK=stone,5"]),
            "allow_fallback": entry_of(["DAY"], allow_fallback=True),
        }
        embedded = {
            "BIOMETAG": entry_of(["BIOMETAG=IS_HOT || UNDERWATER"]),
            "VILLAGE": entry_of(["VILLAGE || UNDERWATER"]),
            "BOSS": entry_of(["BOSS || UNDERWATER"]),
            "NEARBY_MOBS": entry_of(["NEARBY_MOBS || UNDERWATER"]),
            "BLOCK": entry_of(["BLOCK=stone,5 || UNDERWATER"]),
        }
        for feature, entry in {**structured, **{f"{k}(or)": v for k, v in embedded.items()}}.items():
            with self.subTest(feature):
                want = feature.split("(")[0]
                self.assertEqual(mod_versions.unsupported_in_entry(entry, "0.1.0"), [want])

    def test_no_substring_false_positives(self):
        entry = entry_of(["BIOME=village_of_boss || DAY"])
        self.assertEqual(mod_versions.unsupported_in_entry(entry, "0.1.0"), [])


class MergeKeepsPriority(unittest.TestCase):
    """P0: save-time merging must not change what the mod plays."""

    def packs(self):
        a = entry_of(["BIOME=x"], ["s1"])
        b = entry_of(["DAY"], ["s2"])
        c = entry_of(["BIOME=x"], ["s3"])
        return Songpack(entries=[a, b, c]), (a, b, c)

    def test_non_adjacent_duplicates_are_not_merged(self):
        pack, _ = self.packs()
        saved = yaml_io.songpack_to_dict(pack)["entries"]
        self.assertEqual([e["songs"] for e in saved], [["s1"], ["s2"], ["s3"]])

    def test_simulator_matches_the_saved_file(self):
        pack, _ = self.packs()
        before = songs_playing(pack.entries, "x", ["DAY"])
        after = songs_playing(roundtrip(pack).entries, "x", ["DAY"])
        self.assertEqual(before, after)
        self.assertEqual(before, ["s1"])   # s1 loops (no fallback); s2/s3 unreachable

    def test_priority_identical_after_reload(self):
        pack, _ = self.packs()
        self.assertEqual(entry_pools.semantic_snapshot(pack.entries),
                         entry_pools.semantic_snapshot(roundtrip(pack).entries))

    def test_adjacent_identical_entries_form_one_pool_everywhere(self):
        a = entry_of(["DAY"], ["s1"])
        b = entry_of(["DAY"], ["s2"])
        pack = Songpack(entries=[a, b])
        saved = yaml_io.songpack_to_dict(pack)["entries"]
        self.assertEqual(saved[0]["songs"], ["s1", "s2"])
        # the simulator sees the pool, not "s2 unreachable behind a looping s1"
        self.assertEqual(songs_playing(pack.entries, "plains", ["DAY"]), ["s1", "s2"])
        self.assertEqual(songs_playing(roundtrip(pack).entries, "plains", ["DAY"]),
                         ["s1", "s2"])

    def test_plan_numbers_follow_the_editor_list(self):
        pack, (a, b, c) = self.packs()
        plan = plan_for(pack.entries, "x", ["DAY"])
        self.assertEqual([i.entry_index for i in plan.items], [1, 2, 3])

    def test_entries_that_differ_by_any_flag_never_merge(self):
        flags = ["allow_fallback", "force_stop_on_changed", "force_stop_on_valid",
                 "force_stop_on_invalid", "force_start_on_valid"]
        for flag in flags:
            with self.subTest(flag):
                a = entry_of(["DAY"], ["s1"])
                b = entry_of(["DAY"], ["s2"], **{flag: True})
                saved = yaml_io.songpack_to_dict(Songpack(entries=[a, b]))["entries"]
                self.assertEqual(len(saved), 2)
        a = entry_of(["DAY"], ["s1"])
        b = entry_of(["DAY"], ["s2"], force_chance=0.5)
        self.assertEqual(len(yaml_io.songpack_to_dict(Songpack(entries=[a, b]))["entries"]), 2)

    def test_different_extra_fields_never_merge(self):
        a = entry_of(["DAY"], ["s1"])
        b = entry_of(["DAY"], ["s2"])
        b.extra_fields = {"alwaysPlay": True}
        self.assertEqual(len(yaml_io.songpack_to_dict(Songpack(entries=[a, b]))["entries"]), 2)

    def test_auto_arrange_keeps_identical_entries_together(self):
        d1, n, d2 = entry_of(["DAY"], ["d1"]), entry_of(["NIGHT"], ["n"]), entry_of(["DAY"], ["d2"])
        ordered = priority.auto_priority_order([d1, n, d2])
        self.assertEqual([e.songs[0] for e in ordered], ["d1", "d2", "n"])

    def test_scope_order_is_part_of_the_logical_view(self):
        g = entry_of(["DAY"], ["g"], scope=C.SCOPE_GLOBAL)
        n = entry_of(["NIGHT"], ["n"])
        view = entry_pools.logical_view([g, n])
        self.assertEqual([e.songs[0] for e in view.entries], ["n", "g"])


class UnknownFields(unittest.TestCase):
    def test_entry_and_top_level_extras_survive(self):
        pack = load_text('''
            name: "P"
            futureSetting: {a: 1, b: [x, y]}
            entries:
              - events: ["DAY"]
                alwaysPlay: true
                songs: ["Example"]
        ''')
        self.assertEqual(pack.entries[0].extra_fields, {"alwaysPlay": True})
        again = roundtrip(roundtrip(pack))
        self.assertEqual(again.entries[0].extra_fields, {"alwaysPlay": True})
        self.assertEqual(again.extra_top_level, {"futureSetting": {"a": 1, "b": ["x", "y"]}})
        saved = yaml_io.songpack_to_dict(again)
        self.assertTrue(saved["entries"][0]["alwaysPlay"])

    def test_multiline_credits_survive(self):
        pack = load_text('''
            name: "P"
            credits: "one\\ntwo\\n  three"
            entries: []
        ''')
        self.assertEqual(pack.credits, "one\ntwo\n  three")
        self.assertEqual(roundtrip(pack).credits, "one\ntwo\n  three")


class LoadValidation(unittest.TestCase):
    def test_invalid_types_are_reported_not_coerced(self):
        with self.assertRaises(yaml_io.SongpackFormatError) as ctx:
            load_text('''
                entries:
                  - events: "DAY"
                    allowFallback: "false"
                    forceChance: "not-a-number"
                    songs: "Example"
            ''')
        message = str(ctx.exception)
        for needle in ("'events' must be a list", "'allowFallback' must be true or false",
                       "'forceChance' must be a number", "'songs' must be a list"):
            self.assertIn(needle, message)

    def test_one_bad_item_no_longer_yields_an_empty_pack(self):
        with self.assertRaises(yaml_io.SongpackFormatError) as ctx:
            load_text('''
                entries:
                  - events: ["DAY"]
                    songs: ["A"]
                  - just-a-string
                  - events: ["NIGHT"]
                    songs: ["B"]
            ''')
        self.assertIn("Entry 2", str(ctx.exception))

    def test_non_string_songs_are_rejected(self):
        with self.assertRaises(yaml_io.SongpackFormatError):
            load_text('''
                entries:
                  - events: ["DAY"]
                    songs: [123]
            ''')

    def test_genuinely_empty_entries_list_is_fine(self):
        self.assertEqual(load_text("name: x\nentries: []\n").entries, [])

    def test_bool_flags_true_false_round_trip(self):
        pack = load_text('''
            entries:
              - events: ["DAY"]
                allowFallback: true
                forceChance: 0.5
                songs: ["A"]
        ''')
        self.assertTrue(pack.entries[0].allow_fallback)
        self.assertEqual(pack.entries[0].force_chance, 0.5)


class SoftBiomeMatching(unittest.TestCase):
    FOREST_LIKE = {"forest", "dark_forest", "birch_forest", "flower_forest"}
    IDS = ["forest", "dark_forest", "birch_forest", "flower_forest", "ocean",
           "deep_ocean", "cold_ocean", "plains", "snowy_plains",
           "sunflower_plains", "cherry_grove"]

    def matches(self, want):
        return {b for b in self.IDS if conditions.soft_match(want, b)}

    def test_documented_soft_search(self):
        self.assertEqual(self.matches("forest"), self.FOREST_LIKE)
        self.assertEqual(self.matches("ocean"), {"ocean", "deep_ocean", "cold_ocean"})
        self.assertEqual(self.matches("plains"), {"plains", "snowy_plains", "sunflower_plains"})
        self.assertEqual(self.matches("cherry"), {"cherry_grove"})

    def test_namespaced_value_is_specific_not_broad(self):
        self.assertEqual(self.matches("minecraft:forest"), {"forest"})

    def test_simulator_uses_the_same_rule(self):
        entry = entry_of(["BIOME=forest"], ["Forest"])
        for biome in self.IDS:
            with self.subTest(biome):
                self.assertEqual(bool(songs_playing([entry], biome)),
                                 biome in self.FOREST_LIKE)
        specific = entry_of(["BIOME=minecraft:forest"], ["Only"])
        self.assertEqual(songs_playing([specific], "forest"), ["Only"])
        self.assertEqual(songs_playing([specific], "dark_forest"), [])

    def test_biome_case_grouping_uses_the_same_rule(self):
        entry = entry_of(["BIOME=forest"])
        pack = Songpack(entries=[entry])
        self.assertEqual(case_grouping.biome_cases(pack, "dark_forest"), [entry])
        self.assertEqual(case_grouping.biome_case_via_soft(entry, "dark_forest"), "forest")
        self.assertIsNone(case_grouping.biome_case_via_soft(entry, "forest"))
        self.assertEqual(case_grouping.biome_cases(pack, "desert"), [])

    def test_dimension_soft_match(self):
        entry = entry_of(["DIM=NETHER"], ["N"])
        state = simulation.make_state("nether_wastes", "minecraft:the_nether", set())
        plan = simulation.build_plan([entry], state)
        self.assertTrue(plan.items[0].reachable)


class SongPools(unittest.TestCase):
    def test_every_song_of_a_pool_is_discoverable(self):
        pool = entry_of(["DAY"], ["Freedom", "WorldUnbound"])
        other = entry_of(["NIGHT"], ["Moon"])
        entries = [pool, other]
        self.assertEqual(case_grouping.cases_containing_song(entries, "WorldUnbound"), [pool])
        self.assertEqual(case_grouping.pool_songs([pool]), ["Freedom", "WorldUnbound"])
        self.assertEqual(list(case_grouping.secondary_songs(entries)), ["WorldUnbound"])

    def test_pool_round_trips_in_order(self):
        pack = load_text('''
            entries:
              - events: ["DAY"]
                songs: ["Freedom", "WorldUnbound"]
        ''')
        self.assertEqual(roundtrip(pack).entries[0].songs, ["Freedom", "WorldUnbound"])


class Transitions(unittest.TestCase):
    def test_force_stop_on_valid_and_invalid(self):
        e = entry_of(["BOSS"], force_stop_on_valid=True)
        t = simulation.evaluate_transition(set(), {e.id}, [e], rand=lambda: 0.0)
        self.assertIs(t.stop_entry, e)
        t = simulation.evaluate_transition({e.id}, set(), [e], rand=lambda: 0.0)
        self.assertIsNone(t.stop_entry)          # only "valid" was requested
        e.force_stop_on_invalid = True
        t = simulation.evaluate_transition({e.id}, set(), [e], rand=lambda: 0.0)
        self.assertIs(t.stop_entry, e)

    def test_force_chance_applies_to_stop_and_start(self):
        e = entry_of(["BOSS"], force_stop_on_changed=True,
                     force_start_on_valid=True, force_chance=0.5)
        hit = simulation.evaluate_transition(set(), {e.id}, [e], rand=lambda: 0.1)
        self.assertIs(hit.stop_entry, e)
        self.assertEqual(hit.armed_start, [e.id])
        miss = simulation.evaluate_transition(set(), {e.id}, [e], rand=lambda: 0.9)
        self.assertIsNone(miss.stop_entry)
        self.assertEqual(miss.armed_start, [])

    def test_force_start_arms_only_when_it_becomes_valid(self):
        e = entry_of(["BOSS"], force_start_on_valid=True)
        stay = simulation.evaluate_transition({e.id}, {e.id}, [e], rand=lambda: 0.0)
        self.assertEqual(stay.armed_start, [])
        went = simulation.evaluate_transition({e.id}, set(), [e], rand=lambda: 0.0)
        self.assertEqual(went.armed_start, [])
        came = simulation.evaluate_transition(set(), {e.id}, [e], rand=lambda: 0.0)
        self.assertEqual(came.armed_start, [e.id])

    def test_armed_start_fires_at_stop_only_while_still_valid(self):
        boss = entry_of(["BOSS"], ["BossSong"], force_start_on_valid=True)
        day = entry_of(["DAY"], ["DaySong"])
        entries = [boss, day]
        self.assertIs(simulation.choose_force_start([boss.id], {boss.id, day.id}, entries), boss)
        self.assertIsNone(simulation.choose_force_start([boss.id], {day.id}, entries))
        self.assertIsNone(simulation.choose_force_start([], {boss.id}, entries))

    def test_force_start_plays_the_entry_even_if_the_chain_skips_it(self):
        a = entry_of(["DAY"], ["A"])                        # no fallback: blocks below
        boss = entry_of(["BOSS"], ["BossSong"], force_start_on_valid=True)
        plan = plan_for([a, boss], "plains", ["DAY", "BOSS"])
        self.assertFalse(plan.items[plan.first_item_of(boss.id)].reachable)
        self.assertEqual(plan.items[plan.first_item_of(boss.id)].song, "BossSong")


class SaveValidation(unittest.TestCase):
    def messages(self, entries):
        return [str(i) for i in pack_validation.validate_pack(Songpack(entries=entries))]

    def test_empty_songs_and_conditions_are_reported(self):
        msgs = self.messages([Entry(), entry_of(["DAY"], ["ok"])])
        self.assertTrue(any("no songs" in m for m in msgs))
        self.assertTrue(any("no conditions" in m for m in msgs))
        self.assertFalse(any("Entry 2" in m for m in msgs))

    def test_bad_force_chance(self):
        e = entry_of(["DAY"])
        e.force_chance = 1.5
        self.assertTrue(any("forceChance" in m for m in self.messages([e])))

    def test_unreachable_entry_is_reported(self):
        broad = entry_of(["DAY"], ["broad"])
        narrow = entry_of(["DAY", "BIOME=forest"], ["narrow"])
        msgs = self.messages([broad, narrow])
        self.assertTrue(any("can never play" in m and "Entry 2" in m for m in msgs))
        broad.allow_fallback = True
        self.assertFalse(any("can never play" in m for m in self.messages([broad, narrow])))

    def test_soft_biome_implication(self):
        broad = entry_of(["BIOME=forest"], ["broad"])
        narrow = entry_of(["BIOME=dark_forest"], ["narrow"])
        self.assertTrue(any("can never play" in m for m in self.messages([broad, narrow])))

    def test_documented_force_flag_combinations_are_not_invented_errors(self):
        e = entry_of(["DAY"], force_stop_on_changed=True, force_stop_on_valid=True,
                     force_stop_on_invalid=True)
        self.assertEqual(self.messages([e]), [])


class GlobalScopeWithPools(unittest.TestCase):
    def test_blocker_that_is_a_pool_gets_fallback_on_every_member(self):
        b1 = entry_of(["BIOME=forest"], ["f1"])
        b2 = entry_of(["BIOME=forest"], ["f2"])
        g = entry_of(["DAY"], ["glob"], scope=C.SCOPE_GLOBAL)
        entries = [b1, b2, g]
        biomes = {"forest": "minecraft:overworld"}
        # DAY is only true in this scenario if the scenario says so
        blockers = scopes.find_blockers(entries, biomes)
        self.assertEqual(len(blockers), 1)
        scopes.enable_fallback_on_blockers(entries, biomes)
        self.assertTrue(b1.allow_fallback and b2.allow_fallback)
        self.assertEqual(scopes.find_blockers(entries, biomes), [])


class ExprImplication(unittest.TestCase):
    def test_soundness_examples(self):
        p = conditions.parse_expression
        self.assertTrue(conditions.expression_implies(
            p(["DAY", "BIOME=forest"]), p(["DAY"])))
        self.assertFalse(conditions.expression_implies(
            p(["DAY"]), p(["DAY", "BIOME=forest"])))
        self.assertTrue(conditions.expression_implies(
            p(["DAY"]), p(["DAY || NIGHT"])))
        self.assertFalse(conditions.expression_implies(
            p(["DAY || NIGHT"]), p(["DAY"])))
        self.assertTrue(conditions.expression_implies(
            p(["BLOCK=stone,10"]), p(["BLOCK=stone,5"])))
        self.assertFalse(conditions.expression_implies(
            p(["BLOCK=stone,5"]), p(["BLOCK=stone,10"])))


if __name__ == "__main__":
    unittest.main()
