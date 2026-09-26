"""
settings_tab.py
----------------
Tab 4: "Settings".

Editor preferences are global and persist in ~/.rm-songpack-maker/settings.json.
Biome / biome-tag text colours belong to the current songpack and are written
to biome_customization.json when the songpack is saved.

The editor's bundled biome defaults are intentionally read-only here. They
are project data rather than a user-facing setting, so the Settings tab no
longer exposes controls for changing or committing them.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
import customtkinter as ctk

import biome_customization
import biome_tag_platforms
import constants as C
import simulation
import theme


class SettingsTab(ctk.CTkFrame):
    def __init__(self, parent, app: "App"):  # noqa: F821
        super().__init__(parent)
        self.app = app

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=10, pady=10)

        # ---- editor preferences ------------------------------------------
        prefs = ctk.CTkFrame(body)
        prefs.pack(fill="x")

        ctk.CTkLabel(
            prefs, text="Editor preferences", font=("", 14, "bold")
        ).pack(anchor="w", padx=12, pady=(10, 4))

        self.double_click_var = tk.BooleanVar(
            value=bool(app.settings.get("double_click_preview", False)))
        ctk.CTkSwitch(
            prefs,
            text="Double-click a song in the list to play/pause its preview",
            variable=self.double_click_var,
            command=self._on_double_click_toggled,
        ).pack(anchor="w", padx=12, pady=(6, 4))

        self.dark_var = tk.BooleanVar(
            value=bool(app.settings.get("dark_theme", True)))
        ctk.CTkSwitch(
            prefs,
            text="Use dark theme",
            variable=self.dark_var,
            command=self._on_theme_toggled,
        ).pack(anchor="w", padx=12, pady=4)

        self.show_empty_tags_var = tk.BooleanVar(
            value=bool(app.settings.get("show_empty_biome_tags", False)))
        ctk.CTkSwitch(
            prefs,
            text="Show biome tags with no known biomes on the tag map",
            variable=self.show_empty_tags_var,
            command=self._on_show_empty_tags_toggled,
        ).pack(anchor="w", padx=12, pady=4)

        self.pool_overlaps_var = tk.BooleanVar(
            value=bool(app.settings.get("pool_overlapping_biomes", True)))
        ctk.CTkSwitch(
            prefs,
            text="When saving, pool the songs of entries that overlap on the same biomes",
            variable=self.pool_overlaps_var,
            command=self._on_pool_overlaps_toggled,
        ).pack(anchor="w", padx=12, pady=4)

        self.expand_time_var = tk.BooleanVar(
            value=bool(app.settings.get("expand_time_agnostic_songs", True)))
        ctk.CTkSwitch(
            prefs,
            text="When saving, expand place-conditioned songs with no time into per-time pools",
            variable=self.expand_time_var,
            command=self._on_expand_time_toggled,
        ).pack(anchor="w", padx=12, pady=4)

        ctk.CTkLabel(
            prefs,
            text=("Saved to your user profile, so they apply to every songpack and every "
                  "time you open the editor."),
            text_color=("gray40", "gray70"),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(2, 10))

        # ---- biome colours -----------------------------------------------
        colors = ttk.LabelFrame(
            body, text="Biome / biome-tag text colors (saved with this songpack)")
        colors.pack(fill="both", expand=True, pady=(10, 0))

        ttk.Label(
            colors,
            text=("These colors are only used by this editor to make biome conditions easier to scan; "
                  "ReactiveMusic ignores them.\n"
                  f"'Change color…' saves to this songpack only ({biome_customization.CONFIG_FILENAME}, "
                  "written when you save it)."),
            style="Muted.TLabel", justify="left",
        ).pack(anchor="w", padx=8, pady=(8, 4))

        filter_row = ttk.Frame(colors)
        filter_row.pack(fill="x", padx=8)
        ttk.Label(filter_row, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(filter_row, textvariable=self.filter_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0))
        ttk.Button(
            filter_row, text="✕", width=2,
            command=lambda: self.filter_var.set(""),
        ).pack(side="left", padx=(2, 0))
        self.filter_var.trace_add("write", lambda *_: self.refresh())

        tree_wrap = ttk.Frame(colors)
        tree_wrap.pack(fill="both", expand=True, padx=8, pady=(6, 0))

        columns = ("name", "kind", "origin", "color_from", "color")
        self.tree = ttk.Treeview(
            tree_wrap, columns=columns, show="headings", selectmode="browse", height=12)
        for key, text, width, anchor in (
            ("name", "Biome / tag", 240, "w"),
            ("kind", "Used as", 100, "w"),
            ("origin", "Name is", 90, "center"),
            ("color_from", "Color set by", 130, "center"),
            ("color", "Color", 90, "center"),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor)
        self.tree.pack(side="left", fill="both", expand=True)
        vscroll = ttk.Scrollbar(
            tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vscroll.set)
        vscroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._change_color())

        btns = ttk.Frame(colors)
        btns.pack(fill="x", padx=8, pady=(8, 8))
        ttk.Button(
            btns, text="Change color… (this songpack)",
            command=self._change_color,
        ).pack(side="left", padx=2)
        ttk.Button(
            btns, text="Reset to default",
            command=self._reset_color,
        ).pack(side="left", padx=2)
        ttk.Button(
            btns, text="Add custom biome/tag…",
            command=self._add_custom,
        ).pack(side="left", padx=2)
        ttk.Button(
            btns, text="Delete custom",
            command=self._delete_custom,
        ).pack(side="left", padx=2)
        ttk.Button(
            btns, text="Biome tag groups…",
            command=self._open_tag_groups,
        ).pack(side="left", padx=2)

        self.refresh()

    # -- biome tag groups --------------------------------------------------
    def _open_tag_groups(self):
        """Edit named bundles of BIOMETAG= conditions stored with this songpack.

        Groups are an editor convenience only. Entries keep ordinary
        BIOMETAG= conditions, so changing a group definition never rewrites
        existing entries that previously used it.
        """
        groups = self.app.biome_custom_tag_groups
        tags = biome_customization.all_tag_names(
            self.app.biome_custom_tag_members,
            self.app.biome_custom_tags,
        )
        tags = list(dict.fromkeys(
            tags + [tag for members in groups.values() for tag in members]
        ))

        window = ctk.CTkToplevel(self)
        window.title("Biome tag groups")
        window.geometry("720x560")
        window.transient(self.app)
        window.after(100, lambda: window.winfo_exists() and window.grab_set())

        body = ctk.CTkFrame(window, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=12, pady=12)

        left = ctk.CTkFrame(body)
        left.pack(side="left", fill="y", padx=(0, 8))
        ctk.CTkLabel(
            left, text="Groups", font=("", 14, "bold")
        ).pack(anchor="w", padx=10, pady=(8, 4))
        group_list = tk.Listbox(left, width=24, exportselection=False)
        group_list.pack(fill="y", expand=True, padx=8, pady=(0, 8))

        right = ctk.CTkFrame(body)
        right.pack(side="left", fill="both", expand=True)

        name_var = tk.StringVar()
        ctk.CTkLabel(right, text="Group name:").pack(
            anchor="w", padx=10, pady=(8, 2))
        ctk.CTkEntry(
            right, textvariable=name_var, width=260
        ).pack(anchor="w", padx=10, pady=(0, 6))

        ctk.CTkLabel(
            right, text="Biome tags in this group:", anchor="w"
        ).pack(fill="x", padx=10)
        tag_frame = ctk.CTkScrollableFrame(right)
        tag_frame.pack(fill="both", expand=True, padx=8, pady=4)

        tag_vars = {}
        for tag in sorted(tags, key=str.lower):
            var = tk.BooleanVar()
            tag_vars[tag] = var
            ctk.CTkCheckBox(
                tag_frame, text=tag, variable=var
            ).pack(anchor="w", padx=4, pady=1)

        current = {"name": None}

        def reload_list():
            group_list.delete(0, "end")
            for name in sorted(groups, key=str.lower):
                group_list.insert("end", f"{name}  ({len(groups[name])})")

        def load_group(name):
            current["name"] = name
            name_var.set(name or "")
            selected = set(groups.get(name, [])) if name else set()
            for tag, var in tag_vars.items():
                var.set(tag in selected)

        def on_select(_event=None):
            selection = group_list.curselection()
            if selection:
                names = sorted(groups, key=str.lower)
                load_group(names[selection[0]])

        def refresh_after_group_change():
            reload_list()
            self.app.on_biome_colors_changed()

        def save_group():
            name = name_var.get().strip()
            chosen = [
                tag for tag in sorted(tag_vars, key=str.lower)
                if tag_vars[tag].get()
            ]
            if not name or not chosen:
                messagebox.showwarning(
                    "Biome tag group",
                    "Give the group a name and select at least one biome tag.",
                    parent=window,
                )
                return
            old = current["name"]
            if name != old and name in groups:
                messagebox.showwarning(
                    "Biome tag group",
                    "A group with that name already exists.",
                    parent=window,
                )
                return
            if old and old != name:
                groups.pop(old, None)
            groups[name] = chosen
            current["name"] = name
            refresh_after_group_change()
            self.app.set_status(
                f"Saved biome tag group '{name}' ({len(chosen)} tags). "
                "Save the songpack to keep it."
            )

        def delete_group():
            name = current["name"]
            if not name or name not in groups:
                return
            if not messagebox.askyesno(
                "Delete biome tag group",
                f"Delete the group '{name}'? Existing entries keep their tags.",
                parent=window,
            ):
                return
            groups.pop(name, None)
            load_group(None)
            refresh_after_group_change()

        group_list.bind("<<ListboxSelect>>", on_select)

        buttons = ctk.CTkFrame(right, fg_color="transparent")
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(
            buttons, text="New", width=80, **theme.NEUTRAL_BUTTON,
            command=lambda: (
                group_list.selection_clear(0, "end"),
                load_group(None),
            ),
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            buttons, text="Delete", width=90, **theme.DANGER_BUTTON,
            command=delete_group,
        ).pack(side="right", padx=4)
        ctk.CTkButton(
            buttons, text="Save group", width=110,
            command=save_group,
        ).pack(side="right", padx=4)

        window.bind("<Escape>", lambda _e: window.destroy())
        reload_list()

    # -- preference handlers -------------------------------------------------
    def _on_double_click_toggled(self):
        self.app.settings["double_click_preview"] = bool(
            self.double_click_var.get())
        self.app.save_settings()
        self.app.set_status(
            "Double-click preview turned %s." %
            ("on" if self.double_click_var.get() else "off"))

    def _on_theme_toggled(self):
        self.app.settings["dark_theme"] = bool(self.dark_var.get())
        self.app.save_settings()
        self.app.apply_theme()
        self.refresh()
        self.app.set_status(
            "Switched to the %s theme." %
            ("dark" if self.dark_var.get() else "light"))

    def _on_show_empty_tags_toggled(self):
        self.app.settings["show_empty_biome_tags"] = bool(
            self.show_empty_tags_var.get())
        self.app.save_settings()
        library_chart = getattr(self.app.library_tab, "biome_map", None)
        if library_chart is not None and library_chart.winfo_exists():
            library_chart.redraw()
        simulator_chart = getattr(self.app.simulator_tab, "chart", None)
        if simulator_chart is not None and simulator_chart.winfo_exists():
            simulator_chart.redraw()
        self.app.set_status(
            "Empty biome tags turned %s on the tag map." %
            ("on" if self.show_empty_tags_var.get() else "off"))

    def _on_pool_overlaps_toggled(self):
        self.app.settings["pool_overlapping_biomes"] = bool(
            self.pool_overlaps_var.get())
        self.app.save_settings()
        self.app.set_status(
            "Biome pooling on save turned %s. It takes effect the next time "
            "you save." %
            ("on" if self.pool_overlaps_var.get() else "off"))

    def _on_expand_time_toggled(self):
        self.app.settings["expand_time_agnostic_songs"] = bool(
            self.expand_time_var.get())
        self.app.save_settings()
        self.app.set_status(
            "Time-agnostic song expansion on save turned %s. It takes effect "
            "the next time you save." %
            ("on" if self.expand_time_var.get() else "off"))

    # -- biome colour list -------------------------------------------------
    def _store(self, is_tag: bool) -> dict:
        return self.app.biome_custom_tags if is_tag else self.app.biome_custom_biomes

    @staticmethod
    def _builtins(is_tag: bool):
        return C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES

    def _rows(self):
        query = self.filter_var.get().strip().lower()
        for is_tag in (False, True):
            builtins = self._builtins(is_tag)
            custom = self._store(is_tag)
            names = list(builtins) + sorted(n for n in custom if n not in builtins)
            for name in names:
                if query and query not in name.lower():
                    continue
                if name in custom:
                    color = custom[name]
                    color_from = "This songpack"
                elif biome_customization.is_bundled_default(name, is_tag):
                    color = biome_customization.default_color(name, is_tag)
                    color_from = "App default"
                elif is_tag and biome_customization.tag_members(
                        name, self.app.biome_custom_tag_members):
                    # Tags carry a biome list, not a colour: averaged from it.
                    color = self.app.library_tab._biome_color(name, True)
                    color_from = "Avg. of biomes"
                else:
                    color = biome_customization.default_color(name, is_tag)
                    color_from = "Automatic"
                yield name, is_tag, name not in builtins, color, color_from

    def refresh(self):
        if not hasattr(self, "tree"):
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for name, is_tag, is_custom_name, color, color_from in self._rows():
            iid = ("tag:" if is_tag else "biome:") + name
            tag = "fg" + color.replace("#", "")
            self.tree.tag_configure(tag, foreground=color)
            self.tree.insert(
                "", "end", iid=iid, tags=(tag,),
                values=(
                    name,
                    "BIOMETAG=" if is_tag else "BIOME=",
                    "Custom" if is_custom_name else "Built-in",
                    color_from,
                    color,
                ),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
            self.tree.see(selected[0])

    def _selection(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(
                "Biome colors", "Select a biome or biome tag in the list first.")
            return None
        iid = sel[0]
        is_tag = iid.startswith("tag:")
        name = iid.split(":", 1)[1]
        return name, is_tag, name not in self._builtins(is_tag)

    def _apply_color(self, name: str, is_tag: bool, color: str | None):
        store = self._store(is_tag)
        if color is None:
            store.pop(name, None)
        else:
            store[name] = color
        self.refresh()
        self.app.on_biome_colors_changed()

    def _change_color(self):
        selection = self._selection()
        if not selection:
            return
        name, is_tag, _ = selection
        current = self.app.library_tab._biome_color(name, is_tag)
        result = colorchooser.askcolor(
            color=current, parent=self, title=f"Text color for {name}")
        if not result[1]:
            return
        self._apply_color(name, is_tag, result[1].lower())
        self.app.set_status(
            f"'{name}' will now be shown in {result[1].lower()}. "
            "Save the songpack to keep this color.")

    def _reset_color(self):
        selection = self._selection()
        if not selection:
            return
        name, is_tag, is_custom = selection
        if is_custom:
            # Keep the custom definition, just drop the colour override.
            self._apply_color(
                name, is_tag, biome_customization.default_color(name, is_tag))
        else:
            self._apply_color(name, is_tag, None)
        self.app.set_status(f"'{name}' reset to its automatic color.")

    def _delete_custom(self):
        selection = self._selection()
        if not selection:
            return
        name, is_tag, is_custom = selection
        if not is_custom:
            messagebox.showinfo(
                "Delete custom",
                f"'{name}' is one of ReactiveMusic's known values, so it can't be deleted. "
                "Use 'Reset to default' to drop its custom color instead.")
            return
        in_use = sum(
            1 for e in self.app.pack.entries
            for b in e.biomes if b.value == name and b.is_tag == is_tag
        )
        message = f"Delete the custom {'biome tag' if is_tag else 'biome'} '{name}'?"
        if in_use:
            message += (
                f"\n\nIt is currently used by {in_use} entry/entries. Those conditions "
                "are kept as-is; only the definition and its color are removed."
            )
        if not messagebox.askyesno("Delete custom", message):
            return
        self._apply_color(name, is_tag, None)
        self.app.set_status(f"Deleted custom definition '{name}'.")

    def _add_custom(self):
        window = tk.Toplevel(self)
        window.title("Add Custom Biome / Biome Tag")
        window.resizable(False, False)
        window.transient(self.app)
        window.grab_set()

        body = ttk.Frame(window)
        body.pack(padx=14, pady=14)
        name_var = tk.StringVar()
        type_var = tk.StringVar(value="Biome")
        color_var = tk.StringVar(
            value=biome_customization.default_color("custom"))

        ttk.Label(body, text="Name / identifier:").grid(
            row=0, column=0, padx=6, pady=5, sticky="e")
        name_entry = ttk.Entry(body, textvariable=name_var, width=34)
        name_entry.grid(row=0, column=1, columnspan=2, padx=2, pady=5)
        name_entry.focus_set()

        ttk.Label(body, text="Type:").grid(
            row=1, column=0, padx=6, pady=5, sticky="e")
        ttk.Combobox(
            body, textvariable=type_var, values=("Biome", "Biome Tag"),
            state="readonly", width=14,
        ).grid(row=1, column=1, padx=2, pady=5, sticky="w")

        ttk.Label(body, text="Text color:").grid(
            row=2, column=0, padx=6, pady=5, sticky="e")
        swatch = tk.Label(
            body, text="        ", bg=color_var.get(), relief="sunken")
        swatch.grid(row=2, column=1, padx=2, pady=5, sticky="w")

        def pick():
            result = colorchooser.askcolor(
                color=color_var.get(), parent=window, title="Biome text color")
            if result[1]:
                color_var.set(result[1].lower())
                swatch.configure(bg=result[1].lower())

        ttk.Button(body, text="Choose…", command=pick).grid(
            row=2, column=2, padx=4, pady=5)

        tag_label = ttk.Label(body, text="Add to tags (optional):")
        tag_label.grid(row=3, column=0, padx=6, pady=5, sticky="ne")
        tag_listbox = tk.Listbox(
            body, selectmode="multiple", height=7, exportselection=False)
        tag_listbox.grid(
            row=3, column=1, columnspan=2, padx=2, pady=5, sticky="ew")
        available_tags = list(dict.fromkeys(
            [t for t in C.COMMON_BIOME_TAGS
             if biome_tag_platforms.tag_available(
                 t, self.app.pack.platform, self.app.pack.minecraft_version)]
            + sorted(self.app.biome_custom_tags)
        ))
        for tag in available_tags:
            tag_listbox.insert("end", tag)

        def _on_type_changed(*_args):
            state = "normal" if type_var.get() == "Biome" else "disabled"
            tag_listbox.configure(state=state)
            tag_label.configure(state=state)

        type_var.trace_add("write", _on_type_changed)
        _on_type_changed()

        def add():
            name = name_var.get().strip()
            is_tag = type_var.get() == "Biome Tag"
            color = color_var.get().strip().lower()
            if not name:
                messagebox.showwarning(
                    "Custom biome", "Enter a name.", parent=window)
                return
            if name in self._builtins(is_tag) or name in self._store(is_tag):
                messagebox.showwarning(
                    "Custom biome", "That name already exists.", parent=window)
                return
            if not biome_customization.valid_color(color):
                messagebox.showwarning(
                    "Custom biome", "Choose a valid text color.", parent=window)
                return
            chosen = (
                [available_tags[i] for i in tag_listbox.curselection()]
                if not is_tag else []
            )
            if not is_tag:
                for tag in chosen:
                    members = self.app.biome_custom_tag_members.setdefault(tag, [])
                    if name not in members:
                        members.append(name)
                if chosen:
                    simulation.set_custom_tag_members(
                        self.app.biome_custom_tag_members)
            window.destroy()
            self._apply_color(name, is_tag, color)
            if not is_tag:
                self.app.mark_dirty()
            self.filter_var.set(name)
            extra = f" Added to {len(chosen)} tag(s)." if chosen else ""
            self.app.set_status(
                f"Added custom {'biome tag' if is_tag else 'biome'} '{name}'."
                f"{extra} It is now available in the biome picker; save the songpack "
                "to keep this definition.")

        ttk.Button(body, text="Cancel", command=window.destroy).grid(
            row=4, column=1, padx=4, pady=(8, 0), sticky="e")
        ttk.Button(body, text="Add", command=add).grid(
            row=4, column=2, padx=4, pady=(8, 0), sticky="e")
        window.bind("<Return>", lambda _e: add())
        window.bind("<Escape>", lambda _e: window.destroy())
