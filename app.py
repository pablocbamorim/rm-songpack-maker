"""
app.py
------
The Tkinter GUI for the ReactiveMusic Songpack Editor.

Three tabs:
  1. Songpack Info      -- the global yaml keys (name, author, ...)
  2. Music & Conditions  -- pick a song, check the conditions that should
                            trigger it, see a live preview + rarity score
  3. Priority Order      -- the auto-computed (and freely drag-reorderable)
                            play-priority list

See README.md for the reasoning behind the rarity scoring and the
"variety mixing" fallback helper.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

import constants as C
import block_data
import yaml_io
import priority
import condition_logic
from models import Songpack, Entry, BiomeCondition, DimensionCondition, BlockCondition


# ---------------------------------------------------------------------------
# Tab 1: Songpack Info
# ---------------------------------------------------------------------------
class InfoTab(ttk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        pad = {"padx": 8, "pady": 5}

        container = ttk.Frame(self)
        container.pack(anchor="nw", padx=10, pady=10)

        self.name_var = tk.StringVar()
        self.version_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.description_var = tk.StringVar()
        self.credits_var = tk.StringVar()
        self.switch_var = tk.StringVar()
        self.delay_var = tk.StringVar()
        self.root_key_var = tk.StringVar()

        text_rows = [
            ("Songpack Name", self.name_var),
            ("Version", self.version_var),
            ("Author", self.author_var),
            ("Description", self.description_var),
            ("Credits", self.credits_var),
        ]
        r = 0
        for label, var in text_rows:
            ttk.Label(container, text=label + ":").grid(row=r,
                                                        column=0, sticky="e", **pad)
            ttk.Entry(container, textvariable=var, width=55).grid(
                row=r, column=1, sticky="w", **pad)
            r += 1

        ttk.Label(container, text="Music Switch Speed:").grid(
            row=r, column=0, sticky="e", **pad)
        ttk.Combobox(container, textvariable=self.switch_var, values=C.MUSIC_SWITCH_SPEEDS,
                     state="readonly", width=15).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(container, text="Music Delay Length:").grid(
            row=r, column=0, sticky="e", **pad)
        ttk.Combobox(container, textvariable=self.delay_var, values=C.MUSIC_DELAY_LENGTHS,
                     state="readonly", width=15).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(container, text="Entries root key:").grid(
            row=r, column=0, sticky="e", **pad)
        ttk.Entry(container, textvariable=self.root_key_var,
                  width=20).grid(row=r, column=1, sticky="w", **pad)
        r += 1
        ttk.Label(
            container,
            text=("Auto-detected when you load an existing file. MAKING_SONGPACKS.md doesn't\n"
                  "show this key explicitly, so only change it if your installed mod version\n"
                  "expects something other than the default ('entries')."),
            foreground="#666", justify="left",
        ).grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        ttk.Button(self, text="Apply changes", command=self._apply_clicked).pack(
            anchor="w", padx=10, pady=(0, 10))
        ttk.Label(
            self,
            text="(Changes here are also applied automatically when you switch tabs or save.)",
            foreground="#666",
        ).pack(anchor="w", padx=10)

    def _apply_clicked(self):
        self.pull_into_pack()
        self.app.set_status("Songpack info updated.")

    def push_from_pack(self):
        p = self.app.pack
        self.name_var.set(p.name)
        self.version_var.set(p.version)
        self.author_var.set(p.author)
        self.description_var.set(p.description)
        self.credits_var.set(p.credits)
        self.switch_var.set(p.music_switch_speed)
        self.delay_var.set(p.music_delay_length)
        self.root_key_var.set(p.entries_root_key)

    def pull_into_pack(self):
        p = self.app.pack
        p.name = self.name_var.get()
        p.version = self.version_var.get()
        p.author = self.author_var.get()
        p.description = self.description_var.get()
        p.credits = self.credits_var.get()
        p.music_switch_speed = self.switch_var.get() or "NORMAL"
        p.music_delay_length = self.delay_var.get() or "NORMAL"
        p.entries_root_key = self.root_key_var.get().strip() or "entries"


# ---------------------------------------------------------------------------
# Tab 2: Music & Conditions
# ---------------------------------------------------------------------------
class LibraryTab(ttk.Frame):
    # Prefix shown next to entries that have no trigger conditions set yet
    # (i.e. they'd "always match" -- usually a sign the user forgot to
    # configure them, so we flag it visually in the list).
    WARNING_PREFIX = "\u26a0 "  # ⚠

    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        self.selected_entry_id = None
        self.category_vars = {}  # cat -> {option: BooleanVar}

        # ---- left: entry list -------------------------------------------------
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)

        btn_row = ttk.Frame(left)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="+ Add Entry",
                   command=self._add_blank_entry).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Load Music Folder…",
                   command=self.app.action_load_music_folder).pack(side="left", padx=2)
        ttk.Button(btn_row, text="Remove", command=self._remove_selected).pack(
            side="left", padx=2)

        # -- search box: filter the entry list by song name --
        search_row = ttk.Frame(left)
        search_row.pack(fill="x", pady=(6, 0))
        ttk.Label(search_row, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(
            search_row, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.search_var.trace_add(
            "write", lambda *_: self.refresh_tree(keep_selection=True))
        ttk.Button(search_row, text="✕", width=2,
                   command=lambda: self.search_var.set("")).pack(side="left", padx=(2, 0))

        columns = ("song", "summary", "score")
        self.tree = ttk.Treeview(
            left, columns=columns, show="headings", selectmode="browse", height=22)
        self.tree.heading("song", text="Song")
        self.tree.heading("summary", text="Conditions (preview)")
        self.tree.heading("score", text="Rarity")
        self.tree.column("song", width=180, anchor="w")
        self.tree.column("summary", width=260, anchor="w")
        self.tree.column("score", width=55, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=(6, 0))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ---- right: condition editor -------------------------------------------
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)

        header = ttk.Frame(right)
        header.pack(fill="x")
        self.editor_title = ttk.Label(
            header, text="Select a song on the left to view/edit its trigger conditions.",
            font=("", 10, "bold"),
        )
        self.editor_title.pack(side="left")
        self.toggle_btn = ttk.Button(
            header, text="▾ Hide editor", command=self._toggle_editor)
        self.toggle_btn.pack(side="right")

        self.editor_outer = ttk.Frame(right)
        self.editor_outer.pack(fill="both", expand=True, pady=(6, 0))

        self.canvas = tk.Canvas(self.editor_outer, highlightthickness=0)
        vscroll = ttk.Scrollbar(
            self.editor_outer, orient="vertical", command=self.canvas.yview)
        self.editor_frame = ttk.Frame(self.canvas)
        self.editor_frame.bind(
            "<Configure>", lambda e: self.canvas.configure(
                scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window(
            (0, 0), window=self.editor_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=vscroll.set)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(
            self.canvas_window, width=e.width))
        self.canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

        ttk.Label(
            self.editor_frame,
            text="Select a song from the list on the left to configure what makes it play.",
            foreground="#666",
        ).pack(anchor="w", padx=10, pady=10)

    # -- mouse wheel helpers -------------------------------------------------
    def _bind_mousewheel(self, _event=None):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event=None):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(1, "units")
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # -- list management -------------------------------------------------
    def refresh_tree(self, keep_selection=False):
        prev = self.selected_entry_id if keep_selection else None
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().lower()
        for entry in self.app.pack.entries:
            if query and not any(query in s.lower() for s in entry.songs):
                continue
            name = entry.display_name()
            if not entry.has_any_condition():
                name = self.WARNING_PREFIX + name
            self.tree.insert(
                "", "end", iid=entry.id,
                values=(name, condition_logic.summarize_entry(
                    entry), priority.score_entry(entry)),
            )
        if prev and self.tree.exists(prev):
            self.tree.selection_set(prev)

    def _add_blank_entry(self):
        name = simpledialog.askstring(
            "Add Entry", "Song filename (without extension), e.g. MyTrack:", parent=self,
        )
        entry = Entry(songs=[name] if name else [])
        self.app.pack.entries.append(entry)
        self.refresh_tree()
        self.tree.selection_set(entry.id)
        self.tree.see(entry.id)
        self.app.priority_tab.refresh()
        self.app.set_status(
            f"Added entry '{entry.display_name()}'. Configure its conditions below.")

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        entry_id = sel[0]
        entry = next(
            (e for e in self.app.pack.entries if e.id == entry_id), None)
        if not entry:
            return
        if not messagebox.askyesno("Remove entry", f"Remove '{entry.display_name()}' from the songpack?"):
            return
        self.app.pack.entries = [
            e for e in self.app.pack.entries if e.id != entry_id]
        if self.selected_entry_id == entry_id:
            self.selected_entry_id = None
            self._clear_editor(
                "Select a song from the list on the left to configure what makes it play.")
        self.refresh_tree()
        self.app.priority_tab.refresh()

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        entry_id = sel[0]
        self.selected_entry_id = entry_id
        entry = next(
            (e for e in self.app.pack.entries if e.id == entry_id), None)
        if entry:
            self.editor_title.config(
                text=f"Conditions for: {entry.display_name()}")
            if self.editor_outer.winfo_ismapped():
                self._build_editor_for(entry)

    def _clear_editor(self, message):
        for w in self.editor_frame.winfo_children():
            w.destroy()
        ttk.Label(self.editor_frame, text=message, foreground="#666").pack(
            anchor="w", padx=10, pady=10)
        self.editor_title.config(
            text="Select a song on the left to view/edit its trigger conditions.")

    def _toggle_editor(self):
        if self.editor_outer.winfo_ismapped():
            self.editor_outer.pack_forget()
            self.toggle_btn.config(text="▸ Show editor")
        else:
            self.editor_outer.pack(fill="both", expand=True, pady=(6, 0))
            self.toggle_btn.config(text="▾ Hide editor")
            if self.selected_entry_id:
                entry = next(
                    (e for e in self.app.pack.entries if e.id == self.selected_entry_id), None)
                if entry:
                    self._build_editor_for(entry)

    # -- helpers -------------------------------------------------
    def _available_biome_values(self, entry: Entry, is_tag: bool):
        """Biome/biome-tag options not already added to this entry, so the
        picker doesn't keep offering values that are already selected."""
        pool = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
        used = {b.value for b in entry.biomes if b.is_tag == is_tag}
        return [v for v in pool if v not in used]

    # -- editor construction -------------------------------------------------
    def _build_editor_for(self, entry: Entry):
        for w in self.editor_frame.winfo_children():
            w.destroy()
        self.category_vars = {}

        # -- fixed checkbox categories --
        for cat in C.FIXED_CATEGORY_ORDER:
            definition = C.FIXED_CATEGORIES[cat]
            frame = ttk.LabelFrame(
                self.editor_frame, text=f"{definition['label']}  (checked options = OR)")
            frame.pack(fill="x", padx=6, pady=4)
            option_vars = {}
            for opt in definition["options"]:
                var = tk.BooleanVar(
                    value=opt in entry.selected.get(cat, set()))
                ttk.Checkbutton(
                    frame, text=opt, variable=var,
                    command=lambda c=cat: self._on_fixed_changed(entry, c),
                ).pack(side="left", padx=4, pady=2)
                option_vars[opt] = var
            self.category_vars[cat] = option_vars

        # -- biome --
        biome_frame = ttk.LabelFrame(self.editor_frame, text="Biome")
        biome_frame.pack(fill="x", padx=6, pady=4)

        row1 = ttk.Frame(biome_frame)
        row1.pack(fill="x", padx=4, pady=2)
        ttk.Label(row1, text="Biome:").pack(side="left")
        self.biome_search_var = tk.StringVar()
        self.biome_is_tag_var = tk.BooleanVar(value=False)
        self.biome_combobox = ttk.Combobox(
            row1, textvariable=self.biome_search_var,
            values=self._available_biome_values(entry, False), width=24,
        )
        self.biome_combobox.pack(side="left", padx=4)

        def _on_biome_tag_toggle():
            self.biome_combobox.configure(
                values=self._available_biome_values(
                    entry, self.biome_is_tag_var.get())
            )

        ttk.Checkbutton(
            row1, text="Use as BIOMETAG (broader match)", variable=self.biome_is_tag_var,
            command=_on_biome_tag_toggle,
        ).pack(side="left", padx=8)
        ttk.Button(row1, text="Add", command=lambda: self._add_biome(
            entry)).pack(side="left", padx=4)

        row2 = ttk.Frame(biome_frame)
        row2.pack(fill="x", padx=4)
        ttk.Label(row2, text="Combine multiple biomes with:").pack(side="left")
        self.biome_combine_var = tk.StringVar(value=entry.biome_combine)
        for mode in (C.COMBINE_OR, C.COMBINE_AND):
            ttk.Radiobutton(
                row2, text=mode, value=mode, variable=self.biome_combine_var,
                command=lambda: self._set_combine(
                    entry, "biome_combine", self.biome_combine_var.get()),
            ).pack(side="left", padx=4)

        self.biome_listbox = tk.Listbox(
            biome_frame, height=min(4, max(2, len(entry.biomes))))
        self.biome_listbox.pack(fill="x", padx=4, pady=4)
        for b in entry.biomes:
            self.biome_listbox.insert(
                "end", ("[TAG] " if b.is_tag else "") + b.value)
        ttk.Button(biome_frame, text="Remove selected", command=lambda: self._remove_biome(entry)).pack(
            anchor="w", padx=4, pady=(0, 4)
        )

        # -- dimension --
        dim_frame = ttk.LabelFrame(self.editor_frame, text="Dimension")
        dim_frame.pack(fill="x", padx=6, pady=4)

        drow1 = ttk.Frame(dim_frame)
        drow1.pack(fill="x", padx=4, pady=2)
        ttk.Label(drow1, text="Dimension:").pack(side="left")
        self.dim_search_var = tk.StringVar()
        self.dim_combobox = ttk.Combobox(
            drow1, textvariable=self.dim_search_var, values=C.COMMON_DIMENSIONS, width=24)
        self.dim_combobox.pack(side="left", padx=4)
        ttk.Button(drow1, text="Add", command=lambda: self._add_dimension(
            entry)).pack(side="left", padx=4)

        drow2 = ttk.Frame(dim_frame)
        drow2.pack(fill="x", padx=4)
        ttk.Label(drow2, text="Combine multiple dimensions with:").pack(
            side="left")
        self.dim_combine_var = tk.StringVar(value=entry.dimension_combine)
        for mode in (C.COMBINE_OR, C.COMBINE_AND):
            ttk.Radiobutton(
                drow2, text=mode, value=mode, variable=self.dim_combine_var,
                command=lambda: self._set_combine(
                    entry, "dimension_combine", self.dim_combine_var.get()),
            ).pack(side="left", padx=4)

        self.dim_listbox = tk.Listbox(
            dim_frame, height=min(4, max(2, len(entry.dimensions))))
        self.dim_listbox.pack(fill="x", padx=4, pady=4)
        for d in entry.dimensions:
            self.dim_listbox.insert("end", d.value)
        ttk.Button(dim_frame, text="Remove selected", command=lambda: self._remove_dimension(entry)).pack(
            anchor="w", padx=4, pady=(0, 4)
        )

        # -- block --
        block_frame = ttk.LabelFrame(
            self.editor_frame, text="Nearby Blocks (25-block radius)")
        block_frame.pack(fill="x", padx=6, pady=4)

        brow1 = ttk.Frame(block_frame)
        brow1.pack(fill="x", padx=4, pady=2)
        ttk.Label(brow1, text="Block:").pack(side="left")
        self.block_search_var = tk.StringVar()
        self.block_combobox = ttk.Combobox(
            brow1, textvariable=self.block_search_var, values=block_data.COMMON_BLOCK_IDS, width=24
        )
        self.block_combobox.pack(side="left", padx=4)
        self.block_search_var.trace_add(
            "write", lambda *_: self._filter_block_options())
        ttk.Label(brow1, text="Min count:").pack(side="left", padx=(10, 0))
        self.block_count_var = tk.IntVar(value=1)
        ttk.Spinbox(brow1, from_=1, to=10000, textvariable=self.block_count_var, width=7).pack(
            side="left", padx=4)
        ttk.Button(brow1, text="Add", command=lambda: self._add_block(
            entry)).pack(side="left", padx=4)
        ttk.Label(
            block_frame, text="Tip: use /reactivemusic logBlockCounter in-game to see real counts.",
            foreground="#666",
        ).pack(anchor="w", padx=4)

        brow2 = ttk.Frame(block_frame)
        brow2.pack(fill="x", padx=4)
        ttk.Label(brow2, text="Combine multiple blocks with:").pack(side="left")
        self.block_combine_var = tk.StringVar(value=entry.block_combine)
        for mode in (C.COMBINE_AND, C.COMBINE_OR):
            ttk.Radiobutton(
                brow2, text=mode, value=mode, variable=self.block_combine_var,
                command=lambda: self._set_combine(
                    entry, "block_combine", self.block_combine_var.get()),
            ).pack(side="left", padx=4)

        self.block_listbox = tk.Listbox(
            block_frame, height=min(4, max(2, len(entry.blocks))))
        self.block_listbox.pack(fill="x", padx=4, pady=4)
        for b in entry.blocks:
            self.block_listbox.insert(
                "end", f"{b.block_id}  (min {b.min_count})")
        ttk.Button(block_frame, text="Remove selected", command=lambda: self._remove_block(entry)).pack(
            anchor="w", padx=4, pady=(0, 4)
        )

        # -- advanced / fallback behaviour --
        adv_frame = ttk.LabelFrame(
            self.editor_frame, text="Advanced / Fallback Behaviour")
        adv_frame.pack(fill="x", padx=6, pady=4)

        self.allow_fallback_var = tk.BooleanVar(value=entry.allow_fallback)
        ttk.Checkbutton(
            adv_frame,
            text="allowFallback — once this entry's own song(s) are exhausted, let a broader\n"
                 "entry play instead of repeating (recommended ON, especially for rare/narrow entries)",
            variable=self.allow_fallback_var,
            command=lambda: self._on_advanced_changed(entry),
        ).pack(anchor="w", padx=4, pady=2)

        self.force_stop_changed_var = tk.BooleanVar(
            value=entry.force_stop_on_changed)
        ttk.Checkbutton(
            adv_frame, text="forceStopMusicOnChanged (stop current music whenever this event's validity flips)",
            variable=self.force_stop_changed_var, command=lambda: self._on_advanced_changed(
                entry),
        ).pack(anchor="w", padx=4, pady=1)

        self.force_stop_valid_var = tk.BooleanVar(
            value=entry.force_stop_on_valid)
        ttk.Checkbutton(
            adv_frame, text="forceStopMusicOnValid (stop current music when this event becomes valid)",
            variable=self.force_stop_valid_var, command=lambda: self._on_advanced_changed(
                entry),
        ).pack(anchor="w", padx=4, pady=1)

        self.force_stop_invalid_var = tk.BooleanVar(
            value=entry.force_stop_on_invalid)
        ttk.Checkbutton(
            adv_frame, text="forceStopMusicOnInvalid (stop current music when this event becomes invalid)",
            variable=self.force_stop_invalid_var, command=lambda: self._on_advanced_changed(
                entry),
        ).pack(anchor="w", padx=4, pady=1)

        self.force_start_var = tk.BooleanVar(value=entry.force_start_on_valid)
        ttk.Checkbutton(
            adv_frame, text="forceStartMusicOnValid (immediately start this entry once valid, if music stopped)",
            variable=self.force_start_var, command=lambda: self._on_advanced_changed(
                entry),
        ).pack(anchor="w", padx=4, pady=1)

        chance_row = ttk.Frame(adv_frame)
        chance_row.pack(fill="x", padx=4, pady=(4, 6))
        ttk.Label(chance_row, text="forceChance:").pack(side="left")
        self.force_chance_var = tk.DoubleVar(value=entry.force_chance)
        ttk.Scale(
            chance_row, from_=0.0, to=1.0, variable=self.force_chance_var, orient="horizontal", length=180,
            command=lambda _v: self._on_advanced_changed(entry),
        ).pack(side="left", padx=4)
        self.force_chance_label = ttk.Label(
            chance_row, text=f"{entry.force_chance:.2f}")
        self.force_chance_label.pack(side="left")

        # -- custom / unrecognised raw conditions --
        custom_frame = ttk.LabelFrame(
            self.editor_frame, text="Custom / unrecognised raw conditions (one per line)")
        custom_frame.pack(fill="x", padx=6, pady=4)
        self.custom_text = tk.Text(custom_frame, height=3)
        self.custom_text.insert("1.0", "\n".join(entry.custom_raw_conditions))
        self.custom_text.pack(fill="x", padx=4, pady=4)
        self.custom_text.bind(
            "<FocusOut>", lambda _e: self._on_custom_changed(entry))
        ttk.Label(
            custom_frame,
            text="Conditions loaded from an existing file that this editor's checkboxes\n"
                 "couldn't fully represent land here verbatim instead of being lost.",
            foreground="#666",
        ).pack(anchor="w", padx=4, pady=(0, 4))

        # -- priority / variety helper --
        info_frame = ttk.LabelFrame(
            self.editor_frame, text="Priority & Variety")
        info_frame.pack(fill="x", padx=6, pady=(4, 12))
        self.score_label = ttk.Label(
            info_frame,
            text=f"Rarity score: {priority.score_entry(entry)}   "
            f"(higher = more specific = plays before broader/common entries)",
        )
        self.score_label.pack(anchor="w", padx=4, pady=2)

        if not entry.has_any_condition():
            ttk.Label(
                info_frame,
                text=f"{self.WARNING_PREFIX}This entry has no conditions set, so it always matches -- "
                "it will play whenever nothing higher in the priority list is valid.",
                foreground="#b45309",
            ).pack(anchor="w", padx=4, pady=(0, 6))

        fallbacks = priority.find_broader_fallbacks(
            entry, self.app.pack.entries)
        if fallbacks:
            ttk.Label(
                info_frame,
                text="These broader entries would also be valid whenever this one is. Mixing one\n"
                     "of their songs directly into this entry's own rotation lets it play here too,\n"
                     "right away, instead of waiting for this entry's songs to fully exhaust first\n"
                     "(so this song doesn't loop as annoyingly in rare situations):",
                justify="left",
            ).pack(anchor="w", padx=4, pady=(2, 4))
            for fb in fallbacks:
                row = ttk.Frame(info_frame)
                row.pack(fill="x", padx=12, pady=1)
                ttk.Label(row, text=f"{fb.display_name()}  —  {condition_logic.summarize_entry(fb, 40)}").pack(
                    side="left"
                )
                ttk.Button(
                    row, text="Mix into this entry", command=lambda fb=fb: self._mix_in_fallback(entry, fb)
                ).pack(side="right")
        else:
            ttk.Label(info_frame, text="No broader entries currently detected to mix in.", foreground="#666").pack(
                anchor="w", padx=4
            )

    # -- change handlers -------------------------------------------------
    def _on_fixed_changed(self, entry: Entry, cat: str):
        chosen = {opt for opt,
                  var in self.category_vars[cat].items() if var.get()}
        entry.selected[cat] = chosen
        self._refresh_after_change(entry, rebuild=False)

    def _on_advanced_changed(self, entry: Entry):
        entry.allow_fallback = self.allow_fallback_var.get()
        entry.force_stop_on_changed = self.force_stop_changed_var.get()
        entry.force_stop_on_valid = self.force_stop_valid_var.get()
        entry.force_stop_on_invalid = self.force_stop_invalid_var.get()
        entry.force_start_on_valid = self.force_start_var.get()
        entry.force_chance = round(self.force_chance_var.get(), 2)
        self.force_chance_label.config(text=f"{entry.force_chance:.2f}")
        self._refresh_after_change(entry, rebuild=False)

    def _on_custom_changed(self, entry: Entry):
        text = self.custom_text.get("1.0", "end").strip()
        entry.custom_raw_conditions = [
            line.strip() for line in text.splitlines() if line.strip()]
        self._refresh_after_change(entry, rebuild=False)

    def _set_combine(self, entry: Entry, attr: str, value: str):
        setattr(entry, attr, value)
        self._refresh_after_change(entry, rebuild=False)

    def _filter_block_options(self):
        text = self.block_search_var.get().strip().lower()
        if text:
            filtered = [
                b for b in block_data.COMMON_BLOCK_IDS if text in b.lower()]
        else:
            filtered = block_data.COMMON_BLOCK_IDS
        self.block_combobox["values"] = filtered[:50]

    def _add_biome(self, entry: Entry):
        value = self.biome_search_var.get().strip()
        if not value:
            return
        entry.biomes.append(BiomeCondition(
            value=value, is_tag=self.biome_is_tag_var.get()))
        self.biome_search_var.set("")
        self._refresh_after_change(entry, rebuild=True)

    def _remove_biome(self, entry: Entry):
        sel = self.biome_listbox.curselection()
        if not sel:
            return
        del entry.biomes[sel[0]]
        self._refresh_after_change(entry, rebuild=True)

    def _add_dimension(self, entry: Entry):
        value = self.dim_search_var.get().strip()
        if not value:
            return
        entry.dimensions.append(DimensionCondition(value=value))
        self.dim_search_var.set("")
        self._refresh_after_change(entry, rebuild=True)

    def _remove_dimension(self, entry: Entry):
        sel = self.dim_listbox.curselection()
        if not sel:
            return
        del entry.dimensions[sel[0]]
        self._refresh_after_change(entry, rebuild=True)

    def _add_block(self, entry: Entry):
        value = self.block_search_var.get().strip()
        if not value:
            return
        try:
            count = max(1, int(self.block_count_var.get()))
        except (tk.TclError, ValueError):
            count = 1
        entry.blocks.append(BlockCondition(block_id=value, min_count=count))
        self.block_search_var.set("")
        self._refresh_after_change(entry, rebuild=True)

    def _remove_block(self, entry: Entry):
        sel = self.block_listbox.curselection()
        if not sel:
            return
        del entry.blocks[sel[0]]
        self._refresh_after_change(entry, rebuild=True)

    def _mix_in_fallback(self, target_entry: Entry, source_entry: Entry):
        added = [s for s in source_entry.songs if s and s not in target_entry.songs]
        if not added:
            messagebox.showinfo(
                "Nothing to mix in", "That entry's song(s) are already part of this rotation.")
            return
        target_entry.songs.extend(added)
        target_entry.allow_fallback = True
        self._refresh_after_change(target_entry, rebuild=True)
        self.app.set_status(
            f"Mixed {', '.join(added)} into '{target_entry.songs[0]}' so it can play there too."
        )

    def _refresh_after_change(self, entry: Entry, rebuild: bool):
        if rebuild:
            self._build_editor_for(entry)
        else:
            self.score_label.config(
                text=f"Rarity score: {priority.score_entry(entry)}   "
                f"(higher = more specific = plays before broader/common entries)"
            )
        self.app.on_entry_conditions_changed(entry)


# ---------------------------------------------------------------------------
# Tab 3: Priority Order (drag & drop)
# ---------------------------------------------------------------------------
class PriorityTab(ttk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        self._drag_start_iid = None

        top = ttk.Frame(self)
        top.pack(fill="x", padx=8, pady=8)
        ttk.Label(
            top,
            text="Drag rows to reorder. The mod plays the first entry (top of this list) whose "
                 "conditions are currently true, so more specific/rare entries should sit above "
                 "broader, more common ones.",
            wraplength=680, justify="left",
        ).pack(side="left", fill="x", expand=True)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=8)
        ttk.Button(btns, text="Auto-arrange by rarity (recommended)", command=self._auto_arrange).pack(
            side="left", padx=2
        )
        ttk.Button(btns, text="Move Up",
                   command=lambda: self._nudge(-1)).pack(side="left", padx=2)
        ttk.Button(btns, text="Move Down", command=lambda: self._nudge(1)).pack(
            side="left", padx=2)

        columns = ("idx", "song", "score", "summary", "fallback")
        self.tree = ttk.Treeview(
            self, columns=columns, show="headings", selectmode="browse", height=24)
        headers = {"idx": "#", "song": "Song", "score": "Rarity",
                   "summary": "Conditions", "fallback": "Fallback"}
        widths = {"idx": 35, "song": 190, "score": 60,
                  "summary": 320, "fallback": 70}
        anchors = {"idx": "center", "song": "w", "score": "center",
                   "summary": "w", "fallback": "center"}
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor=anchors[c])
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tree.bind("<ButtonPress-1>", self._on_press)
        self.tree.bind("<B1-Motion>", self._on_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_release)

    def refresh(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for i, entry in enumerate(self.app.pack.entries, start=1):
            name = entry.display_name()
            if not entry.has_any_condition():
                name = LibraryTab.WARNING_PREFIX + name
            self.tree.insert(
                "", "end", iid=entry.id,
                values=(
                    i, name, priority.score_entry(entry),
                    condition_logic.summarize_entry(entry),
                    "yes" if entry.allow_fallback else "no",
                ),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def _auto_arrange(self):
        self.app.pack.entries = priority.auto_priority_order(
            self.app.pack.entries)
        self.refresh()
        self.app.library_tab.refresh_tree(keep_selection=True)
        self.app.set_status(
            "Priority order recomputed: rarest/most-specific entries now sit at the top.")

    def _nudge(self, direction: int):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        entries = self.app.pack.entries
        idx = next((i for i, e in enumerate(entries) if e.id == iid), None)
        if idx is None:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(entries):
            entries[idx], entries[new_idx] = entries[new_idx], entries[idx]
            self.refresh()
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _on_press(self, event):
        self._drag_start_iid = self.tree.identify_row(event.y)

    def _on_motion(self, event):
        if not self._drag_start_iid:
            return
        target = self.tree.identify_row(event.y)
        if target and target != self._drag_start_iid:
            self.tree.move(self._drag_start_iid, "", self.tree.index(target))

    def _on_release(self, _event):
        if self._drag_start_iid:
            self._sync_order_from_tree()
        self._drag_start_iid = None

    def _sync_order_from_tree(self):
        order_ids = self.tree.get_children("")
        id_to_entry = {e.id: e for e in self.app.pack.entries}
        self.app.pack.entries = [id_to_entry[i]
                                 for i in order_ids if i in id_to_entry]
        self.refresh()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ReactiveMusic Songpack Editor")
        self.geometry("1080x700")
        self.minsize(860, 560)

        self.pack_data = Songpack()
        self.music_source_folder = None
        self.current_save_folder = None

        self.status_var = tk.StringVar(
            value="Ready. Start with File > New Songpack, Load Config…, or Load Music Folder…"
        )

        self._build_menu()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.info_tab = InfoTab(self.notebook, self)
        self.library_tab = LibraryTab(self.notebook, self)
        self.priority_tab = PriorityTab(self.notebook, self)

        self.notebook.add(self.info_tab, text="Songpack Info")
        self.notebook.add(self.library_tab, text="Music & Conditions")
        self.notebook.add(self.priority_tab, text="Priority Order")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        status_bar = ttk.Label(
            self, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="bottom")

        self.refresh_all()

    @property
    def pack(self) -> Songpack:
        return self.pack_data

    def set_status(self, text: str):
        self.status_var.set(text)

    def refresh_all(self):
        self.info_tab.push_from_pack()
        self.library_tab.refresh_tree()
        self.priority_tab.refresh()

    def _on_tab_changed(self, _event=None):
        self.info_tab.pull_into_pack()
        self.priority_tab.refresh()
        self.library_tab.refresh_tree(keep_selection=True)

    def on_entry_conditions_changed(self, _entry: Entry):
        self.library_tab.refresh_tree(keep_selection=True)
        self.priority_tab.refresh()

    # -- menu -------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="New Songpack",
                             command=self.action_new_songpack)
        filemenu.add_command(label="Load Config…",
                             command=self.action_load_config)
        filemenu.add_command(label="Load Music Folder…",
                             command=self.action_load_music_folder)
        filemenu.add_separator()
        filemenu.add_command(label="Save Config…",
                             command=self.action_save_config)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(
            label="How priority & variety work", command=self.action_show_about)
        menubar.add_cascade(label="Help", menu=helpmenu)

        self.config(menu=menubar)

    # -- actions -------------------------------------------------
    def action_new_songpack(self):
        if not messagebox.askyesno("New Songpack", "Discard the current songpack and start a new one?"):
            return
        self.pack_data = Songpack()
        self.music_source_folder = None
        self.current_save_folder = None
        self.refresh_all()
        self.set_status("Started a new, empty songpack.")

    def action_load_config(self):
        path = filedialog.askdirectory(
            title="Select the songpack folder (containing ReactiveMusic.yaml)")
        if not path:
            return
        try:
            self.pack_data = yaml_io.load_songpack(path)
        except Exception as exc:  # noqa: BLE001 - surface any load error to the user
            messagebox.showerror("Load failed", str(exc))
            return
        self.current_save_folder = path
        self.refresh_all()
        self.set_status(
            f"Loaded {len(self.pack_data.entries)} entries from {path}")

    def action_load_music_folder(self):
        folder = filedialog.askdirectory(
            title="Select the folder containing your .mp3/.ogg/.wav files")
        if not folder:
            return
        stems = yaml_io.scan_music_folder(folder)
        existing = {s for e in self.pack_data.entries for s in e.songs}
        added = 0
        for stem in stems:
            if stem not in existing:
                self.pack_data.entries.append(Entry(songs=[stem]))
                added += 1
        self.music_source_folder = folder
        self.refresh_all()
        self.set_status(
            f"Found {len(stems)} audio file(s) in {folder}, added {added} new blank entries. "
            f"Configure their conditions in the 'Music & Conditions' tab."
        )

    def action_save_config(self):
        self.info_tab.pull_into_pack()
        if not self.pack_data.entries:
            if not messagebox.askyesno("Save Config", "This songpack has no entries yet. Save anyway?"):
                return
        folder = filedialog.askdirectory(
            title="Choose (or create) a folder to save this songpack into")
        if not folder:
            return
        copy_music = False
        if self.music_source_folder:
            copy_music = messagebox.askyesno(
                "Copy music files?",
                f"Copy referenced audio files from:\n{self.music_source_folder}\ninto:\n{folder}/music/ ?",
            )
        try:
            path = yaml_io.save_songpack(
                self.pack_data, folder,
                copy_music_from=self.music_source_folder if copy_music else None,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Save failed", str(exc))
            return
        self.current_save_folder = folder
        self.set_status(f"Saved to {path}")
        messagebox.showinfo("Saved", f"Songpack saved to:\n{path}")

    def action_show_about(self):
        messagebox.showinfo(
            "How priority & variety work",
            "Entries are auto-scored by how specific their conditions are: more, narrower "
            "conditions score higher (rarer), fewer/broader ones score lower. 'Auto-arrange "
            "by rarity' sorts entries highest-score-first, because the mod plays the first "
            "entry (top to bottom) whose conditions are currently all true.\n\n"
            "To stop a rare song from looping, every new entry defaults to allowFallback=ON: "
            "once an entry's own song(s) have all played, the mod falls through to the next "
            "valid (broader) entry instead of repeating.\n\n"
            "For a more direct fix, open a narrow entry's editor -- if a broader entry would "
            "also be valid in the same situation, it's suggested under 'Priority & Variety' "
            "with a 'Mix into this entry' button, which copies that broader song straight into "
            "this entry's own rotation so it can play there immediately, not just after this "
            "entry's songs run out.",
        )


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
