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

## Mental model: one list, one condition model, many views

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
- **Simulation Map → select a biome** groups entries by `BIOME=`
  condition ("cases" of a biome); on the **Biome tags** map it groups them by
  `BIOMETAG=` condition ("cases" of a tag). A tag case is a plain entry — songs
  added to a tag are *not* copied onto its biomes; the entry just matches all of
  them (the simulator resolves tags through the bundled membership table).
- **Priority Order tab** shows `entries` in raw list order (= play priority:
  first match wins, per the mod's own rules).

Both groupings are *computed on the fly* from entry data (see
`case_grouping.py`) — there's no separate "case id". Edit from either view
and the other one is automatically consistent on next redraw.

### The condition model (`conditions.py`)

An entry's `events` array is an **AND of ORs** (array items are AND'd, `a || b`
inside an item is OR'd). `conditions.py` is the *only* place that interprets
that: it parses items into `Atom`s (fixed event / BIOME / BIOMETAG / DIM /
BLOCK / unknown), provides `soft_match` (the mod's substring matching for
`BIOME=`/`DIM=`), `canonical()` (order-insensitive form for comparing logic),
`features_used()` (version gating) and `expression_implies()` (reachability).

The structured `Entry` fields (checkbox sets, biome/dimension/block lists +
OR/AND mode) are only a **projection** of that expression for what the widgets
can write back *exactly*. `condition_logic.parse_events` moves a group into a
structured field only when that is lossless; everything else (an OR across
categories such as `BIOME=ocean || UNDERWATER`, two OR groups in one category,
unknown tokens) stays verbatim, item by item, in `Entry.custom_raw_conditions`.
**Analysis code must not look at individual GUI fields:** it calls
`condition_logic.entry_clauses(entry)` / `entry_atoms(entry)`, which cover the
structured fields *and* the verbatim items. The simulator, priority scoring,
biome case discovery, chart highlighting, version gating and save validation
all do.

### Logical entries (`entry_pools.py`)

The editor keeps one `Entry` per song, but YAML entries hold song *pools*.
Entries that are **adjacent** in priority order and have the same canonical
conditions, flags, scope and extra fields are written as one YAML entry.
Non-adjacent duplicates are *not* merged (that used to hoist a later entry's
songs above the entries between them). `entry_pools.logical_view()` is the pack
exactly as ReactiveMusic will read it; the simulator, the blocker check and
save verification all use it, never the raw list, so a prediction and the saved
file cannot disagree.
When a YAML entry contains multiple songs, `entry_pools.expand_song_pools()` restores the editor's one-Entry-per-song view before a music-folder scan. `entry_pools.reconcile_music_folder_entries()` then adds only genuinely missing audio stems; save-time `merge_equivalent_entries()` can still collapse adjacent equivalent rows back into a YAML song pool.

## Startup chain

```
main.py
  → app.App()            (app.py wraps app_core.App, fixes CTkTabview packing)
  → app_core.App.__init__()        (theme.install_ctk_theme() runs first, before any CTk widget exists; then loads editor preferences and builds the gradient header and tabs)
  → best-effort last-songpack restore (from app_settings.py)
  → ui_enhancements.install(app)   (adds preview buttons, save verification,
                                     filename sanitization — monkeypatches
                                     a few App methods)
  → version_ui.install(app)        (adds a version label to the Help menu)
  → app.mainloop()
```

On a successful restore, the last opened songpack folder is loaded and the
window selects **Simulation Map**. A missing or invalid restore target is
cleared and startup continues with a fresh songpack. `_restore_last_songpack` and
`action_load_config` each run the same load sequence (`yaml_io.load_songpack` +
`biome_customization.load`/`load_attributes` + `mod_versions.apply_to_pack`), so
change one and you must change the other.

`app.py` and `app_core.py` together are "the app" — `app_core.py` has the
real `App`/tab classes; `app.py` is a thin compatibility shim (historical
entry point) that also fixes tab-frame packing.

## Tabs and cross-tab refresh hooks

Tab order (as built in `App.__init__`): **Songpack Info · Music & Conditions ·
Simulation Map · Priority Order · Settings**. The app opens on Simulation Map.

Because every tab is a view over `app.pack.entries`, anything that mutates it from
outside its own tab must tell the others. The hooks live on `App` (`app_core.py`):

| Hook | Call it when | Refreshes |
|---|---|---|
| `refresh_all()` | A whole new pack is in place (New, Load, session restore) | Every tab |
| `on_entry_conditions_changed(entry)` | One entry's conditions changed in the Music & Conditions editor | Song list, Priority tab |
| `on_pack_entries_changed()` | Entries were added/removed/edited from somewhere else (the simulator's embedded case editor) | Song list, Priority tab, simulator |
| `on_target_changed()` | The target Minecraft/mod version moved (Songpack Info) | Condition editor (re-gates unsupported conditions) |
| `on_biome_colors_changed()` | A colour or custom biome changed in Settings | Condition editor, simulator map |
| `apply_theme()` | Light/dark was toggled | CTk appearance, ttk styles, simulator chart + tree tags |
| `focus_entry_in_library(entry_id)` | "Open full editor…" in the case editor | Switches to Music & Conditions and selects the song row |
| `mark_dirty()` | Any songpack-affecting edit (see below) | Title bar gets a "• unsaved changes" suffix |
| `mark_clean()` | A load/save/new-songpack just made the in-memory pack match disk | Title bar suffix clears |

`mark_dirty()` is called from the four hooks above (`on_entry_conditions_changed`,
`on_pack_entries_changed`, `on_target_changed`, `on_biome_colors_changed`) plus a
handful of mutation sites that don't go through them (add/remove entry or case,
scope changes, priority reordering, Songpack Info's "Apply changes", loading a
music folder). If you add a new place that mutates `pack.entries` or songpack
metadata outside those hooks, call `self.app.mark_dirty()` (or, from a module
that doesn't import `App`, `getattr(app, "mark_dirty", lambda: None)()`) there
too, or the title bar / exit-confirmation will silently miss it.
`action_new_songpack`, `action_load_config` and `_restore_last_songpack` call
`mark_clean()` after `refresh_all()`; `action_save_config` and the new
`action_quick_save()` (bound to Ctrl+S — saves straight back to
`current_save_folder`, skipping the folder dialog, the "Saved" popup and
`ui_enhancements`' reload/verify step) call it after a successful write.
`_on_close_window` (the `WM_DELETE_WINDOW` handler, and File > Exit) confirms
before discarding unsaved work, mirroring `action_new_songpack` /
`action_load_config`.

Switching tabs (`_on_tab_changed`) also pulls the Songpack Info fields into the pack,
refreshes the priority and song lists, and rebuilds the simulator's cached plans
when it comes into view. If you add a new place that edits `pack.entries`, call
`on_pack_entries_changed()` rather than refreshing individual tabs yourself.

## Files a songpack save produces (and who reads them)

Saving and loading are **not symmetrical**: some files are handled inside
`yaml_io`, others by `App` directly, so a new save/load path has to cover all of them.

| File | Written by | Read by | Notes |
|---|---|---|---|
| `ReactiveMusic.yaml` | `yaml_io.save_songpack` | `yaml_io.load_songpack` | The only file ReactiveMusic reads. |
| `songpack_scopes.json` | `scopes.save`, called from `yaml_io.save_songpack` (deleted when nothing is scoped) | `scopes.apply_to_entries`, called from `yaml_io.load_songpack` | Global/default markers. |
| `biome_customization.json` | `biome_customization.save`, called from `App.action_save_config` | `biome_customization.load` / `load_attributes` / `load_tag_members`, called from `App.action_load_config` and `_restore_last_songpack` | Custom biome/tag colours and chart attributes, plus `biome_tag_members` additions from the custom-biome tag picker. These memberships are merged into `simulation` via `simulation.set_custom_tag_members()`. |
| `songpack_target.json` | `mod_versions.save`, called from `App.action_save_config` | `mod_versions.load` + `apply_to_pack`, from the same load paths | Target Minecraft/mod version and platform. |
| `~/.rm-songpack-maker/settings.json` | `app_settings.save` | `app_settings.load` | Editor prefs, not songpack data: `dark_theme`, `double_click_preview`, `preview_volume`, `last_songpack_folder`, `show_empty_biome_tags`. |
| `default_biome_colors.json` (bundled) | Nothing at runtime | `biome_customization` (cached) | Read-only from the UI. The `save_app_default_color` / `remove_app_default_color` helpers still exist but no screen calls them. |

`save_songpack` is called with `copy_music_from=None`, so audio is never copied.
`yaml_io._copy_referenced_music` exists but is not wired to anything yet.

## Layered file map

### 1. Domain model (no GUI, no I/O) — read these to understand *data*
| File | Purpose |
|---|---|
| `models.py` | `Entry`, `Songpack`, `BiomeCondition`, `DimensionCondition`, `BlockCondition` dataclasses. The single source of truth for songpack state. |
| `constants.py` | Fixed event categories (Special/Time/Weather/.../Combat) straight from `MAKING_SONGPACKS.md`, biome/biome-tag name lists, rarity-score weights. |
| `condition_logic.py` | Two-way conversion: `Entry`'s structured checkbox/list state ⇄ the raw `events: [...]` YAML string array. `build_events()` and `parse_events()` (lossless: see above), plus `entry_clauses()`/`entry_atoms()`/`canonical_events()`. |
| `conditions.py` | The canonical condition expression (AND of ORs of `Atom`s), the single `soft_match` for `BIOME=`/`DIM=`, canonical/implication helpers. No dependencies on models or the GUI. **Read this first** when a condition behaves differently in two views. |
| `entry_pools.py` | Logical entries: which neighbouring editor entries are saved as one song pool (`merge_groups`, `logical_view`, `semantic_snapshot`). |
| `pack_validation.py` | Save-time sanity report (no songs, no conditions, bad `forceChance`, entries that can never play). Warnings only; never edits the pack. |
| `case_grouping.py` | Groups `pack.entries` by song ("cases of a song"), by biome ("cases of a biome", soft-matching, reading every atom incl. verbatim items) or, with `is_tag=True`, by biome tag ("cases of a tag"). Also song-pool helpers (`pool_songs`, `cases_containing_song`, `secondary_songs`). Pure functions over the entries list. |
| `scopes.py` | "Global" / "default" songs. `Entry.scope` is editor-only metadata persisted in `songpack_scopes.json` (keyed by an entry's events + songs, so it survives a YAML round trip). Also the blocker check (`find_blockers`, `enable_fallback_on_blockers`): which entries above a global song stop it being reached in which biomes. No special YAML output: a global/default entry is a plain entry with no `BIOME=`, pinned below normal entries. |
| `priority.py` | Rarity scoring (`score_entry`) that drives "Auto-arrange by rarity", plus `find_broader_fallbacks` (the "mix into this entry" variety helper). |
| `mod_versions.py` | Feature-gate table: which ReactiveMusic mod version introduced which condition/flag, Minecraft-version → mod-version lookup, and the `songpack_target.json` sidecar (editor-only metadata, never written into the actual YAML). |

### 2. Persistence / I/O — read these for load/save behavior
| File | Purpose |
|---|---|
| `yaml_io.py` | Load/save `ReactiveMusic.yaml`. Validates types on load (`SongpackFormatError` lists every problem; nothing is truthiness-coerced and a malformed entries list can no longer load as an empty pack), preserves unknown per-entry and top-level keys (`Entry.extra_fields`, `Songpack.extra_top_level`), writes song pools via `entry_pools`, and matches the mod author's preferred YAML style (quoted strings, indented lists). |
| `biome_customization.py` | Two *separate* colour/attribute stores: per-songpack overrides (`biome_customization.json` next to a songpack) vs. bundled app defaults (`default_biome_colors.json` next to this script, shipped with the editor). Also owns the biome chart's temperature/humidity/erosion/weirdness attribute data, the bundled **tag membership** (`load_app_tag_members`, `tag_members`), and everything derived from it: a tag's averaged colour (`tag_color`) and averaged chart attributes (`tag_attributes`). |
| `default_biome_colors.json` | The bundled defaults data file itself. Keys: `biomes` (name → colour), `biome_tags` (**tag → list of the biomes it contains** — tags have no colour of their own), `biome_dimensions`, `biome_attributes` (chart data). Rarely needs to be read in full — just know what the keys are. |
| `audio_io.py` | Pure audio logic (no tkinter): probing, waveform peak extraction, trim/export via `soundfile`+`numpy`. Safe to call from worker threads. |
| `block_data.py` | Static list of common vanilla block IDs for the nearby-block picker. |

### 3. Simulation engine (pure logic, no GUI)
| File | Purpose |
|---|---|
| `simulation.py` | "What would the mod actually play here?" engine behind the Biome Simulator tab. Implements the mod's real evaluation rules (top-to-bottom, first-valid-entry-wins, `allowFallback` chains, biome/tag/dimension/block matching, and the transition model: `evaluate_transition` = forceStop* + armed forceStartMusicOnValid with `forceChance`). Feed it `entry_pools.logical_view(...).entries`, not the raw list. Tag matching uses the bundled JSON's tag lists (`_tag_table`, with a small built-in fallback), and `make_tag_state` builds the "somewhere inside a biome of tag T" situation used by the tag map. Read this to understand simulator *semantics*; read `simulator_tab.py` for its UI. |

### 4. GUI — main window & tabs
| File | Purpose |
|---|---|
| `app_core.py` | **The biggest file.** Defines `App` (main window, menu, tab container) and three of the five tabs directly: `InfoTab` (songpack metadata + target mod build), `LibraryTab` (a.k.a. "Music & Conditions" — the condition editor, by far the most complex UI: fixed-category checkboxes, biome/dimension/block pickers, the Biome Map chart, case tabs, multi-select editing), `PriorityTab` (drag-reorderable priority list). Also has shared layout helpers (`_section`, `_flow_group`, typography constants). |
| `simulator_tab.py` | Tab 3, "Simulation Map" (three persistent columns: map · playlist · embedded case editor; `StepSlider` is its discrete situation slider): situation sliders (time/weather/height/underwater + collapsible extra conditions/manual facts) + the map + a playlist that imitates the mod + an embedded case editor, using `simulation.py` for all the actual logic. A selector above the map switches between the **Biomes** map and the **Biome tags** map (one `BiomeChart`, mode-dependent data). Everything below the map works on a *subject*: a biome name, or `"#" + tag`. |
| `settings_tab.py` | Tab 5, "Settings": editor-wide preferences (dark theme, double-click preview) and the biome/tag colour list editor (reads/writes via `biome_customization.py`). |
| `biome_chart.py` | The reusable "Biome Map" canvas widget (icons placed by temperature/humidity, shaped by erosion/weirdness). Used by both `LibraryTab` (editing one entry's biomes) and `simulator_tab.py` (situation preview) — it's handed callables, so it doesn't know about `Entry` or `Songpack` at all. Paints a gradient backdrop plus optional night/underwater/weather layers (`render_backdrop`, Pillow-rendered and cached). Optional hooks used by the simulator: `on_hover`, `tooltip_lines`, `action_labels`, `on_right_click`, `backdrop`. It has a bottom-right resize grip whose height is remembered in the module-level `_RESIZED_HEIGHT`. |
| `biome_case_editor.py` | Biome-first editing (as opposed to `LibraryTab`'s song-first editing), using the biome-side grouping in `case_grouping.py`. `BiomeCaseEditorPanel` is the copy embedded in the simulator's third column (with `is_tag=True` it edits the `BIOMETAG=` cases of a tag); `BiomeCaseEditorWindow` is the older standalone popup (`open_biome_case_editor`). Nothing in the UI opens it any more (right-clicking a map icon now just selects it), but it is still where the panel's shared methods are defined and copied from. Both share their editing methods (see the `setattr` loop at the bottom of the file). |
| `theme.py` | The visual identity (palette sampled from the logo) and the ONE place colours live. `install_ctk_theme()` patches CustomTkinter's theme before the first widget exists. `(light, dark)` tuples and the `NEUTRAL_BUTTON` / `DANGER_BUTTON` / `TAB_*` dicts go straight into CTk widgets; `tree_colors`, `listbox_colors`, `toplevel_bg`, `chart_palette` and `waveform_palette` serve widgets CTk doesn't manage (ttk trees, raw tk listboxes/toplevels/canvases). Also builds the gradient header and window backdrop (`build_header`, `build_background`; Pillow, degrading to solid colours). Imports no GUI library at module level, so it is unit-testable headless (`test_theme.py`). |
| `app_settings.py` | Editor-wide preferences persisted to `~/.rm-songpack-maker/settings.json` (NOT songpack data), plus the CTk↔ttk theming bridge (ttk.Treeview/Entry/etc. don't follow CustomTkinter's theme automatically). |

### 5. Audio editing subsystem
| File | Purpose |
|---|---|
| `audio_editor.py` | The waveform/trim/preview/save `CTkToplevel` window ("Edit audio…"). UI + threading glue around `audio_io.py` (decoding/export) and `audio_preview.py` (playback). |
| `audio_preview.py` | One shared `pygame.mixer.music` wrapper (`PreviewPlayer`) used by the song list's Preview button, the audio editor, and the simulator's playlist — because pygame's music channel is a single global stream, there must be exactly one state machine for it. |

### 6. Cross-cutting glue
| File | Purpose |
|---|---|
| `ui_enhancements.py` | `install(app)`: adds the Preview/Stop buttons under the song list, wraps `action_save_config` with a reload-and-verify step, and sanitizes filenames when loading a music folder (with user confirmation). It also publishes `app.resolve_entry_audio_path` and `app.action_edit_audio`, which the "Edit audio…" button and `audio_editor` reuse. Monkeypatches a few `App` methods after construction — check here if an `app.action_*` method behaves differently than its definition in `app_core.py` suggests. |
| `version_ui.py` | Trivial: adds a version label + links to the Help menu. |
| `main.py` | Entry point; wires the install functions above onto `app.App()`. |
| `app.py` | Compatibility shim: `from app_core import *`, subclasses `App` only to fix CTkTabview child packing. |

### 7. Reference / non-code
| File | Purpose |
|---|---|
| `MAKING_SONGPACKS.md` | **The spec.** Canonical description of the YAML format this whole editor is generating. Read this, not the editor code, to check "is this what ReactiveMusic actually supports?" |
| `ReactiveMusic.yaml-template.yaml` | A worked example songpack in the documented style — useful to sanity-check `yaml_io.py`'s output format. |
| `README.md` | User-facing docs: features, how to use the GUI, install instructions. Useful for understanding intended *user* workflow, not implementation. |
| `assets/` | `SoundpackMaker.ico` (window icon, `main.py`), `SoundpackMaker512.png` (header logo, `theme.py`) and the README screenshots. A missing icon/logo is tolerated (silently skipped). |
| `requirements.txt` | Runtime deps: PyYAML, pygame, customtkinter, Pillow, soundfile, numpy. |

## Tests

`python -m unittest discover -s tests -v` (no GUI libraries needed). The
regression tests in `tests/test_entry_logic.py` cover the fixtures of the entry-
logic repair plan: round-trip stability of boolean structure, cross-category OR,
merge/priority consistency, unknown-field preservation, type validation, soft
matching, version gating, force transitions and save validation.

Two smaller suites live at the repo root: `test_fixes.py` (`priority.is_broader_than`,
`scopes` detection of biome conditions hidden in verbatim items, `entry_pools`
positions after scope sorting, `yaml_io` top-level type validation) and
`test_theme.py` (logo gradient and palette; the gradient tests are skipped without
Pillow). From the repo root: `python -m unittest test_fixes test_theme -v`.

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

**"Loading a music folder after loading a config":** `yaml_io.scan_music_folder()` finds the audio stems; `entry_pools.reconcile_music_folder_entries()` expands any YAML song pools into the editor's one-song-per-entry view and appends blank entries for stems that are not already represented. Both `app_core.py`'s fallback action and `ui_enhancements.py`'s installed action call that shared helper so their reconciliation rules cannot drift.

**"The condition editor UI needs a change":** `app_core.py`'s `LibraryTab` —
it's long; search for the specific `_build_*_section` method. Shared row/flow
helpers (`_section`, `_row`, `_flow_group`) live near the top of the file.

**"Simulation Map behaves wrong":** logic bugs → `simulation.py`. Display/
interaction bugs → `simulator_tab.py`. Both share `biome_chart.py` for the
map widget itself.

**"Clicking biomes on the Music & Conditions map doesn't add/remove the right condition":**
`app_core.py::LibraryTab._build_biome_map_section`, `_on_chart_toggle` (adds/removes a
plain `BIOME=`), `_active_biome_keys` (which icons show a ✔ — reads every atom
through `conditions.soft_match`, so broader names and verbatim items light up too) and
`_chart_biomes` (the dimension filter). Drawing itself is `biome_chart.py`.

**"Editing a biome's / tag's cases from the Simulation Map":** the grouping is
`case_grouping.biome_cases` (`is_tag=True` for tags); the UI is
`biome_case_editor.BiomeCaseEditorPanel`, created by
`simulator_tab._show_editor_for` and reporting the selected case back through
`_on_case_selected`. Edits end in `App.on_pack_entries_changed()`.

**"Colours / dark mode / fonts look wrong":** `theme.py` (tokens and per-toolkit
helpers), then `App.apply_theme` → `app_settings.apply_ttk_theme` →
`app_core._configure_ttk_typography`, in that order (see the gotcha below).

**"Session restore / last songpack":** `App._restore_last_songpack`, the
`last_songpack_folder` key in `app_settings.py`, written by `action_load_config` and
`action_save_config`.

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
- The song-first list has one row per **primary** song (`songs[0]`). The other
  members of a YAML song pool have no row of their own: the row label lists the
  whole pool, search matches every pool member, and `case_grouping.
  cases_containing_song` finds every entry a song plays in. (Giving pool members
  their own rows needs row ids that are not entry ids; not done yet.)
- Entries with **no `BIOME=`** and cross-category items are normal: a
  `custom_raw_conditions` string is *not* opaque, it is parsed on demand by
  `conditions.py`.
- `allowFallback` defaults to **false** (MAKING_SONGPACKS.md). An old note in
  `mod_versions.py` quotes a 0.5.0 release note that reads as if it became the
  default; unconfirmed, the editor follows the spec.
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
  biomes' colours unless the songpack overrides it. A tag with an empty (or
  attribute-less) membership list is not dropped by the underlying tag-attribute
  table: it gets a centred `(0, 0, 0, 0)` icon. The `show_empty_biome_tags`
  preference hides those entries on both tag maps by default, while a custom
  biome explicitly added to a tag counts as known membership.
  `simulation.set_custom_tag_members()` invalidates the tag-table cache so
  `BIOMETAG=` evaluation sees those additions immediately.
- The `"#"` prefix on simulator subjects (`"#IS_HOT"`) is what tells a tag from
  a biome in the shared plan cache / pinned / playlist state; it is never
  written anywhere else.
- The chart background is an image, not canvas items; the weather emoji is drawn as a mask so it is
  colourless. If no emoji font is found it falls back to canvas text in a blended colour.
- Biome/dimension/block "combine" mode (OR vs AND) is a real per-category,
  per-entry setting (`entry.fixed_combine`, `biome_combine`, etc.), not just
  a display option — see `condition_logic.build_events`.
- Theming is two layers applied in a fixed order by `App.apply_theme`:
  `app_settings.apply_ttk_theme` (CTk→ttk bridge; may switch the ttk theme to
  `clam`, which resets ttk styles) and then `app_core._configure_ttk_typography`
  (fonts and `theme.tree_colors`). Reversing them loses the fonts/colours.
  `SettingsTab` still builds its colour list from plain `ttk` widgets.
- Custom biomes added in the UI get a colour but **no chart attributes**, so they
  never appear on the maps unless `biome_attributes` is added to
  `biome_customization.json` by hand (`biome_customization.load_attributes` reads
  it; nothing in the UI writes it).
