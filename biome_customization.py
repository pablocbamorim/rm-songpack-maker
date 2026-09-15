from __future__ import annotations

import colorsys
import json
import os
import tempfile
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from types import MethodType

CONFIG_FILENAME = "biome_customization.json"


def default_color(name: str, is_tag: bool = False) -> str:
    """Return a deterministic, readable color for a biome/biome-tag name."""
    hue = (sum((i + 1) * ord(c) for i, c in enumerate(name)) % 360) / 360.0
    saturation = 0.62 if is_tag else 0.58
    value = 0.92
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return "#%02x%02x%02x" % (
        round(r * 255), round(g * 255), round(b * 255)
    )


def _valid_color(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def _load(folder: str):
    path = os.path.join(folder, CONFIG_FILENAME)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}, {}

    if not isinstance(data, dict):
        return {}, {}

    biomes = data.get("biomes", {})
    tags = data.get("biome_tags", {})
    if not isinstance(biomes, dict):
        biomes = {}
    if not isinstance(tags, dict):
        tags = {}

    return (
        {str(k): str(v).lower() for k, v in biomes.items() if _valid_color(v)},
        {str(k): str(v).lower() for k, v in tags.items() if _valid_color(v)},
    )


def _save(folder: str, biomes: dict[str, str], tags: dict[str, str]) -> None:
    """Atomically write the customization file into the songpack folder."""
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, CONFIG_FILENAME)
    fd, temp_path = tempfile.mkstemp(
        prefix=".biome_customization_", suffix=".tmp", dir=folder
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 1,
                    "biomes": dict(sorted(biomes.items(), key=lambda item: item[0].lower())),
                    "biome_tags": dict(sorted(tags.items(), key=lambda item: item[0].lower())),
                },
                handle,
                indent=2,
                ensure_ascii=False,
            )
            handle.write("\n")
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def install(app) -> None:
    """Install custom biome/tag support on the existing LibraryTab instance."""
    import constants as C

    library = app.library_tab
    builtin_biome_colors = {
        name: default_color(name, False) for name in C.COMMON_BIOMES
    }
    builtin_tag_colors = {
        name: default_color(name, True) for name in C.COMMON_BIOME_TAGS
    }
    custom_biomes: dict[str, str] = {}
    custom_tags: dict[str, str] = {}

    def catalog(is_tag: bool):
        base = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
        custom = custom_tags if is_tag else custom_biomes
        builtin = builtin_tag_colors if is_tag else builtin_biome_colors
        names = list(dict.fromkeys([*base, *custom]))
        colors = {
            name: custom.get(name, builtin.get(name, default_color(name, is_tag)))
            for name in names
        }
        return names, colors

    def available(self, entry, is_tag: bool):
        names, _ = catalog(is_tag)
        used = {condition.value for condition in entry.biomes if condition.is_tag == is_tag}
        return [name for name in names if name not in used]

    def recolor_listbox(self):
        listbox = getattr(self, "biome_listbox", None)
        entry_id = getattr(self, "selected_entry_id", None)
        if listbox is None or not entry_id:
            return
        entry = next((item for item in app.pack.entries if item.id == entry_id), None)
        if entry is None:
            return
        for index, condition in enumerate(entry.biomes):
            _, colors = catalog(condition.is_tag)
            listbox.itemconfig(
                index,
                foreground=colors.get(
                    condition.value, default_color(condition.value, condition.is_tag)
                ),
            )

    def open_add_dialog():
        window = tk.Toplevel(app)
        window.title("Add Custom Biome / Biome Tag")
        window.resizable(False, False)
        window.transient(app)
        window.grab_set()

        name_var = tk.StringVar()
        type_var = tk.StringVar(value="Biome")
        color_var = tk.StringVar(value="#66ccff")

        body = ttk.Frame(window)
        body.pack(padx=14, pady=14)

        ttk.Label(body, text="Name / identifier:").grid(
            row=0, column=0, padx=6, pady=5, sticky="e"
        )
        ttk.Entry(body, textvariable=name_var, width=34).grid(
            row=0, column=1, columnspan=2, padx=2, pady=5
        )

        ttk.Label(body, text="Type:").grid(
            row=1, column=0, padx=6, pady=5, sticky="e"
        )
        ttk.Combobox(
            body,
            textvariable=type_var,
            values=("Biome", "Biome Tag"),
            state="readonly",
            width=14,
        ).grid(row=1, column=1, padx=2, pady=5, sticky="w")

        ttk.Label(body, text="Text color:").grid(
            row=2, column=0, padx=6, pady=5, sticky="e"
        )
        swatch = tk.Label(
            body, text="        ", bg=color_var.get(), relief="sunken"
        )
        swatch.grid(row=2, column=1, padx=2, pady=5, sticky="w")

        def choose_color():
            result = colorchooser.askcolor(
                color=color_var.get(), parent=window, title="Biome text color"
            )
            if result[1]:
                color_var.set(result[1].lower())
                swatch.configure(bg=result[1])

        ttk.Button(body, text="Choose…", command=choose_color).grid(
            row=2, column=2, padx=4, pady=5
        )

        def add_custom():
            name = name_var.get().strip()
            color = color_var.get().strip().lower()
            is_tag = type_var.get() == "Biome Tag"
            custom = custom_tags if is_tag else custom_biomes
            builtin = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES

            if not name:
                messagebox.showwarning(
                    "Custom biome", "Enter a biome/biome-tag name.", parent=window
                )
                return
            if name in builtin:
                messagebox.showwarning(
                    "Custom biome",
                    "That name is already a built-in biome/biome-tag.",
                    parent=window,
                )
                return
            if not _valid_color(color):
                messagebox.showwarning(
                    "Custom biome", "Choose a valid text color.", parent=window
                )
                return

            custom[name] = color
            window.destroy()

            if library.selected_entry_id:
                entry = next(
                    (item for item in app.pack.entries
                     if item.id == library.selected_entry_id),
                    None,
                )
                if entry is not None:
                    library._build_editor_for(entry)
                    library.biome_search_var.set(name)
                    if is_tag:
                        library.biome_is_tag_var.set(True)
                        library.biome_combobox.configure(
                            values=library._available_biome_values(entry, True)
                        )
                    recolor_listbox()
            app.set_status(f"Added custom {'biome tag' if is_tag else 'biome'} '{name}'.")

        ttk.Button(body, text="Cancel", command=window.destroy).grid(
            row=3, column=1, padx=4, pady=(8, 0), sticky="e"
        )
        ttk.Button(body, text="Add", command=add_custom).grid(
            row=3, column=2, padx=4, pady=(8, 0), sticky="e"
        )
        window.bind("<Return>", lambda _event: add_custom())
        window.bind("<Escape>", lambda _event: window.destroy())

    original_build = library._build_editor_for

    def build(self, entry):
        # Replace the option provider with a correctly bound method. The old
        # implementation assigned a plain function to the instance, which is
        # easy to get wrong with Python's descriptor/binding rules.
        self._available_biome_values = MethodType(available, self)
        original_build(entry)

        # The original editor already exposes the exact row we want. Attach
        # the custom-definition button to that row rather than searching by
        # arbitrary child indexes.
        add_button_parent = self.biome_combobox.master
        if not any(
            isinstance(child, ttk.Button)
            and child.cget("text") == "Add custom…"
            for child in add_button_parent.winfo_children()
        ):
            ttk.Button(
                add_button_parent,
                text="Add custom…",
                command=open_add_dialog,
            ).pack(side="left", padx=4)

        recolor_listbox()

    library._build_editor_for = MethodType(build, library)

    original_load = app.action_load_config
    original_save = app.action_save_config
    original_new = app.action_new_songpack

    def load_config():
        before = app.current_save_folder
        original_load()
        folder = app.current_save_folder
        if folder and folder != before:
            custom_biomes.clear()
            custom_tags.clear()
            custom_biomes.update(_load(folder)[0])
            custom_tags.update(_load(folder)[1])
            if library.selected_entry_id:
                entry = next(
                    (item for item in app.pack.entries
                     if item.id == library.selected_entry_id),
                    None,
                )
                if entry is not None:
                    library._build_editor_for(entry)

    def save_config():
        # The core save action chooses the folder and updates current_save_folder.
        original_save()
        folder = app.current_save_folder
        if not folder:
            return
        try:
            _save(folder, custom_biomes, custom_tags)
        except OSError as exc:
            messagebox.showerror(
                "Biome customization",
                f"Could not save biome customization:\n{exc}",
                parent=app,
            )
            return
        app.set_status(
            f"Saved songpack and biome customization to {folder}"
        )

    def new_songpack():
        original_new()
        custom_biomes.clear()
        custom_tags.clear()

    app.action_load_config = load_config
    app.action_save_config = save_config
    app.action_new_songpack = new_songpack

    if app.current_save_folder:
        loaded_biomes, loaded_tags = _load(app.current_save_folder)
        custom_biomes.update(loaded_biomes)
        custom_tags.update(loaded_tags)
