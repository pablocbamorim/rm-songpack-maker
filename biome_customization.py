from __future__ import annotations

import colorsys
import json
import os
import tempfile
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

CONFIG_FILENAME = "biome_customization.json"


def default_color(name: str, is_tag: bool = False) -> str:
    """Return a deterministic readable color for built-in biome names."""
    hue = (sum((i + 1) * ord(c) for i, c in enumerate(name)) % 360) / 360.0
    saturation = 0.62 if is_tag else 0.58
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, 0.92)
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
    try:
        with open(os.path.join(folder, CONFIG_FILENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}

    def clean(value):
        if not isinstance(value, dict):
            return {}
        return {
            str(k): str(v).lower()
            for k, v in value.items()
            if _valid_color(v)
        }

    return clean(data.get("biomes", {})), clean(data.get("biome_tags", {}))


def _save(folder: str, biomes: dict[str, str], tags: dict[str, str]):
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, CONFIG_FILENAME)
    fd, tmp = tempfile.mkstemp(
        prefix=".biome_customization_", suffix=".tmp", dir=folder
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": 1,
                    "biomes": dict(sorted(biomes.items(), key=lambda x: x[0].lower())),
                    "biome_tags": dict(sorted(tags.items(), key=lambda x: x[0].lower())),
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install() -> None:
    """Install biome support before App() is constructed.

    The previous implementation patched an already-created App instance.
    That was too late for LibraryTab's widgets and, importantly, the File
    menu had already captured the original action callbacks.  This installer
    patches the classes first, so normal App construction creates the correct
    editor and menu callbacks from the start.
    """
    import app as app_module
    import constants as C
    import yaml_io
    from models import Songpack

    App = app_module.App
    LibraryTab = app_module.LibraryTab

    if getattr(App, "_biome_customization_installed", False):
        return

    original_app_init = App.__init__
    original_load = App.action_load_config
    original_save = App.action_save_config
    original_new = App.action_new_songpack
    original_available = LibraryTab._available_biome_values
    original_build = LibraryTab._build_editor_for

    def app_init(self, *args, **kwargs):
        self.biome_custom_biomes = {}
        self.biome_custom_tags = {}
        original_app_init(self, *args, **kwargs)

    def available(self, entry, is_tag: bool):
        builtins = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
        custom = self.app.biome_custom_tags if is_tag else self.app.biome_custom_biomes
        used = {b.value for b in entry.biomes if b.is_tag == is_tag}
        return [v for v in [*builtins, *custom] if v not in used]

    def recolor_listbox(self):
        listbox = getattr(self, "biome_listbox", None)
        if listbox is None:
            return
        for i, condition in enumerate(self.app.pack.entries[
            next((idx for idx, e in enumerate(self.app.pack.entries)
                 if e.id == self.selected_entry_id), -1)
        ].biomes if self.selected_entry_id and any(
            e.id == self.selected_entry_id for e in self.app.pack.entries
        ) else []):
            custom = (
                self.app.biome_custom_tags
                if condition.is_tag
                else self.app.biome_custom_biomes
            )
            listbox.itemconfig(
                i,
                foreground=custom.get(
                    condition.value,
                    default_color(condition.value, condition.is_tag),
                ),
            )

    def build(self, entry):
        self._available_biome_values = available.__get__(self, LibraryTab)
        original_build(self, entry)

        row1 = self.biome_combobox.master
        ttk.Button(
            row1,
            text="Add custom…",
            command=lambda: self._open_custom_biome_dialog(),
        ).pack(side="left", padx=4)

        # Listbox items support per-item foreground colors.  Reapply this on
        # every rebuild because _build_editor_for recreates the Listbox.
        for index, condition in enumerate(entry.biomes):
            custom = (
                self.app.biome_custom_tags
                if condition.is_tag
                else self.app.biome_custom_biomes
            )
            self.biome_listbox.itemconfig(
                index,
                foreground=custom.get(
                    condition.value,
                    default_color(condition.value, condition.is_tag),
                ),
            )

    def open_custom_biome_dialog(self):
        window = tk.Toplevel(self)
        window.title("Add Custom Biome / Biome Tag")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()

        body = ttk.Frame(window)
        body.pack(padx=14, pady=14)
        name_var = tk.StringVar()
        type_var = tk.StringVar(value="Biome")
        color_var = tk.StringVar(value="#66ccff")

        ttk.Label(body, text="Name / identifier:").grid(
            row=0, column=0, padx=6, pady=5
        )
        ttk.Entry(body, textvariable=name_var, width=34).grid(
            row=0, column=1, columnspan=2, padx=2, pady=5
        )
        ttk.Label(body, text="Type:").grid(row=1, column=0, padx=6, pady=5)
        ttk.Combobox(
            body,
            textvariable=type_var,
            values=("Biome", "Biome Tag"),
            state="readonly",
            width=14,
        ).grid(row=1, column=1, padx=2, pady=5, sticky="w")
        ttk.Label(body, text="Text color:").grid(row=2, column=0, padx=6, pady=5)
        swatch = tk.Label(
            body, text="        ", bg=color_var.get(), relief="sunken"
        )
        swatch.grid(row=2, column=1, padx=2, pady=5, sticky="w")

        def pick():
            result = colorchooser.askcolor(
                color=color_var.get(), parent=window, title="Biome text color"
            )
            if result[1]:
                color = result[1].lower()
                color_var.set(color)
                swatch.configure(bg=color)

        ttk.Button(body, text="Choose…", command=pick).grid(
            row=2, column=2, padx=4, pady=5
        )

        def add():
            name = name_var.get().strip()
            is_tag = type_var.get() == "Biome Tag"
            color = color_var.get().strip().lower()
            builtins = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
            custom = (
                self.app.biome_custom_tags
                if is_tag
                else self.app.biome_custom_biomes
            )
            if not name:
                messagebox.showwarning(
                    "Custom biome", "Enter a name.", parent=window
                )
                return
            if name in builtins or name in custom:
                messagebox.showwarning(
                    "Custom biome", "That name already exists.", parent=window
                )
                return
            if not _valid_color(color):
                messagebox.showwarning(
                    "Custom biome", "Choose a valid text color.", parent=window
                )
                return
            custom[name] = color
            window.destroy()
            entry = next(
                (e for e in self.app.pack.entries
                 if e.id == self.selected_entry_id),
                None,
            )
            if entry is not None:
                self._build_editor_for(entry)
            self.app.set_status(
                f"Added custom {'biome tag' if is_tag else 'biome'} '{name}'. "
                "Save the songpack to keep this definition."
            )

        ttk.Button(
            body, text="Cancel", command=window.destroy
        ).grid(row=3, column=1, padx=4, pady=(8, 0), sticky="e")
        ttk.Button(
            body, text="Add", command=add
        ).grid(row=3, column=2, padx=4, pady=(8, 0), sticky="e")
        window.bind("<Return>", lambda _e: add())
        window.bind("<Escape>", lambda _e: window.destroy())

    def load_config(self):
        path = filedialog.askdirectory(
            title="Select the songpack folder (containing ReactiveMusic.yaml)"
        )
        if not path:
            return
        try:
            self.pack_data = yaml_io.load_songpack(path)
            biomes, tags = _load(path)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc), parent=self)
            return
        self.biome_custom_biomes = biomes
        self.biome_custom_tags = tags
        self.current_save_folder = path
        self.refresh_all()
        self.set_status(
            f"Loaded {len(self.pack_data.entries)} entries and biome customization from {path}"
        )

    def save_config(self):
        self.info_tab.pull_into_pack()
        if not self.pack_data.entries:
            if not messagebox.askyesno(
                "Save Config",
                "This songpack has no entries yet. Save anyway?",
                parent=self,
            ):
                return
        folder = filedialog.askdirectory(
            title="Choose (or create) a folder to save this songpack into"
        )
        if not folder:
            return
        try:
            path = yaml_io.save_songpack(
                self.pack_data, folder, copy_music_from=None
            )
            _save(folder, self.biome_custom_biomes, self.biome_custom_tags)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        self.current_save_folder = folder
        self.set_status(
            f"Saved songpack and biome customization to {folder}"
        )
        messagebox.showinfo(
            "Saved",
            f"Songpack saved to:\n{path}\n\n"
            f"Biome customization saved to:\n"
            f"{os.path.join(folder, CONFIG_FILENAME)}",
            parent=self,
        )

    def new_songpack(self):
        if not messagebox.askyesno(
            "New Songpack",
            "Discard the current songpack and start a new one?",
            parent=self,
        ):
            return
        self.pack_data = Songpack()
        self.music_source_folder = None
        self.current_save_folder = None
        self.biome_custom_biomes.clear()
        self.biome_custom_tags.clear()
        self.refresh_all()
        self.set_status("Started a new, empty songpack.")

    App.__init__ = app_init
    App.action_load_config = load_config
    App.action_save_config = save_config
    App.action_new_songpack = new_songpack

    LibraryTab._available_biome_values = available
    LibraryTab._build_editor_for = build
    LibraryTab._open_custom_biome_dialog = open_custom_biome_dialog

    App._biome_customization_installed = True
