"""
biome_case_editor.py
---------------------
Biome-first editing, reached by right-clicking a biome icon on the Biome
Simulator's map.

Music & Conditions (app_core.LibraryTab) edits *song-first*: pick a song,
then tick the conditions that trigger it, with tabs for several "cases"
(condition sets) of that same song. This window is the same idea turned
around, *biome-first*: pick a biome on the map, see every "case" already
defined for it (every Entry whose ``biomes`` list names this biome), and
for each case edit its extra conditions (time of day, weather, ...) and
the pool of songs that play under it -- closer to how
MAKING_SONGPACKS.md and the template songpack actually read, entry by
entry, event set to song list.

Both views work because a "case" is never stored anywhere of its own --
see case_grouping.py. It's always just a live grouping over
``app.pack.entries``, by primary song here vs. by biome there. Add a case
here, and case_grouping.group_by_song() picks it up as a new case of its
song the next time the Music & Conditions tab draws its list; add a case
there, and case_grouping.biome_cases() picks it up here the next time this
window (re)opens for that biome. Nothing needs to be told to "sync".

Full power (biome tags, dimensions, nearby blocks, multiple biomes on one
entry, forceStop*/forceChance, allowFallback) still lives in Music &
Conditions -- this window sticks to the common case (one biome, the fixed
time/weather/etc. categories, and a song pool) and offers a button to jump
to the full editor for anything more advanced.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

import case_grouping
import condition_logic
import constants as C
import priority
import yaml_io
from models import Entry

_BODY = ("", 13)
_BODY_BOLD = ("", 13, "bold")
_SECTION = ("", 15, "bold")
_TITLE = ("", 17, "bold")
_SMALL = ("", 11)
_SMALL_BOLD = ("", 11, "bold")

_TAB_ON = (("#3B8ED0", "#1F6AA5"), ("#36719F", "#144870"), "#FFFFFF")
_TAB_OFF = (("#D5D9DE", "#3A3A3A"), ("#C4C8CE", "#4A4A4A"),
            ("#1A1A1A", "#DCE4EE"))

#: One open editor per biome name at a time, so right-clicking the same
#: biome twice focuses the existing window instead of stacking copies.
_OPEN: dict = {}



# The embedded panel intentionally reuses the window editor's data/editing
# methods. Both views therefore mutate the same app.pack.entries objects and
# keep the song-first and biome-first editors in lockstep.
for _name in (
    "_cases", "_current_entry", "_refresh_case_bar", "_restyle_case_tabs",
    "_select_case", "_add_case", "_remove_case", "_build_editor",
    "_build_category", "_on_category_changed", "_set_combine",
    "_build_songs_section", "_add_song", "_remove_song", "_open_full_editor",
    "_changed", "_update_score_label",
):
    setattr(BiomeCaseEditorPanel, _name, getattr(BiomeCaseEditorWindow, _name))


def open_biome_case_editor(app, biome_name: str) -> None:
    existing = _OPEN.get(biome_name)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        except tk.TclError:
            _OPEN.pop(biome_name, None)
    _OPEN[biome_name] = BiomeCaseEditorWindow(app, biome_name)


def _available_songs(app) -> list:
    """Every song name worth offering in the "add song" picker: whatever
    is in the loaded music folder, plus every song already used anywhere
    in the pack (so picking an existing song by name is always possible
    even without a music folder loaded).
    """
    names = set()
    folder = getattr(app, "music_source_folder", None)
    if folder:
        try:
            names.update(yaml_io.scan_music_folder(folder))
        except OSError:
            pass
    for entry in app.pack.entries:
        names.update(entry.songs)
    return sorted(names)


class BiomeCaseEditorPanel(ctk.CTkFrame):
    """Embedded version of the biome-first editor used by Simulation Map.

    The same editing methods as the standalone biome editor are reused here,
    but the chrome lives inside a normal frame so the simulator can keep the
    editor visible beside the map and playlist instead of opening a separate
    window only after a right-click.
    """

    def __init__(self, app, biome_name: str):
        super().__init__(app, corner_radius=10)
        self.app = app
        self.biome_name = biome_name
        self.active_case = 0
        self._case_tab_buttons = []
        self._category_vars = {}
        self._build_embedded_chrome()
        self._refresh_case_bar()
        self._select_case(0 if self._cases() else None)

    def _build_embedded_chrome(self) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(
            outer, text=f"Edit: {self.biome_name}", font=_TITLE, anchor="w",
        ).pack(fill="x", padx=4, pady=(2, 6))

        bar = ctk.CTkFrame(outer, corner_radius=8)
        bar.pack(fill="x")
        top = ctk.CTkFrame(bar, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=8)
        self._tabs_frame = ctk.CTkFrame(top, fg_color="transparent")
        self._tabs_frame.pack(side="left", fill="x", expand=True)
        self.remove_case_btn = ctk.CTkButton(
            top, text="Remove case", width=100, font=_BODY,
            fg_color=("#C24C4C", "#A03030"),
            hover_color=("#A03030", "#7A2020"),
            command=self._remove_case,
        )
        self.remove_case_btn.pack(side="right", padx=(6, 0))

        self.body = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(8, 0))

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", pady=(8, 0))
        self.score_label = ctk.CTkLabel(
            footer, text="", font=_SMALL, anchor="w",
            text_color=("gray40", "gray70"),
        )
        self.score_label.pack(fill="x", expand=True)

    def _on_close(self) -> None:
        """Embedded editors stay mounted; selection changes control visibility."""
        pass



class BiomeCaseEditorWindow(ctk.CTkToplevel):
    def __init__(self, app, biome_name: str):
        super().__init__(app)
        self.app = app
        self.biome_name = biome_name
        self.active_case = 0
        self._case_tab_buttons: list = []
        self._category_vars: dict = {}

        self.title(f"Songs for biome: {biome_name}")
        self.geometry("760x660")
        self.minsize(640, 520)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_chrome()
        self._refresh_case_bar()
        self._select_case(0 if self._cases() else None)

        self.after(60, self.focus_force)

    # -- data --------------------------------------------------------------
    def _cases(self):
        return case_grouping.biome_cases(self.app.pack, self.biome_name)

    def _current_entry(self) -> Optional[Entry]:
        cases = self._cases()
        if not cases:
            return None
        index = max(0, min(self.active_case, len(cases) - 1))
        return cases[index]

    # -- chrome --------------------------------------------------------------
    def _build_chrome(self) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        header = ctk.CTkFrame(outer, corner_radius=8)
        header.pack(fill="x")
        ctk.CTkLabel(
            header, text=f"Songs for biome: {self.biome_name}", font=_TITLE,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(
            header,
            text=("Each case below is its own set of conditions for this biome -- e.g. "
                  "\"day + sunrise\" vs. \"night + sunset\" vs. \"sun + rain\" -- with its "
                  "own pool of songs. A biome plays whenever ANY of its cases matches."),
            font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
            justify="left", wraplength=700,
        ).pack(fill="x", padx=14, pady=(2, 10))

        # -- case tab bar --
        bar = ctk.CTkFrame(outer, corner_radius=8)
        bar.pack(fill="x", pady=(10, 0))
        top = ctk.CTkFrame(bar, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=8)
        self._tabs_frame = ctk.CTkFrame(top, fg_color="transparent")
        self._tabs_frame.pack(side="left", fill="x", expand=True)
        self.remove_case_btn = ctk.CTkButton(
            top, text="Remove case", width=110, font=_BODY,
            fg_color=("#C24C4C", "#A03030"), hover_color=("#A03030", "#7A2020"),
            command=self._remove_case,
        )
        self.remove_case_btn.pack(side="right", padx=(6, 0))

        # -- scrollable editor body --
        self.body = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        self.body.pack(fill="both", expand=True, pady=(10, 0))

        # -- footer --
        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", pady=(10, 0))
        self.score_label = ctk.CTkLabel(
            footer, text="", font=_SMALL, anchor="w",
            text_color=("gray40", "gray70"))
        self.score_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            footer, text="Close", width=90, font=_BODY,
            fg_color=("#B0B0B0", "#3A3A3A"), hover_color=("#909090", "#4A4A4A"),
            command=self._on_close,
        ).pack(side="right")

        self.bind("<Escape>", lambda _e: self._on_close())

    # -- case tab bar --------------------------------------------------------
    def _refresh_case_bar(self) -> None:
        for w in self._tabs_frame.winfo_children():
            w.destroy()
        self._case_tab_buttons = []
        cases = self._cases()
        for index in range(len(cases)):
            btn = ctk.CTkButton(
                self._tabs_frame, text=f"Case {index + 1}", width=96,
                height=30, corner_radius=6, font=_BODY,
                command=lambda n=index: self._select_case(n),
            )
            btn.pack(side="left", padx=(0, 6))
            self._case_tab_buttons.append(btn)
        ctk.CTkButton(
            self._tabs_frame, text="+ Add case", width=110, height=30,
            corner_radius=6, font=_BODY, fg_color="transparent",
            border_width=1, text_color=("#1A1A1A", "#DCE4EE"),
            hover_color=("#D5D9DE", "#3A3A3A"), command=self._add_case,
        ).pack(side="left", padx=(0, 6))
        self.remove_case_btn.configure(
            state="normal" if cases else "disabled")
        self._restyle_case_tabs()

    def _restyle_case_tabs(self) -> None:
        cases = self._cases()
        for index, button in enumerate(self._case_tab_buttons):
            text = f"Case {index + 1}"
            if index < len(cases) and not cases[index].songs:
                text += "  (no songs)"
            fg, hover, tc = _TAB_ON if index == self.active_case else _TAB_OFF
            try:
                button.configure(text=text, fg_color=fg, hover_color=hover,
                                 text_color=tc)
            except tk.TclError:
                pass

    def _select_case(self, index: Optional[int]) -> None:
        self.active_case = index or 0
        self._restyle_case_tabs()
        self._build_editor()

    def _add_case(self) -> None:
        new_entry = case_grouping.add_biome_case(
            self.app.pack, self.biome_name)
        cases = self._cases()
        self.active_case = cases.index(new_entry)
        self._refresh_case_bar()
        self._build_editor()
        self.app.on_pack_entries_changed()
        self.app.set_status(
            f"Added Case {self.active_case + 1} for biome '{self.biome_name}'. "
            "Set its conditions and songs below.")

    def _remove_case(self) -> None:
        cases = self._cases()
        if not cases:
            return
        index = max(0, min(self.active_case, len(cases) - 1))
        victim = cases[index]
        detail = ""
        if victim.songs:
            detail = f"\n\nIts songs ({', '.join(victim.songs)}) go with it."
        if not messagebox.askyesno(
                "Remove case",
                f"Remove Case {index + 1} for biome '{self.biome_name}'?{detail}",
                parent=self):
            return
        self.app.pack.entries = [
            e for e in self.app.pack.entries if e.id != victim.id]
        self.active_case = max(0, index - 1)
        self._refresh_case_bar()
        self._build_editor()
        self.app.on_pack_entries_changed()
        self.app.set_status(f"Removed a case for biome '{self.biome_name}'.")

    # -- editor body ----------------------------------------------------------
    def _build_editor(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        self._category_vars = {}

        entry = self._current_entry()
        if entry is None:
            ctk.CTkLabel(
                self.body,
                text=("No cases yet for this biome. Click \"+ Add case\" above to "
                      "create the first one, then add songs to it."),
                font=_BODY, text_color=("gray40", "gray70"), justify="left",
                wraplength=680,
            ).pack(anchor="w", padx=10, pady=12)
            self.score_label.configure(text="")
            return

        # -- extra conditions (the fixed categories) --
        for cat in C.FIXED_CATEGORY_ORDER:
            self._build_category(entry, cat)

        if (entry.biomes and len(entry.biomes) > 1) or entry.dimensions or entry.blocks:
            ctk.CTkLabel(
                self.body,
                text=(f"{chr(0x26A0)} This case also has biome/dimension/nearby-block "
                      "conditions beyond this biome, set from Music & Conditions. "
                      "They stay as-is; use \"Open full editor\" below to change them."),
                font=_SMALL, text_color=("#b45309", "#E0A030"), justify="left",
                anchor="w", wraplength=680,
            ).pack(anchor="w", padx=10, pady=(2, 6))

        # -- songs --
        self._build_songs_section(entry)

        # -- jump to full editor --
        link_row = ctk.CTkFrame(self.body, fg_color="transparent")
        link_row.pack(fill="x", padx=4, pady=(6, 10))
        ctk.CTkButton(
            link_row, text="Open full editor in Music & Conditions…",
            width=260, font=_BODY,
            command=lambda e=entry: self._open_full_editor(e),
        ).pack(side="left")
        ctk.CTkLabel(
            link_row,
            text="(biome tags, dimensions, nearby blocks, forceStop/forceChance, allowFallback)",
            font=_SMALL, text_color=("gray40", "gray70"),
        ).pack(side="left", padx=(8, 0))

        self._update_score_label(entry)

    def _build_category(self, entry: Entry, cat: str) -> None:
        definition = C.FIXED_CATEGORIES[cat]
        card = ctk.CTkFrame(self.body, corner_radius=8)
        card.pack(fill="x", padx=4, pady=3)
        ctk.CTkLabel(card, text=definition["label"], font=_SMALL_BOLD,
                     anchor="w").pack(fill="x", padx=10, pady=(6, 0))

        fc = case_grouping.entry_fixed_combine(entry)
        mode_var = tk.StringVar(value=fc.get(cat, C.COMBINE_OR))
        combine_row = ctk.CTkFrame(card, fg_color="transparent")
        combine_row.pack(fill="x", padx=8, pady=(2, 0))
        ctk.CTkLabel(combine_row, text="Combine with:", font=_SMALL,
                     text_color=("gray40", "gray70")).pack(side="left")
        ctk.CTkSegmentedButton(
            combine_row, values=[C.COMBINE_OR, C.COMBINE_AND],
            variable=mode_var, font=_SMALL,
            command=lambda v, c=cat: self._set_combine(entry, c, v),
        ).pack(side="left", padx=8)

        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.pack(fill="x", padx=6, pady=(2, 6))
        option_vars = {}
        for opt in definition["options"]:
            already_set = opt in entry.selected.get(cat, set())
            var = tk.BooleanVar(value=already_set)
            ctk.CTkCheckBox(
                grid, text=opt, variable=var, font=_BODY,
                command=lambda c=cat: self._on_category_changed(entry, c),
            ).pack(side="left", padx=(0, 12), pady=2)
            option_vars[opt] = var
        self._category_vars[cat] = option_vars

    def _on_category_changed(self, entry: Entry, cat: str) -> None:
        chosen = {opt for opt, var in self._category_vars[cat].items()
                  if var.get()}
        entry.selected[cat] = chosen
        self._changed(entry)

    def _set_combine(self, entry: Entry, cat: str, value: str) -> None:
        case_grouping.entry_fixed_combine(entry)[cat] = value
        self._changed(entry)

    def _build_songs_section(self, entry: Entry) -> None:
        card = ctk.CTkFrame(self.body, corner_radius=8)
        card.pack(fill="x", padx=4, pady=(8, 3))
        ctk.CTkLabel(card, text="Songs in this case", font=_SECTION,
                     anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            card,
            text="Any of these can play when this case's conditions are true.",
            font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
        ).pack(fill="x", padx=10)

        listbox_wrap = ctk.CTkFrame(card, corner_radius=6)
        listbox_wrap.pack(fill="x", padx=8, pady=6)
        self.song_listbox = self.app.library_tab._themed_listbox(
            listbox_wrap, height=min(6, max(2, len(entry.songs))))
        self.song_listbox.pack(fill="x", padx=2, pady=2)
        for song in entry.songs:
            self.song_listbox.insert("end", song)

        add_row = ctk.CTkFrame(card, fg_color="transparent")
        add_row.pack(fill="x", padx=8, pady=(0, 8))
        self.song_var = tk.StringVar()
        self.song_combobox = ctk.CTkComboBox(
            add_row, variable=self.song_var,
            values=[s for s in _available_songs(
                self.app) if s not in entry.songs],
            width=260, font=_BODY)
        self.song_combobox.pack(side="left", padx=(0, 6))
        ctk.CTkButton(add_row, text="Add", width=64, font=_BODY,
                      command=lambda e=entry: self._add_song(e)).pack(
                          side="left", padx=2)
        ctk.CTkButton(
            add_row, text="Remove selected", width=140, font=_BODY,
            fg_color=("#B0B0B0", "#3A3A3A"), hover_color=("#909090", "#4A4A4A"),
            command=lambda e=entry: self._remove_song(e),
        ).pack(side="left", padx=2)

        if not getattr(self.app, "music_source_folder", None):
            ctk.CTkLabel(
                card,
                text="Tip: load a music folder (Music & Conditions tab) to pick songs from a list.",
                font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 6))

    def _add_song(self, entry: Entry) -> None:
        name = self.song_var.get().strip()
        if not name:
            return
        if name not in entry.songs:
            entry.songs.append(name)
        self.song_var.set("")
        self._changed(entry, rebuild=True)

    def _remove_song(self, entry: Entry) -> None:
        sel = self.song_listbox.curselection()
        if not sel:
            return
        del entry.songs[sel[0]]
        self._changed(entry, rebuild=True)

    def _open_full_editor(self, entry: Entry) -> None:
        self.app.focus_entry_in_library(entry.id)
        self._on_close()

    # -- change plumbing -------------------------------------------------
    def _changed(self, entry: Entry, rebuild: bool = False) -> None:
        if rebuild:
            self._build_editor()
        else:
            self._update_score_label(entry)
        self._restyle_case_tabs()
        self.app.on_pack_entries_changed()

    def _update_score_label(self, entry: Entry) -> None:
        summary = condition_logic.summarize_entry(entry, 80)
        self.score_label.configure(
            text=f"Conditions: {summary}   ·   Rarity score: {priority.score_entry(entry)}")

    def _on_close(self) -> None:
        _OPEN.pop(self.biome_name, None)
        try:
            self.destroy()
        except tk.TclError:
            pass
