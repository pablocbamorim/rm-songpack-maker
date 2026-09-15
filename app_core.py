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

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog, colorchooser
import customtkinter as ctk

import constants as C
import block_data
import yaml_io
import priority
import condition_logic
import biome_customization
import mod_versions
import app_settings
import settings_tab
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
        self.mc_var = tk.StringVar()
        self.mod_version_var = tk.StringVar()
        self.platform_var = tk.StringVar()
        # Guards the target traces while push_from_pack() is filling the
        # widgets, so loading a songpack doesn't look like a user edit.
        self._loading = False
        self._target_job = None

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

        # ---- target mod build -------------------------------------------
        ttk.Separator(container, orient="horizontal").grid(
            row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        r += 1
        ttk.Label(container, text="Target build (editor only — not written to the YAML)",
                  font=("", 9, "bold")).grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        ttk.Label(container, text="Minecraft Version:").grid(
            row=r, column=0, sticky="e", **pad)
        mc_row = ttk.Frame(container)
        mc_row.grid(row=r, column=1, sticky="w", **pad)
        ttk.Combobox(mc_row, textvariable=self.mc_var, values=mod_versions.MC_CHOICES,
                     width=22).pack(side="left")
        ttk.Label(mc_row, text="(you can also type a version that isn't listed)",
                  foreground="#666").pack(side="left", padx=(8, 0))
        r += 1

        ttk.Label(container, text="Reactive Music Version:").grid(
            row=r, column=0, sticky="e", **pad)
        mod_row = ttk.Frame(container)
        mod_row.grid(row=r, column=1, sticky="w", **pad)
        ttk.Combobox(
            mod_row, textvariable=self.mod_version_var,
            values=[mod_versions.MOD_VERSION_AUTO] +
            mod_versions.KNOWN_MOD_VERSIONS,
            width=22,
        ).pack(side="left")
        r += 1
        self.resolved_label = ttk.Label(
            container, text="", foreground="#666", justify="left", wraplength=520)
        self.resolved_label.grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        ttk.Label(container, text="Mod Platform:").grid(
            row=r, column=0, sticky="e", **pad)
        ttk.Combobox(container, textvariable=self.platform_var,
                     values=mod_versions.PLATFORM_CHOICES, state="readonly",
                     width=22).grid(row=r, column=1, sticky="w", **pad)
        r += 1
        ttk.Label(container, text=mod_versions.PLATFORM_NOTE,
                  foreground="#666", justify="left").grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        for var in (self.mc_var, self.mod_version_var, self.platform_var):
            var.trace_add("write", lambda *_: self._on_target_changed())

        ttk.Separator(container, orient="horizontal").grid(
            row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
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

    def _on_target_changed(self):
        """A target picker moved: record it, refresh the explanation line,
        and tell the rest of the app so the condition editor can re-gate
        itself immediately.
        """
        if self._loading:
            return
        # The Minecraft box is free-text, so coalesce keystrokes instead of
        # rebuilding the whole condition editor on every character.
        if self._target_job is not None:
            try:
                self.after_cancel(self._target_job)
            except tk.TclError:
                pass
        self._target_job = self.after(250, self._commit_target_change)

    def _commit_target_change(self):
        self._target_job = None
        self.pull_into_pack()
        self.refresh_resolved_label()
        self.app.on_target_changed()

    def refresh_resolved_label(self):
        _version, explanation = mod_versions.resolve(
            self.mc_var.get(), self.mod_version_var.get())
        self.resolved_label.config(text=explanation)

    def push_from_pack(self):
        p = self.app.pack
        self._loading = True
        self.mc_var.set(p.minecraft_version or mod_versions.MC_ANY)
        self.mod_version_var.set(
            p.mod_version or mod_versions.MOD_VERSION_AUTO)
        self.platform_var.set(p.platform or mod_versions.PLATFORM_ANY)
        self._loading = False
        self.refresh_resolved_label()
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

        mc = self.mc_var.get().strip()
        p.minecraft_version = "" if mc == mod_versions.MC_ANY else mc
        mod = self.mod_version_var.get().strip()
        p.mod_version = "" if mod == mod_versions.MOD_VERSION_AUTO else mod
        platform = self.platform_var.get().strip()
        p.platform = "" if platform == mod_versions.PLATFORM_ANY else platform


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
        self.selected_entry_ids: list[str] = []
        self.category_vars = {}  # cat -> {option: BooleanVar}

        # ---- left: entry list -------------------------------------------------
        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        self.left = left

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
            left, columns=columns, show="headings", selectmode="extended", height=22)
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
        prev = list(self.selected_entry_ids) if keep_selection else []
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
        valid_prev = [iid for iid in prev if self.tree.exists(iid)]
        if valid_prev:
            self.tree.selection_set(valid_prev)

    def _add_blank_entry(self):
        name = simpledialog.askstring(
            "Add Entry", "Song filename (without extension):")
        if not name:
            return
        if not name.lower().endswith((".mp3", ".ogg", ".wav")):
            name += ".mp3"
        self.app.pack.entries.append(Entry(songs=[name]))
        self.refresh_tree()
        self.app.priority_tab.refresh()

    def _remove_selected(self):
        ids = set(self.tree.selection())
        if not ids:
            return
        if not messagebox.askyesno("Remove", f"Remove {len(ids)} selected entr{'y' if len(ids) == 1 else 'ies'}?"):
            return
        self.app.pack.entries = [e for e in self.app.pack.entries if e.id not in ids]
        self.selected_entry_ids = []
        self.selected_entry_id = None
        self._clear_editor()
        self.refresh_tree()
        self.app.priority_tab.refresh()

    def _on_select(self, _event=None):
        ids = list(self.tree.selection())
        self.selected_entry_ids = ids
        self.selected_entry_id = ids[0] if ids else None
        if len(ids) == 1:
            entry = next((e for e in self.app.pack.entries if e.id == ids[0]), None)
            if entry:
                self._build_editor_for(entry)
        elif len(ids) > 1:
            entries = [e for e in self.app.pack.entries if e.id in ids]
            self._build_multi_editor_for(entries)
        else:
            self._clear_editor()

    def _clear_editor(self):
        for child in self.editor_frame.winfo_children():
            child.destroy()
        ttk.Label(
            self.editor_frame,
            text="Select a song from the list on the left to configure what makes it play.",
            foreground="#666",
        ).pack(anchor="w", padx=10, pady=10)

    def _toggle_editor(self):
        if self.editor_outer.winfo_ismapped():
            self.editor_outer.pack_forget()
            self.toggle_btn.configure(text="▸ Show editor")
        else:
            self.editor_outer.pack(fill="both", expand=True, pady=(6, 0))
            self.toggle_btn.configure(text="▾ Hide editor")

    def _build_editor_for(self, entry: Entry):
        for child in self.editor_frame.winfo_children():
            child.destroy()
        self.category_vars = {}
        self.editor_title.configure(text=f"Editing: {entry.display_name()}")
        self._build_condition_sections(self.editor_frame, entry)

    def _build_multi_editor_for(self, entries: list[Entry]):
        for child in self.editor_frame.winfo_children():
            child.destroy()
        self.category_vars = {}
        self.editor_title.configure(text=f"Editing {len(entries)} selected entries")
        self._build_multi_condition_sections(self.editor_frame, entries)

    def _build_condition_sections(self, parent, entry):
        pad = {"padx": 8, "pady": 4}
        ttk.Label(parent, text="Songs", font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
        song_frame = ttk.Frame(parent)
        song_frame.pack(fill="x", padx=10)
        self.song_vars = []
        for song in entry.songs:
            var = tk.StringVar(value=song)
            self.song_vars.append(var)
            row = ttk.Frame(song_frame)
            row.pack(fill="x", pady=2)
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
            ttk.Button(row, text="Remove", command=lambda v=var: self._remove_song(entry, v)).pack(side="right", padx=(4, 0))
        ttk.Button(song_frame, text="+ Add song", command=lambda: self._add_song(entry)).pack(anchor="w", pady=4)

        self._build_condition_categories(parent, entry)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", padx=10, pady=8)
        ttk.Label(parent, text="Entry settings", font=("", 10, "bold")).pack(anchor="w", padx=10, pady=(0, 2))
        settings = ttk.Frame(parent)
        settings.pack(fill="x", padx=10)
        self.fallback_var = tk.BooleanVar(value=entry.allow_fallback)
        ttk.Checkbutton(settings, text="Allow fallback to lower-priority entries", variable=self.fallback_var,
                        command=lambda: self._apply_entry_settings(entry)).pack(anchor="w", **pad)
        self.disabled_var = tk.BooleanVar(value=entry.disabled)
        ttk.Checkbutton(settings, text="Disabled", variable=self.disabled_var,
                        command=lambda: self._apply_entry_settings(entry)).pack(anchor="w", **pad)

    def _build_condition_categories(self, parent, entry):
        # Build the category checkboxes used by the existing condition model.
        self.category_vars = {}
        for category, options in condition_logic.condition_options(self.app, entry):
            lf = ttk.LabelFrame(parent, text=category)
            lf.pack(fill="x", padx=10, pady=5)
            vars_for_cat = {}
            for option, enabled in options:
                var = tk.BooleanVar(value=enabled)
                vars_for_cat[option] = var
                ttk.Checkbutton(
                    lf, text=option, variable=var,
                    command=lambda c=category, o=option: self._condition_toggled(entry, c, o),
                ).pack(anchor="w", padx=8, pady=2)
            self.category_vars[category] = vars_for_cat

    def _build_multi_condition_sections(self, parent, entries):
        ttk.Label(
            parent,
            text="Changes below are applied to all selected entries.",
            font=("", 10, "bold"),
        ).pack(anchor="w", padx=10, pady=(8, 6))
        for category, options in condition_logic.condition_options_multi(self.app, entries):
            lf = ttk.LabelFrame(parent, text=category)
            lf.pack(fill="x", padx=10, pady=5)
            for option, state in options:
                if state == "mixed":
                    text = f"{option} (mixed)"
                    value = False
                else:
                    text = option
                    value = bool(state)
                var = tk.BooleanVar(value=value)
                ttk.Checkbutton(
                    lf, text=text, variable=var,
                    command=lambda c=category, o=option, v=var: self._multi_condition_toggled(entries, c, o, v),
                ).pack(anchor="w", padx=8, pady=2)

    def _condition_toggled(self, entry, category, option):
        var = self.category_vars[category][option]
        condition_logic.set_condition(self.app, entry, category, option, bool(var.get()))
        self.app.on_entry_conditions_changed(entry)

    def _multi_condition_toggled(self, entries, category, option, var):
        condition_logic.set_condition_multi(self.app, entries, category, option, bool(var.get()))
        self.app.refresh_all()

    def _apply_entry_settings(self, entry):
        entry.allow_fallback = bool(self.fallback_var.get())
        entry.disabled = bool(self.disabled_var.get())
        self.app.on_entry_conditions_changed(entry)

    def _add_song(self, entry):
        entry.songs.append("new_song.mp3")
        self._build_editor_for(entry)
        self.app.on_entry_conditions_changed(entry)

    def _remove_song(self, entry, var):
        song = var.get()
        if len(entry.songs) <= 1:
            return
        entry.songs = [s for s in entry.songs if s != song]
        self._build_editor_for(entry)
        self.app.on_entry_conditions_changed(entry)


# ---------------------------------------------------------------------------
# Tab 3: Priority Order
# ---------------------------------------------------------------------------
class PriorityTab(ttk.Frame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        self._drag_start_iid = None
        self.tree = ttk.Treeview(
            self, columns=("song", "score"), show="headings", height=24)
        self.tree.heading("song", text="Entry")
        self.tree.heading("score", text="Rarity")
        self.tree.column("song", width=500, anchor="w")
        self.tree.column("score", width=100, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.tree.bind("<ButtonPress-1>", self._drag_start)
        self.tree.bind("<ButtonRelease-1>", self._drag_end)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(controls, text="Auto-arrange by rarity", command=self.auto_arrange).pack(side="left")
        ttk.Label(controls, text="Drag entries to reorder them manually.", foreground="#666").pack(side="left", padx=10)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for entry in self.app.pack.entries:
            self.tree.insert("", "end", iid=entry.id,
                             values=(entry.display_name(), priority.score_entry(entry)))

    def auto_arrange(self):
        self.app.pack.entries.sort(key=priority.score_entry, reverse=True)
        self.refresh()
        self.app.set_status("Entries arranged from highest to lowest rarity.")

    def _drag_start(self, event):
        self._drag_start_iid = self.tree.identify_row(event.y)

    def _drag_end(self, event):
        if not self._drag_start_iid:
            return
        target = self.tree.identify_row(event.y)
        if target and target != self._drag_start_iid:
            order = list(self.tree.get_children(""))
            order.remove(self._drag_start_iid)
            index = order.index(target)
            order.insert(index, self._drag_start_iid)
            id_to_entry = {e.id: e for e in self.app.pack.entries}
            self.app.pack.entries = [id_to_entry[i] for i in order if i in id_to_entry]
            self.refresh()
        self._drag_start_iid = None


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        ctk.set_default_color_theme("blue")
        self.settings = app_settings.load()
        ctk.set_appearance_mode(
            "dark" if self.settings.get("dark_theme", True) else "light")
        super().__init__()
        self.title("ReactiveMusic Songpack Editor")
        self.geometry("1080x700")
        self.minsize(860, 560)

        self.pack_data = Songpack()
        self.music_source_folder = None
        self.current_save_folder = None
        self.biome_custom_biomes = {}
        self.biome_custom_tags = {}

        # Editor-wide preferences are loaded before the tabs are built so
        # SettingsTab reads the persisted values on construction.
        self.status_var = tk.StringVar(
            value="Ready. Start with File > New Songpack, Load Config…, or Load Music Folder…"
        )

        self._build_menu()

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.info_tab = InfoTab(self.notebook, self)
        self.library_tab = LibraryTab(self.notebook, self)
        self.priority_tab = PriorityTab(self.notebook, self)
        self.settings_tab = settings_tab.SettingsTab(self.notebook, self)

        self.notebook.add(self.info_tab, text="Songpack Info")
        self.notebook.add(self.library_tab, text="Music & Conditions")
        self.notebook.add(self.priority_tab, text="Priority Order")
        self.notebook.add(self.settings_tab, text="Settings")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        status_bar = ttk.Label(
            self, textvariable=self.status_var, relief="sunken", anchor="w")
        status_bar.pack(fill="x", side="bottom")

        self.refresh_all()
        self.apply_theme()

    @property
    def pack(self) -> Songpack:
        return self.pack_data

    def set_status(self, text: str):
        self.status_var.set(text)

    def refresh_all(self):
        self.info_tab.push_from_pack()
        self.library_tab.refresh_tree()
        self.priority_tab.refresh()
        self.settings_tab.refresh()

    def _on_tab_changed(self, _event=None):
        self.info_tab.pull_into_pack()
        self.priority_tab.refresh()
        self.library_tab.refresh_tree(keep_selection=True)

    def on_entry_conditions_changed(self, _entry: Entry):
        self.library_tab.refresh_tree(keep_selection=True)
        self.priority_tab.refresh()

    # -- target mod build -------------------------------------------
    def effective_mod_version(self):
        """The mod version this songpack is aimed at, or None when no
        target has been chosen (in which case nothing is restricted).
        """
        version, _explanation = mod_versions.resolve(
            self.pack_data.minecraft_version, self.pack_data.mod_version)
        return version

    def on_target_changed(self):
        """The Minecraft/mod version picker moved, so the condition editor
        has to re-gate itself against the new target.
        """
        lib = self.library_tab
        ids = set(lib.selected_entry_ids)
        entries = [e for e in self.pack_data.entries if e.id in ids]
        if lib.editor_outer.winfo_ismapped():
            if len(entries) == 1:
                lib._build_editor_for(entries[0])
            elif len(entries) > 1:
                lib._build_multi_editor_for(entries)

        version = self.effective_mod_version()
        problems = mod_versions.validate_pack(self.pack_data, version)
        if not version:
            self.set_status(
                "No target build set — all documented conditions are available.")
        elif problems:
            self.set_status(
                f"Targeting Reactive Music {version}. "
                f"{len(problems)} entry/entries use conditions this build doesn't have "
                "(you'll be warned again on save).")
        else:
            self.set_status(f"Targeting Reactive Music {version}.")

    # -- settings -------------------------------------------------
    def apply_theme(self):
        """Apply the current persisted light/dark preference via CustomTkinter."""
        ctk.set_appearance_mode(
            "dark" if self.settings.get("dark_theme", True) else "light")

    def save_settings(self):
        try:
            app_settings.save(self.settings)
        except OSError as exc:
            messagebox.showerror(
                "Settings", f"Could not save settings:\n{exc}")

    def on_biome_colors_changed(self):
        """A biome/tag colour or definition changed in the Settings tab, so
        the condition editor's biome list needs redrawing.
        """
        lib = self.library_tab
        ids = set(lib.selected_entry_ids)
        entries = [e for e in self.pack_data.entries if e.id in ids]
        if len(entries) == 1 and lib.editor_outer.winfo_ismapped():
            lib._build_editor_for(entries[0])

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
        self.biome_custom_biomes = {}
        self.biome_custom_tags = {}
        self.refresh_all()
        self.set_status(
            "Started a new, empty songpack. Set its Minecraft version in Songpack Info "
            "so the editor can match the conditions to your mod build.")

    def action_load_config(self):
        path = filedialog.askdirectory(
            title="Select the songpack folder (containing ReactiveMusic.yaml)")
        if not path:
            return
        try:
            self.pack_data = yaml_io.load_songpack(path)
            biomes, tags = biome_customization.load(path)
            mod_versions.apply_to_pack(self.pack_data, mod_versions.load(path))
        except Exception as exc:  # noqa: BLE001 - surface any load error to the user
            messagebox.showerror("Load failed", str(exc))
            return
        self.biome_custom_biomes = biomes
        self.biome_custom_tags = tags
        self.current_save_folder = path
        self.refresh_all()
        version = self.effective_mod_version()
        target = f", targeting Reactive Music {version}" if version else ""
        self.set_status(
            f"Loaded {len(self.pack_data.entries)} entries from {path}{target}")

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
        if not self._confirm_target_problems():
            return
        folder = filedialog.askdirectory(
            title="Choose (or create) a folder to save this songpack into")
        if not folder:
            return
        try:
            path = yaml_io.save_songpack(
                self.pack_data, folder, copy_music_from=None)
            biome_customization.save(
                folder, self.biome_custom_biomes, self.biome_custom_tags)
            mod_versions.save(folder, self.pack_data)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.current_save_folder = folder
        self.set_status(f"Saved to {path}")
        messagebox.showinfo(
            "Saved",
            f"Songpack saved to:\n{path}\n\n"
            f"Biome customization saved to:\n"
            f"{os.path.join(folder, biome_customization.CONFIG_FILENAME)}\n\n"
            f"Target build saved to:\n"
            f"{os.path.join(folder, mod_versions.TARGET_FILENAME)}",
        )

    def _confirm_target_problems(self) -> bool:
        """If any entry uses a condition the target mod build predates,
        list them and let the user decide. Saving is still allowed --
        the target is the user's own note, not a hard rule.
        """
        problems = mod_versions.validate_pack(
            self.pack_data, self.effective_mod_version())
        if not problems:
            return True
        shown = "\n".join(problems[:12])
        if len(problems) > 12:
            shown += f"\n… and {len(problems) - 12} more"
        return messagebox.askyesno(
            "Conditions newer than your target build",
            f"These entries use conditions that Reactive Music "
            f"{self.effective_mod_version()} doesn't support:\n\n{shown}\n\n"
            "They will be written to the YAML as-is and older mod builds will ignore "
            "or fail to load them.\n\nSave anyway?",
        )

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
