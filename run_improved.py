"""Launch the Songpack Editor with the requested UI improvements.

Run this file instead of app.py. The original application remains untouched;
all changes are applied at runtime so the editor's data/YAML behavior is preserved.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import app
import condition_logic
import priority
import constants as C


def _warning(entry):
    return "⚠" if not entry.has_any_condition() else ""


def _smooth_scroll(widget, direction, amount=0.12):
    jobs = getattr(widget, "_smooth_scroll_jobs", {})
    widget._smooth_scroll_jobs = jobs
    old = jobs.get("y")
    if old:
        try:
            widget.after_cancel(old)
        except tk.TclError:
            pass
    start = widget.yview()[0]
    target = max(0.0, min(1.0, start + direction * amount))
    steps = 8

    def step(i=1):
        if i > steps:
            jobs.pop("y", None)
            return
        t = i / steps
        eased = t * t * (3 - 2 * t)
        widget.yview_moveto(start + (target - start) * eased)
        jobs["y"] = widget.after(12, step, i + 1)

    step()


def _bind_smooth(widget):
    def wheel(event):
        delta = getattr(event, "delta", 0)
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        elif delta:
            direction = -1 if delta > 0 else 1
        else:
            return "break"
        magnitude = abs(delta) / 120 if delta else 1
        _smooth_scroll(widget, direction, min(.28, max(.07, .10 * magnitude)))
        return "break"
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        widget.bind(sequence, wheel, add="+")


def patch_library(tab):
    tab._editor_collapsed = False
    tab._left = tab.tree.master
    tab._right = tab.editor_outer.master

    search_row = ttk.Frame(tab._left)
    search_row.pack(fill="x", pady=(6, 0), before=tab.tree)
    ttk.Label(search_row, text="Search music:").pack(side="left", padx=(2, 4))
    tab.music_search_var = tk.StringVar()
    search = ttk.Entry(search_row, textvariable=tab.music_search_var)
    search.pack(side="left", fill="x", expand=True)
    ttk.Button(search_row, text="Clear", command=lambda: tab.music_search_var.set("")).pack(side="left", padx=(4, 2))
    tab.music_search_var.trace_add("write", lambda *_: refresh_library(tab, True))
    search.bind("<Escape>", lambda _e: tab.music_search_var.set(""))

    tab.tree["columns"] = ("warning", "song", "summary", "score")
    tab.tree.heading("warning", text="")
    tab.tree.column("warning", width=28, minwidth=28, stretch=False, anchor="center")
    tab.tree.heading("song", text="Song")
    tab.tree.heading("summary", text="Conditions (preview)")
    tab.tree.heading("score", text="Rarity")

    tab.toggle_btn.pack_forget()
    bar = ttk.Frame(tab)
    bar.pack(fill="x", padx=8, pady=(4, 0), before=tab._left)
    tab._toggle_label = ttk.Label(bar, text="Conditions editor", font=("", 10, "bold"))
    tab._toggle_label.pack(side="left")
    ttk.Button(bar, text="▾ Hide editor", command=lambda: toggle_editor(tab)).pack(side="right")
    tab._toggle_bar = bar

    _bind_smooth(tab.tree)
    _bind_smooth(tab.canvas)

    original_build = tab._build_editor_for
    def build(entry):
        original_build(entry)
        refresh_biomes(tab, entry)
    tab._build_editor_for = build


def refresh_library(tab, keep_selection=False):
    previous = tab.selected_entry_id if keep_selection else None
    query = tab.music_search_var.get().strip().casefold()
    tab.tree.delete(*tab.tree.get_children())
    for entry in tab.app.pack.entries:
        if query and not any(query not in song.casefold() for song in entry.songs):
            pass
        elif query:
            continue
        tab.tree.insert("", "end", iid=entry.id, values=(
            _warning(entry), entry.display_name(), condition_logic.summarize_entry(entry), priority.score_entry(entry)
        ))
    if previous and tab.tree.exists(previous):
        tab.tree.selection_set(previous)


def refresh_biomes(tab, entry):
    is_tag = tab.biome_is_tag_var.get()
    source = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
    existing = {b.value.casefold() for b in entry.biomes if b.is_tag == is_tag}
    query = tab.biome_search_var.get().strip().casefold()
    tab.biome_combobox["values"] = [
        value for value in source
        if value.casefold() not in existing and (not query or query in value.casefold())
    ]
    tab.biome_combobox.set(tab.biome_search_var.get())


def toggle_editor(tab):
    if not tab._editor_collapsed:
        tab.editor_outer.pack_forget()
        tab._right.pack_forget()
        tab._left.pack_configure(side="left", fill="both", expand=True)
        tab._toggle_bar.winfo_children()[-1].configure(text="▸ Show editor")
        tab._editor_collapsed = True
    else:
        tab._left.pack_configure(side="left", fill="y", expand=False)
        tab._right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=8)
        tab.editor_outer.pack(fill="both", expand=True, pady=(6, 0))
        tab._toggle_bar.winfo_children()[-1].configure(text="▾ Hide editor")
        tab._editor_collapsed = False
        if tab.selected_entry_id:
            entry = next((e for e in tab.app.pack.entries if e.id == tab.selected_entry_id), None)
            if entry:
                tab._build_editor_for(entry)


def patch_priority(tab):
    tab.tree["columns"] = ("idx", "warning", "song", "score", "summary", "fallback")
    tab.tree.heading("warning", text="")
    tab.tree.column("warning", width=28, minwidth=28, stretch=False, anchor="center")
    _bind_smooth(tab.tree)

    def refresh():
        selected = tab.tree.selection()
        tab.tree.delete(*tab.tree.get_children())
        for i, entry in enumerate(tab.app.pack.entries, start=1):
            tab.tree.insert("", "end", iid=entry.id, values=(
                i, _warning(entry), entry.display_name(), priority.score_entry(entry),
                condition_logic.summarize_entry(entry), "yes" if entry.allow_fallback else "no"
            ))
        if selected and tab.tree.exists(selected[0]):
            tab.tree.selection_set(selected[0])
    tab.refresh = refresh


def main():
    original_library_init = app.LibraryTab.__init__
    original_priority_init = app.PriorityTab.__init__

    def library_init(self, parent, application):
        original_library_init(self, parent, application)
        patch_library(self)
    def priority_init(self, parent, application):
        original_priority_init(self, parent, application)
        patch_priority(self)

    app.LibraryTab.__init__ = library_init
    app.PriorityTab.__init__ = priority_init
    root = app.App()
    root.mainloop()


if __name__ == "__main__":
    main()
