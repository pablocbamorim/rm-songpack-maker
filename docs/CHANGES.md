# Entry logic fix — what changed

Drop these files over the project (only changed/new files are included; line
endings match the originals). Run `python -m unittest discover -s tests -v`.

## New
- `conditions.py`      one AND-of-ORs condition model + the single `soft_match` for BIOME=/DIM=
- `entry_pools.py`     "logical entries": what will actually be written/read (adjacent identical entries = one pool)
- `pack_validation.py` save-time warnings
- `tests/`             46 regression tests covering every fixture in the plan

## Behaviour changes worth knowing
- Loading a songpack now RAISES (with a list of problems) for wrongly-typed or malformed entries instead of coercing / loading an empty pack.
- Save merges only ADJACENT identical entries; the simulator reads the same merged shape. Auto-arrange keeps identical entries together so they still pool.
- Groups the widgets can't write back exactly (e.g. two OR groups in one category) are now kept verbatim in "Custom / unrecognised conditions" instead of being flattened. All views read them.
- BIOME=/DIM= use one soft-match rule everywhere (chart, case views, simulator, blocker check). `minecraft:forest` is specific, `forest` is a substring.
- Save now shows a "Check before saving" list; save verification compares meaning (conditions, pools, flags, order), not just song names.
- Credits is a multi-line box. Unknown per-entry / top-level YAML keys are preserved.

## Not done / needs your call
- Members of a multi-song pool other than `songs[0]` still have no list row of their own (label, search, banner and `case_grouping.cases_containing_song` cover them). Own rows need row ids that aren't entry ids.
- allowFallback default: spec says false, the 0.5.0 release note reads otherwise. Editor follows the spec; unconfirmed (note in mod_versions.py).
- soft_match assumes a namespace-less BIOME= value is tested against the biome *path* only.
- forceStart: chance is rolled when the entry becomes valid (the doc doesn't say when).
- YAML comments are not preserved. .ogg/.wav support left as is (documentation review only).
- GUI code was syntax/stub-tested only (no Tk in the build environment); please click through it once.
