"""Optional UI enhancements for the ReactiveMusic Songpack Editor."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from tkinter import filedialog, messagebox, ttk

import yaml_io

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_SETTINGS_PATH = os.path.join(os.path.expanduser(
    "~"), ".rm-songpack-maker", "settings.json")


def standardize_name(name: str) -> str:
    stem, ext = os.path.splitext(name)
    text = unicodedata.normalize("NFKD", stem).encode(
        "ascii", "ignore").decode("ascii")
    text = _SAFE_RE.sub("_", text).strip("._-")
    return text or "track"


def needs_translation(name: str) -> bool:
    return standardize_name(name) != name


def _translate_music_folder(folder, stems):
    changed = [(s, standardize_name(s)) for s in stems if needs_translation(s)]
    if not changed:
        return stems

    preview = "\n".join(f"{old}  ->  {new}" for old, new in changed[:20])
    if len(changed) > 20:
        preview += f"\n... and {len(changed) - 20} more"
    answer = messagebox.askyesno(
        "Non-standard song names",
        "Some filenames contain characters that can be troublesome for a mod YAML/file reference.\n\n"
        "Translate them to standard ASCII letters, numbers, _ - before adding them?\n\n"
        + preview,
    )
    if not answer:
        return stems

    mapping = {}
    used = set(os.listdir(folder))
    files = os.listdir(folder)
    for old_stem, new_stem in changed:
        src = next(
            (f for f in files if os.path.splitext(f)[0] == old_stem), None)
        if not src:
            continue
        ext = os.path.splitext(src)[1]
        candidate = new_stem
        n = 2
        while candidate + ext in used and candidate + ext != src:
            candidate = f"{new_stem}_{n}"
            n += 1
        dst = candidate + ext
        if dst != src:
            os.rename(os.path.join(folder, src), os.path.join(folder, dst))
        used.discard(src)
        used.add(dst)
        mapping[old_stem] = candidate
    return [mapping.get(s, s) for s in stems]


def _load_settings():
    defaults = {"double_click_preview": False}
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update(data)
    except (OSError, ValueError):
        pass
    return defaults


def _save_settings(settings):
    try:
        os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError as exc:
        messagebox.showerror("Settings", f"Could not save settings:\n{exc}")


def _apply_dark_theme(app):
    """Apply a consistent dark palette to the existing Tk/ttk widgets."""
    bg = "#1e1e1e"
    surface = "#252526"
    field = "#2d2d30"
    border = "#3f3f46"
    fg = "#e6e6e6"
    muted = "#a0a0a5"
    accent = "#3b82f6"
    accent_hover = "#4b8ff7"
    selected = "#264f78"

    style = ttk.Style(app)
    try:
        style.theme_use("clam")
    except ttk.TclError:
        pass

    style.configure(".", background=bg, foreground=fg, bordercolor=border,
                    lightcolor=border, darkcolor=border, troughcolor=field)
    style.configure("TFrame", background=bg)
    style.configure("TLabel", background=bg, foreground=fg)
    style.configure("TLabelFrame", background=bg,
                    foreground=fg, bordercolor=border)
    style.configure("TLabelframe.Label", background=bg, foreground=fg)
    style.configure("TButton", background=field, foreground=fg, bordercolor=border,
                    padding=(8, 4), focuscolor=border)
    style.map("TButton", background=[("active", accent_hover), ("pressed", accent)],
              foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])
    style.configure("TEntry", fieldbackground=field, foreground=fg,
                    insertcolor=fg, bordercolor=border, lightcolor=border, darkcolor=border)
    style.configure("TCombobox", fieldbackground=field, foreground=fg,
                    background=field, arrowcolor=fg, bordercolor=border)
    style.map("TCombobox", fieldbackground=[("readonly", field)],
              foreground=[("readonly", fg)], background=[("readonly", field)])
    style.configure("TCheckbutton", background=bg, foreground=fg)
    style.map("TCheckbutton", background=[
              ("active", bg)], foreground=[("active", "#ffffff")])
    style.configure("TRadiobutton", background=bg, foreground=fg)
    style.map("TRadiobutton", background=[
              ("active", bg)], foreground=[("active", "#ffffff")])
    style.configure("TNotebook", background=bg, bordercolor=border)
    style.configure("TNotebook.Tab", background=surface, foreground=muted,
                    padding=(12, 6), bordercolor=border)
    style.map("TNotebook.Tab", background=[("selected", field), ("active", surface)],
              foreground=[("selected", fg), ("active", fg)])
    style.configure("Treeview", background=field, fieldbackground=field,
                    foreground=fg, bordercolor=border, rowheight=25)
    style.map("Treeview", background=[("selected", selected)],
              foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=surface, foreground=fg,
                    bordercolor=border, relief="flat")
    style.map("Treeview.Heading", background=[("active", field)])
    style.configure("Vertical.TScrollbar", background=field, troughcolor=bg,
                    bordercolor=bg, arrowcolor=fg)
    style.configure("Horizontal.TScrollbar", background=field, troughcolor=bg,
                    bordercolor=bg, arrowcolor=fg)

    app.configure(background=bg)
    app.option_add("*TCombobox*Listbox.background", field)
    app.option_add("*TCombobox*Listbox.foreground", fg)
    app.option_add("*TCombobox*Listbox.selectBackground", selected)
    app.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    try:
        menu = app.nametowidget(app["menu"])
        menu.configure(background=surface, foreground=fg,
                       activebackground=accent, activeforeground="#ffffff", borderwidth=0)
        for child in menu.winfo_children():
            try:
                child.configure(background=surface, foreground=fg,
                                activebackground=accent, activeforeground="#ffffff", borderwidth=0)
            except Exception:
                pass
    except Exception:
        pass

    canvas = app.library_tab.canvas
    canvas.configure(background=bg, highlightbackground=border,
                     highlightcolor=border)


def _install_smooth_scrolling(library):
    """Use short pixel-based wheel steps with light easing instead of Tk's coarse units."""
    canvas = library.canvas
    state = {"target": None, "after_id": None}

    def get_scrollable_height():
        bbox = canvas.bbox("all")
        if not bbox:
            return 0
        return max(0, bbox[3] - bbox[1] - canvas.winfo_height())

    def animate():
        state["after_id"] = None
        scrollable = get_scrollable_height()
        if scrollable <= 0 or state["target"] is None:
            return
        current = canvas.yview()[0]
        target = state["target"]
        distance = target - current
        if abs(distance) < 0.001:
            canvas.yview_moveto(target)
            state["target"] = None
            return
        canvas.yview_moveto(max(0.0, min(1.0, current + distance * 0.35)))
        state["after_id"] = canvas.after(12, animate)

    def on_wheel(event):
        scrollable = get_scrollable_height()
        if scrollable <= 0:
            return "break"
        if getattr(event, "num", None) == 4:
            notches = 1
        elif getattr(event, "num", None) == 5:
            notches = -1
        else:
            notches = event.delta / 120.0
        delta_fraction = (-notches * 48.0) / scrollable
        current = canvas.yview()[0]
        target = state["target"] if state["target"] is not None else current
        state["target"] = max(0.0, min(1.0, target + delta_fraction))
        if state["after_id"] is None:
            state["after_id"] = canvas.after(0, animate)
        return "break"

    def bind():
        canvas.bind_all("<MouseWheel>", on_wheel)
        canvas.bind_all("<Button-4>", on_wheel)
        canvas.bind_all("<Button-5>", on_wheel)

    def unbind():
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")
        if state["after_id"] is not None:
            try:
                canvas.after_cancel(state["after_id"])
            except Exception:
                pass
            state["after_id"] = None

    canvas.bind("<Enter>", lambda _e: bind())
    canvas.bind("<Leave>", lambda _e: unbind())


def install(app):
    _apply_dark_theme(app)
    _install_smooth_scrolling(app.library_tab)
    settings = _load_settings()

    original_load = app.action_load_music_folder
    original_save = app.action_save_config

    def load_music_folder():
        folder = filedialog.askdirectory(
            title="Select the folder containing your .mp3/.ogg/.wav files")
        if not folder:
            return
        stems = yaml_io.scan_music_folder(folder)
        stems = _translate_music_folder(folder, stems)
        existing = {s for e in app.pack.entries for s in e.songs}
        added = 0
        for stem in stems:
            if stem not in existing:
                from models import Entry
                app.pack.entries.append(Entry(songs=[stem]))
                added += 1
        app.music_source_folder = folder
        app.refresh_all()
        app.set_status(
            f"Found {len(stems)} audio file(s), added {added} new blank entries.")

    def save_config():
        original_save()
        path = getattr(app, "current_save_folder", None)
        if not path:
            return
        yaml_path = os.path.join(path, "ReactiveMusic.yaml")
        if not os.path.isfile(yaml_path):
            return
        try:
            reloaded = yaml_io.load_songpack(path)
            expected = [s for e in app.pack.entries for s in e.songs]
            actual = [s for e in reloaded.entries for s in e.songs]
            if actual != expected:
                raise ValueError(
                    "Saved YAML does not contain the same song entries as the editor.")
        except Exception as exc:
            messagebox.showerror("Save verification failed", str(exc))
            return
        app.set_status(f"Saved and verified: {yaml_path}")

    app.action_load_music_folder = load_music_folder
    app.action_save_config = save_config

    try:
        import pygame
    except ImportError:
        pygame = None

    preview = {"path": None, "paused": False}

    def resolve_selected_path():
        sel = app.library_tab.tree.selection()
        if not sel or not app.music_source_folder:
            return None
        entry = next((e for e in app.pack.entries if e.id == sel[0]), None)
        if not entry or not entry.songs:
            return None
        stem = entry.songs[0]
        for ext in yaml_io.AUDIO_EXTENSIONS:
            path = os.path.join(app.music_source_folder, stem + ext)
            if os.path.isfile(path):
                return path
        return None

    def play_pause():
        path = resolve_selected_path()
        if pygame is None:
            messagebox.showerror(
                "Preview unavailable", "Install the preview dependency with: pip install pygame")
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            if preview["path"] == path and pygame.mixer.music.get_busy():
                pygame.mixer.music.pause()
                preview["paused"] = True
                preview_button.config(text="Resume song")
                return
            if preview["path"] == path and preview["paused"]:
                pygame.mixer.music.unpause()
                preview["paused"] = False
                preview_button.config(text="Pause song")
                return
            if not path:
                messagebox.showinfo(
                    "Preview", "Select a song from the list and make sure its music folder is loaded.")
                return
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            preview["path"] = path
            preview["paused"] = False
            preview_button.config(text="Pause song")
            app.set_status(f"Previewing {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Preview failed", str(exc))

    def stop_preview():
        if pygame is not None and pygame.mixer.get_init():
            pygame.mixer.music.stop()
        preview["path"] = None
        preview["paused"] = False
        preview_button.config(text="Preview song")

    # Put the controls directly under the song list, where they are visible
    # regardless of how the condition editor is sized.
    library = app.library_tab
    left = next((w for w in library.winfo_children()
                if isinstance(w, ttk.Frame)), None)
    if left is not None:
        controls = ttk.Frame(left)
        controls.pack(fill="x", pady=(6, 0))
        preview_button = ttk.Button(
            controls, text="Preview song", command=play_pause)
        preview_button.pack(side="left", padx=2)
        ttk.Button(controls, text="Stop", command=stop_preview).pack(
            side="left", padx=2)
    else:
        preview_button = ttk.Button(
            library, text="Preview song", command=play_pause)
        preview_button.pack(side="bottom")

    def show_settings():
        dialog = ttk.Frame(app)
        win = __import__("tkinter").Toplevel(app)
        win.title("Settings")
        win.resizable(False, False)
        win.transient(app)
        win.grab_set()

        var = __import__("tkinter").BooleanVar(
            value=settings.get("double_click_preview", False))
        ttk.Label(win, text="Playback").pack(anchor="w", padx=14, pady=(14, 6))
        ttk.Checkbutton(
            win,
            text="Double-click a song to play/pause its preview",
            variable=var,
        ).pack(anchor="w", padx=14, pady=4)
        ttk.Label(
            win,
            text="The setting is saved automatically and applies the next time you use the song list.",
        ).pack(anchor="w", padx=14, pady=(2, 12))

        def apply():
            settings["double_click_preview"] = bool(var.get())
            _save_settings(settings)
            win.destroy()

        ttk.Button(win, text="Cancel", command=win.destroy).pack(
            side="right", padx=(4, 14), pady=(0, 14))
        ttk.Button(win, text="Apply", command=apply).pack(
            side="right", pady=(0, 14))

    # Add Settings to the existing Help/File menu without changing app.py.
    try:
        menu = app.nametowidget(app["menu"])
        file_menu = app.nametowidget(menu.entrycget(0, "menu"))
        file_menu.add_separator()
        file_menu.add_command(label="Settings…", command=show_settings)
    except Exception:
        pass

    def on_tree_double_click(_event=None):
        if settings.get("double_click_preview", False):
            play_pause()

    library.tree.bind("<Double-1>", on_tree_double_click, add="+")
    app.bind("<Destroy>", lambda _e: stop_preview(), add="+")
