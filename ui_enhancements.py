"""Optional UI enhancements for the ReactiveMusic Songpack Editor.

Theming and user preferences moved to app_settings.py + the Settings tab
(settings_tab.py); this module now only adds behaviour: filename
normalisation when scanning a music folder, save verification, and the
audio preview controls.
"""
from __future__ import annotations

import os
import re
import unicodedata
from tkinter import filedialog, messagebox, ttk

import yaml_io
from models import Entry

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


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


def install(app):
    # Preferences are owned by App (app.settings) and edited in the
    # Settings tab; we just read them when an event actually fires, so
    # toggling takes effect immediately.
    settings = app.settings

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
    left = getattr(library, "left", None)
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

    def on_tree_double_click(_event=None):
        if settings.get("double_click_preview", False):
            play_pause()

    library.tree.bind("<Double-1>", on_tree_double_click, add="+")
    app.bind("<Destroy>", lambda _e: stop_preview(), add="+")
