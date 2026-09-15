from __future__ import annotations

import colorsys
import json
import os
import tempfile
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from types import MethodType

CONFIG_FILENAME = "biome_customization.json"


def default_color(name: str, is_tag: bool = False) -> str:
    hue = (sum((i + 1) * ord(c) for i, c in enumerate(name)) % 360) / 360.0
    saturation = 0.62 if is_tag else 0.58
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, 0.92)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


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
    fd, tmp = tempfile.mkstemp(prefix=".biome_customization_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "version": 1,
                "biomes": dict(sorted(biomes.items(), key=lambda x: x[0].lower())),
                "biome_tags": dict(sorted(tags.items(), key=lambda x: x[0].lower())),
            }, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def install(app) -> None:
    import constants as C
    import yaml_io
    from models import Songpack

    library = app.library_tab
    custom_biomes: dict[str, str] = {}
    custom_tags: dict[str, str] = {}

    def catalog(is_tag):
        builtins = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
        custom = custom_tags if is_tag else custom_biomes
        return list(dict.fromkeys([*builtins, *custom])), custom

    def available(self, entry, is_tag):
        names, _ = catalog(is_tag)
        used = {b.value for b in entry.biomes if b.is_tag == is_tag}
        return [n for n in names if n not in used]

    def refresh_editor(entry=None):
        if entry is None and library.selected_entry_id:
            entry = next((e for e in app.pack.entries
                          if e.id == library.selected_entry_id), None)
        if entry is not None:
            library._build_editor_for(entry)

    def recolor_listbox():
        lb = getattr(library, "biome_listbox", None)
        entry_id = getattr(library, "selected_entry_id", None)
        if lb is None or not entry_id:
            return
        entry = next((e for e in app.pack.entries if e.id == entry_id), None)
        if entry is None:
            return
        for i, condition in enumerate(entry.biomes):
            custom = custom_tags if condition.is_tag else custom_biomes
            color = custom.get(condition.value, default_color(condition.value, condition.is_tag))
            lb.itemconfig(i, foreground=color)

    def choose_color(parent, initial):
        result = colorchooser.askcolor(color=initial, parent=parent, title="Biome text color")
        return result[1].lower() if result[1] else None

    def add_custom_dialog():
        window = tk.Toplevel(app)
        window.title("Add Custom Biome / Biome Tag")
        window.resizable(False, False)
        window.transient(app)
        window.grab_set()

        body = ttk.Frame(window)
        body.pack(padx=14, pady=14)
        name_var = tk.StringVar()
        type_var = tk.StringVar(value="Biome")
        color_var = tk.StringVar(value="#66ccff")

        ttk.Label(body, text="Name / identifier:").grid(row=0, column=0, padx=6, pady=5)
        ttk.Entry(body, textvariable=name_var, width=34).grid(row=0, column=1, columnspan=2, padx=2, pady=5)
        ttk.Label(body, text="Type:").grid(row=1, column=0, padx=6, pady=5)
        ttk.Combobox(body, textvariable=type_var, values=("Biome", "Biome Tag"),
                     state="readonly", width=14).grid(row=1, column=1, padx=2, pady=5, sticky="w")
        ttk.Label(body, text="Text color:").grid(row=2, column=0, padx=6, pady=5)
        swatch = tk.Label(body, text="        ", bg=color_var.get(), relief="sunken")
        swatch.grid(row=2, column=1, padx=2, pady=5, sticky="w")

        def pick():
            color = choose_color(window, color_var.get())
            if color:
                color_var.set(color)
                swatch.configure(bg=color)

        ttk.Button(body, text="Choose…", command=pick).grid(row=2, column=2, padx=4, pady=5)

        def add():
            name = name_var.get().strip()
            is_tag = type_var.get() == "Biome Tag"
            color = color_var.get().strip().lower()
            builtins = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
            custom = custom_tags if is_tag else custom_biomes
            if not name:
                messagebox.showwarning("Custom biome", "Enter a name.", parent=window)
                return
            if name in builtins or name in custom:
                messagebox.showwarning("Custom biome", "That name already exists.", parent=window)
                return
            if not _valid_color(color):
                messagebox.showwarning("Custom biome", "Choose a valid text color.", parent=window)
                return
            custom[name] = color
            window.destroy()
            refresh_editor()
            app.set_status(f"Added custom {'biome tag' if is_tag else 'biome'} '{name}'.")

        ttk.Button(body, text="Cancel", command=window.destroy).grid(row=3, column=1, padx=4, pady=(8, 0), sticky="e")
        ttk.Button(body, text="Add", command=add).grid(row=3, column=2, padx=4, pady=(8, 0), sticky="e")
        window.bind("<Return>", lambda _e: add())
        window.bind("<Escape>", lambda _e: window.destroy())

    original_build = library._build_editor_for

    def build(self, entry):
        # Keep the original editor construction, but make the customization
        # injection independent of widget type/name lookups.
        self._available_biome_values = MethodType(available, self)
        original_build(entry)

        combobox = getattr(self, "biome_combobox", None)
        if combobox is not None:
            row1 = combobox.master
            biome_frame = row1.master
            add_button = ttk.Button(
                row1, text="Add custom…", command=add_custom_dialog)
            add_button.pack(side="left", padx=4)

            # Recolor immediately after the original editor has populated the
            # Listbox. This is deliberately done after every rebuild.
            recolor_listbox()
        else:
            recolor_listbox()

    library._build_editor_for = MethodType(build, library)

    def reload_custom(folder):
        custom_biomes.clear()
        custom_tags.clear()
        if folder:
            b, t = _load(folder)
            custom_biomes.update(b)
            custom_tags.update(t)

    def load_config():
        path = filedialog.askdirectory(
            title="Select the songpack folder (containing ReactiveMusic.yaml)")
        if not path:
            return
        try:
            app.pack = yaml_io.load_songpack(path)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc), parent=app)
            return
        app.current_save_folder = path
        reload_custom(path)
        app.refresh_all()
        app.set_status(f"Loaded {len(app.pack.entries)} entries from {path}")

    def save_config():
        app.info_tab.pull_into_pack()
        if not app.pack.entries:
            if not messagebox.askyesno("Save Config", "This songpack has no entries yet. Save anyway?", parent=app):
                return
        folder = filedialog.askdirectory(title="Choose (or create) a folder to save this songpack into")
        if not folder:
            return
        try:
            path = yaml_io.save_songpack(app.pack, folder, copy_music_from=None)
            _save(folder, custom_biomes, custom_tags)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=app)
            return
        app.current_save_folder = folder
        app.set_status(f"Saved songpack and biome customization to {folder}")
        messagebox.showinfo("Saved", f"Songpack saved to:\n{path}\n\nBiome customization saved to:\n{os.path.join(folder, CONFIG_FILENAME)}", parent=app)

    def new_songpack():
        if not messagebox.askyesno("New Songpack", "Discard the current songpack and start a new one?", parent=app):
            return
        app.pack = Songpack()
        app.music_source_folder = None
        app.current_save_folder = None
        reload_custom(None)
        app.refresh_all()
        app.set_status("Started a new, empty songpack.")

    app.action_load_config = load_config
    app.action_save_config = save_config
    app.action_new_songpack = new_songpack

    menu_name = app.cget("menu")
    if menu_name:
        menubar = app.nametowidget(menu_name)
        filemenu_name = menubar.entrycget(menubar.index("File"), "menu")
        if filemenu_name:
            filemenu = app.nametowidget(filemenu_name)
            filemenu.entryconfigure("New Songpack", command=new_songpack)
            filemenu.entryconfigure("Load Config…", command=load_config)
            filemenu.entryconfigure("Save Config…", command=save_config)

    if app.current_save_folder:
        reload_custom(app.current_save_folder)
