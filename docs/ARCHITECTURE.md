# Architecture Guide — ReactiveMusic Songpack Editor

This file exists so a new contributor can orient itself **before**
reading source code: what the program does, how the pieces fit together, and
—most importantly—**which files to open for a given task**, so you don't have
to load the whole repo into context.

## What this program is

A Tkinter/CustomTkinter desktop GUI (`SoundpackMaker`) that lets a user build
a **songpack** for the Minecraft mod *ReactiveMusic* without hand-writing
`ReactiveMusic.yaml`. A songpack = a YAML file (`events` → `songs` rules) +
an `music/` folder of audio files. The mod's own format/rules are documented
in `MAKING_SONGPACKS.md` and `ReactiveMusic.yaml-template.yaml` (read these
first if you need to understand *what* a songpack is, independent of this
editor's code).

The editor is "vibe-coded" (per README) — extensively AI-assisted — and the
module docstrings are unusually thorough; **read a module's own docstring
before its code**, it usually explains the "why" you'd otherwise have to
infer.

## Mental model: one list, many views

Everything revolves around a single mutable object graph:

```
App.pack_data : Songpack        (models.py)
  └─ entries: List[Entry]       (models.py)
```

`Entry` = one songpack rule (its `events` conditions + its `songs` pool +
advanced flags). Every tab/window in the app is just a different *view* or
*grouping* over `app.pack.entries` — nothing is duplicated or needs manual
syncing:

- **Music & Conditions tab** groups entries by primary song ("cases" of a
  song).
- **Biome Simulator → select a biome** groups entries by `BIOME=`
  condition ("cases" of a biome); on the **Biome tags** map it groups them by
  `BIOMETAG=` condition ("cases" of a tag). A tag case is a plain entry — songs
  added to a tag are *not* copied onto its biomes; the entry just matches all of
  them (the simulator resolves tags through the bundled membership table).
- **Priority Order tab** shows `entries` in raw list order (= play priority:
  first match wins, per the mod's own rules).

Both groupings are *computed on the fly* from entry data (see
`case_grouping.py`) — there's no separate "case id". Edit from either view
and the other one is automatically consistent on next redraw.

## Startup chain

```
main.py
  → app.App()            (app.py wraps app_core.App, fixes CTkTabview packing)
  → app_core.App.__init__()        (loads editor preferences and builds tabs)
  → best-effort last-songpack restore (from app_settings.py)
  → ui_enhancements.install(app)   (adds preview buttons, save verification,
                                     filename sanitization — monkeypatches
                                     a few App methods)
  → version_ui.install(app)        (adds a version label to the Help menu)
  → app.mainloop()
```

On a successful restore, the last opened songpack folder is loaded and the
window selects **Biome Simulator**. A missing or invalid restore target is
cleared and startup continues with a fresh songpack.

`app.py` and `app_core.py` together are "the app" — `app_core.py` has the
real `App`/tab classes; `app.py` is a thin compatibility shim (historical
entry point) that also fixes tab-frame packing.

## Layered file map

### 1. Domain model (no GUI, no I/O) — read these to understand *data*
| File | Purpose |
|---|---|
| `models.py` | `Entry`, `Songpack`, `BiomeCondition`, `DimensionCondition`, `BlockCondition` dataclasses. The single source of truth for songpack state. |
| `constants.py` | Fixed event categories (Special/Time/Weather/.../Combat) straight from `MAKING_SONGPACKS.md`, biome/biome-tag name lists, rarity-score weights. |
| `condition_logic.py` | Two-way conversion: `Entry`'s structured checkbox/list state ⇄ the raw `events: [...]` YAML string array. `build_events()` and `parse_events()`. |
| `case_grouping.py` | Groups `pack.entries` by song ("cases of a song"), by biome ("cases of a biome") or, with `is_tag=True`, by biome tag ("cases of a tag"). Pure functions over the entries list. |
| `scopes.py` | "Global" / "default" songs. `Entry.scope` is editor-only metadata persisted in `songpack_scopes.json` (keyed by an entry's events + songs, so it survives a YAML round trip). Also the blocker check (`find_blockers`, `enable_fallback_on_blockers`): which entries above a global song stop it being reached in which biomes. No special YAML output: a global/default entry is a plain entry with no `BIOME=`, pinned below normal entries. |
| `priority.py` | Rarity scoring (`score_entry`) that drives "Auto-arrange by rarity", plus `find_broader_fallbacks` (the "mix into this entry" variety helper). |
| `mod_versions.py` | Feature-gate table: which ReactiveMusic mod version introduced which condition/flag, Minecraft-version → mod-version lookup, and the `songpack_target.json` sidecar (editor-only metadata, never written into the actual YAML). |

### 2. Persistence / I/O — read these for load/save behavior
| File | Purpose |
|---|---|
| `yaml_io.py` | Load/save `ReactiveMusic.yaml`. Handles merging entries that share identical conditions into one YAML entry with a song pool, and matches the mod author's preferred YAML formatting style (quoted strings, indented lists). |
| `biome_customization.py` | Two *separate* colour/attribute stores: per-songpack overrides (`biome_customization.json` next to a songpack) vs. bundled app defaults (`default_biome_colors.json` next to this script, shipped with the editor). Also owns the biome chart's temperature/humidity/erosion/weirdness attribute data, the bundled **tag membership** (`load_app_tag_members`, `tag_members`), and everything derived from it: a tag's averaged colour (`tag_color`) and averaged chart attributes (`tag_attributes`). |
| `default_biome_colors.json` | The bundled defaults data file itself. Keys: `biomes` (name → colour), `biome_tags` (**tag → list of the biomes it contains** — tags have no colour of their own), `biome_dimensions`, `biome_attributes` (chart data). Rarely needs to be read in full — just know what the keys are. |
| `audio_io.py` | Pure audio logic (no tkinter): probing, waveform peak extraction, trim/export via `soundfile`+`numpy`. Safe to call from worker threads. |
| `block_data.py` | Static list of common vanilla block IDs for the nearby-block picker. |

### 3. Simulation engine (pure logic, no GUI)
| File | Purpose |
|---|---|
| `simulation.py` | "What would the mod actually play here?" engine behind the Biome Simulator tab. Implements the mod's real evaluation rules (top-to-bottom, first-valid-entry-wins, `allowFallback` chains, biome/tag/dimension/block matching, `forceStop*` transitions). Tag matching uses the bundled JSON's tag lists (`_tag_table`, with a small built-in fallback), and `make_tag_state` builds the "somewhere inside a biome of tag T" situation used by the tag map. Read this to understand simulator *semantics*; read `simulator_tab.py` for its UI. |

### 4. GUI — main window & tabs
| File | Purpose |
|---|---|
| `app_core.py` | **The biggest file.** Defines `App` (main window, menu, tab container) and three of the five tabs directly: `InfoTab` (songpack metadata + target mod build), `LibraryTab` (a.k.a. "Music & Conditions" — the condition editor, by far the most complex UI: fixed-category checkboxes, biome/dimension/block pickers, the Biome Map chart, case tabs, multi-select editing), `PriorityTab` (drag-reorderable priority list). Also has shared layout helpers (`_section`, `_flow_group`, typography constants). |
| `simulator_tab.py` | Tab 4, "Simulation Map": situation sliders (time/weather/height/underwater + collapsible extra conditions/manual facts) + the map + a playlist that imitates the mod + an embedded case editor, using `simulation.py` for all the actual logic. A selector above the map switches between the **Biomes** map and the **Biome tags** map (one `BiomeChart`, mode-dependent data). Everything below the map works on a *subject*: a biome name, or `"#" + tag`. |
| `settings_tab.py` | Tab 5, "Settings": editor-wide preferences (dark theme, double-click preview) and the biome/tag colour list editor (reads/writes via `biome_customization.py`). |
| `biome_chart.py` | The reusable "Biome Map" canvas widget (icons placed by temperature/humidity, shaped by erosion/weirdness). Used by both `LibraryTab` (editing one entry's biomes) and `simulator_tab.py` (situation preview) — it's handed callables, so it doesn't know about `Entry` or `Songpack` at all. Paints a gradient backdrop plus optional night/underwater/weather layers (`render_backdrop`, Pillow-rendered and cached). |
| `biome_case_editor.py` | Biome-first editing (as opposed to `LibraryTab`'s song-first editing), using the biome-side grouping in `case_grouping.py`. `BiomeCaseEditorPanel` is the copy embedded in the simulator's third column (with `is_tag=True` it edits the `BIOMETAG=` cases of a tag); `BiomeCaseEditorWindow` is the older standalone popup. Both share their editing methods (see the `setattr` loop at the bottom of the file). |
| `app_settings.py` | Editor-wide preferences persisted to `~/.rm-songpack-maker/settings.json` (NOT songpack data), plus the CTk↔ttk theming bridge (ttk.Treeview/Entry/etc. don't follow CustomTkinter's theme automatically). |

### 5. Audio editing subsystem
| File | Purpose |
|---|---|
| `audio_editor.py` | The waveform/trim/preview/save `CTkToplevel` window ("Edit audio…"). UI + threading glue around `audio_io.py` (decoding/export) and `audio_preview.py` (playback). |
| `audio_preview.py` | One shared `pygame.mixer.music` wrapper (`PreviewPlayer`) used by the song list's Preview button, the audio editor, and the simulator's playlist — because pygame's music channel is a single global stream, there must be exactly one state machine for it. |

### 6. Cross-cutting glue
| File | Purpose |
|---|---|
| `ui_enhancements.py` | `install(app)`: adds the Preview/Stop buttons under the song list, wraps `action_save_config` with a reload-and-verify step, and sanitizes filenames when loading a music folder (with user confirmation). Monkeypatches a few `App` methods after construction — check here if an `app.action_*` method behaves differently than its definition in `app_core.py` suggests. |
| `version_ui.py` | Trivial: adds a version label + links to the Help menu. |
| `main.py` | Entry point; wires the install functions above onto `app.App()`. |
| `app.py` | Compatibility shim: `from app_core import *`, subclasses `App` only to fix CTkTabview child packing. |

### 7. Reference / non-code
| File | Purpose |
|---|---|
| `MAKING_SONGPACKS.md` | **The spec.** Canonical description of the YAML format this whole editor is generating. Read this, not the editor code, to check "is this what ReactiveMusic actually supports?" |
| `ReactiveMusic.yaml-template.yaml` | A worked example songpack in the documented style — useful to sanity-check `yaml_io.py`'s output format. |
| `README.md` | User-facing docs: features, how to use the GUI, install instructions. Useful for understanding intended *user* workflow, not implementation. |
| `requirements.txt` | Runtime deps: PyYAML, pygame, customtkinter, soundfile, numpy. |

## Data flow for common tasks

**"A checkbox condition needs to change / a new condition type is needed":**
`constants.py` (define it) → `condition_logic.py` (build/parse to YAML tokens)
→ `models.py` (if it needs new Entry fields) → `app_core.py`
(`_build_fixed_categories` / `_build_biome_section` etc. render it) →
`mod_versions.py` (if it's version-gated) → `priority.py` (if it should
affect rarity scoring) → `simulation.py` (if the simulator needs to evaluate
it).

**"Saving/loading is wrong":** `yaml_io.py` is the whole story (load_songpack,
save_songpack, songpack_to_dict, merge_equivalent_entries). `models.py` for
what fields exist.

**"The condition editor UI needs a change":** `app_core.py`'s `LibraryTab` —
it's long; search for the specific `_build_*_section` method. Shared row/flow
helpers (`_section`, `_row`, `_flow_group`) live near the top of the file.

**"Biome Simulator behaves wrong":** logic bugs → `simulation.py`. Display/
interaction bugs → `simulator_tab.py`. Both share `biome_chart.py` for the
map widget itself.

**"Biome tag map / tag colours / tag membership":** membership lives in
`default_biome_colors.json` → `biome_tags`; `biome_customization.py` turns it
into positions/shape (`tag_attributes`) and colours (`tag_color`);
`simulator_tab.py` (`_chart_biomes`, `_chart_color`, `_plan_for`) draws and
evaluates it; `simulation.py` (`_tag_table`, `make_tag_state`) does the matching.

**"Auto-arrange / priority order is wrong":** `priority.py` (`score_entry`,
`auto_priority_order`). `constants.py` has the tunable weights. Scope tiers (normal → global → default) are enforced by `priority.enforce_scope_order`, called from `PriorityTab.refresh` and `yaml_io.merge_equivalent_entries`.

**"Global / default songs don't play where they should":** `scopes.find_blockers` (what blocks them), `simulation.build_plan` (`terminal_entry_id` = the entry that ends the fallback chain), and the `allowFallback` checkboxes (per case in `biome_case_editor.py`, per entry in `LibraryTab`).

**"Audio playback/trimming misbehaves":** `audio_io.py` (pure logic) vs.
`audio_editor.py` (window/threading) vs. `audio_preview.py` (shared player
state machine) — figure out which layer first.

**"Case tabs (multiple condition-sets per song/biome) are wrong":**
`case_grouping.py` for the grouping logic itself; `app_core.py::LibraryTab`
(song-first case UI) or `biome_case_editor.py` (biome-first case UI) for the
two different front-ends onto it.

**"Target mod version / feature gating":** `mod_versions.py` entirely —
`FEATURE_MIN_MOD_VERSION` table, `supports()`, `resolve()`, `validate_pack()`.

**"Biome colours/custom biomes look wrong":** `biome_customization.py` —
note the two distinct stores (per-songpack `biome_customization.json` vs.
bundled `default_biome_colors.json`), don't conflate them.

## Things that look like bugs but aren't (read the docstring first)

- `app_core.py`'s `_flow_group`, `_SmoothScrollFrame`, and the `<Configure>`
  binding quirks around `CTkFrame`/canvas are deliberate CustomTkinter
  workarounds — documented inline.
- `case_grouping.py` groupings are *recomputed live*, never cached/stored —
  if you're looking for where a "case" is persisted, it isn't; it's derived.
- `ui_enhancements.install()` reassigns some `app.action_*` methods *after*
  `app_core.py` defines them — several places in `app_core.py` call through
  a `lambda: self.action_x()` indirection specifically so this still works
  regardless of install order.
- `audio_preview.py`'s single shared `PreviewPlayer` instance
  (`get_player()`) is intentional — don't create a second player for a new
  feature; reuse it or preview code will fight over the pygame channel.
- A biome tag's icon on the tag map is derived, not stored: position =
  average temperature/humidity of its biomes, lobe depth = average erosion,
  lobe count from **`round(average weirdness)`** (so tags only ever have 0, 4 or
  8 lobes — deliberate, see `tag_attributes`). Its colour is the average of its
  biomes' colours unless the songpack overrides it.
- The `"#"` prefix on simulator subjects (`"#IS_HOT"`) is what tells a tag from
  a biome in the shared plan cache / pinned / playlist state; it is never
  written anywhere else.
- The chart background is an image, not canvas items; the weather emoji is drawn as a mask so it is
  colourless. If no emoji font is found it falls back to canvas text in a blended colour.
- Biome/dimension/block "combine" mode (OR vs AND) is a real per-category,
  per-entry setting (`entry.fixed_combine`, `biome_combine`, etc.), not just
  a display option — see `condition_logic.build_events`.
