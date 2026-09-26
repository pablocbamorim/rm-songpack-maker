"""Optional UI enhancements for the ReactiveMusic Songpack Editor.

Theming and user preferences moved to app_settings.py + the Settings tab
(settings_tab.py); this module now only adds behaviour: filename
normalisation when scanning a music folder, save verification, and the
audio preview controls.

The preview controls no longer drive pygame directly. Playback state lives
in audio_preview.PreviewPlayer, a single shared object also used by the
audio editor (audio_editor.py) -- pygame's music channel is global, so two
separate state machines would immediately disagree the moment either one
started playing. The button text here follows the shared player through a
listener, which is what makes it fall back to "Preview song" when the
editor takes the channel over.
"""
from __future__ import annotations

import os
import re
import unicodedata
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import audio_io
import audio_preview
import entry_pools
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
        # Reconcile the folder against the editor's one-entry-per-song
        # view. This expands any YAML song pools first, then adds genuinely
        # missing files, so the rule lives in one testable helper.
        app.pack.entries, expanded, added = entry_pools.reconcile_music_folder_entries(
            app.pack.entries, stems)
        app.music_source_folder = folder
        if added:
            mark_dirty = getattr(app, "mark_dirty", None)
            if callable(mark_dirty):
                mark_dirty()
        app.refresh_all()
        app.set_status(
            f"Found {len(stems)} audio file(s), expanded {expanded} pooled song(s), "
            f"added {added} new blank entries.")

    def save_config():
        original_save()
        path = getattr(app, "current_save_folder", None)
        if not path:
            return
        yaml_path = os.path.join(path, "ReactiveMusic.yaml")
        if not os.path.isfile(yaml_path):
            return
        try:
            # 1. The file ReactiveMusic reads, read WITHOUT the editable-source
            #    sidecar: it must be exactly the entries the save meant to write
            #    (the editor's own, or biome_pooling's compiled form).
            pooler = getattr(app, "output_pooler", None)
            pooling = pooler() if callable(pooler) else None
            written = yaml_io.load_songpack(path, use_source=False)
            compiled = pooling(app.pack.entries) if pooling else app.pack.entries
            # Entries with identical conditions are written as one song
            # pool, so compare against the merged grouping, not the raw list.
            expected = yaml_io.expected_songs_after_save(app.pack, pooling)
            actual = [s for e in written.entries for s in e.songs]
            if actual != expected:
                raise ValueError(
                    "Saved YAML does not contain the same song entries as the editor.")
            # Songs alone are not enough: compare what the file MEANS (canonical
            # conditions, song pools, flags, scope, unknown fields, and the
            # priority order of the entries as ReactiveMusic will read them).
            if (entry_pools.semantic_snapshot(compiled)
                    != entry_pools.semantic_snapshot(written.entries)):
                raise ValueError(
                    "The saved YAML does not mean the same thing as the editor: "
                    "an entry's conditions, flags, song pool or priority position "
                    "differ after reloading it.")
            # 2. What the editor gets back on the next load (the authored
            #    entries from songpack_source.yaml when pooling rewrote the YAML).
            reloaded = yaml_io.load_songpack(path)
            if (entry_pools.semantic_snapshot(app.pack.entries)
                    != entry_pools.semantic_snapshot(reloaded.entries)):
                raise ValueError(
                    "Reloading the saved songpack would not give back the "
                    "entries you are editing (songpack_source.yaml does not "
                    "match).")
            if app.pack.extra_top_level != reloaded.extra_top_level:
                raise ValueError(
                    "Top-level keys that the editor does not edit were not "
                    "preserved in the saved YAML.")
        except Exception as exc:
            messagebox.showerror("Save verification failed", str(exc))
            return
        note = getattr(app, "_pooling_note", lambda: "")()
        app.set_status(f"Saved and verified: {yaml_path}{note}")

    app.action_load_music_folder = load_music_folder
    app.action_save_config = save_config

    # ---- audio preview ---------------------------------------------------
    # One shared player for the song list and the audio editor.
    player = audio_preview.get_player()
    player.set_volume(settings.get("preview_volume", 1.0))

    # What the *song list* last asked to play. The player may be playing
    # something else entirely (the editor's trimmed clip), in which case
    # these buttons must not claim it as theirs.
    library_preview = {"path": None}

    def resolve_entry_path(entry):
        """The audio file backing an entry's primary song, or None.

        Exposed on the app (below) so the audio editor can reuse exactly
        this lookup instead of reimplementing it.
        """
        folder = getattr(app, "music_source_folder", None)
        if not entry or not entry.songs or not folder:
            return None
        return audio_io.resolve_song_path(
            folder, entry.songs[0], yaml_io.AUDIO_EXTENSIONS)

    def resolve_selected_path():
        sel = app.library_tab.tree.selection()
        if not sel:
            return None
        entry = next((e for e in app.pack.entries if e.id == sel[0]), None)
        return resolve_entry_path(entry)

    def update_preview_button(*_args):
        """Keep the button text in sync with the shared player, whoever
        changed it.
        """
        path = library_preview["path"]
        try:
            if path and player.is_current(path):
                if player.is_playing():
                    preview_button.config(text="Pause song")
                    return
                if player.is_paused():
                    preview_button.config(text="Resume song")
                    return
            library_preview["path"] = None
            preview_button.config(text="Preview song")
        except tk.TclError:  # window is going away
            pass

    def play_pause():
        if not player.available():
            messagebox.showerror(
                "Preview unavailable", "Install the preview dependency with: pip install pygame")
            return

        path = library_preview["path"]
        if path and player.is_current(path) and not player.is_playing() \
                and not player.is_paused():
            # It finished on its own since the last click.
            path = None

        if path and player.is_current(path):
            if player.is_playing():
                player.pause()
            elif player.is_paused():
                player.resume()
            update_preview_button()
            return

        path = resolve_selected_path()
        if not path:
            messagebox.showinfo(
                "Preview", "Select a song from the list and make sure its music folder is loaded.")
            return
        try:
            player.play(path, volume=settings.get("preview_volume", 1.0))
        except audio_preview.PreviewError as exc:
            messagebox.showerror("Preview failed", str(exc))
            return
        library_preview["path"] = path
        update_preview_button()
        app.set_status(f"Previewing {os.path.basename(path)}")

    def stop_preview():
        if library_preview["path"] and player.is_current(library_preview["path"]):
            player.stop()
        library_preview["path"] = None
        update_preview_button()

    def edit_audio():
        """Open the audio editor for the selected song."""
        sel = app.library_tab.tree.selection()
        if len(sel) != 1:
            messagebox.showinfo(
                "Audio editor", "Select exactly one song to edit its audio.")
            return
        entry = next((e for e in app.pack.entries if e.id == sel[0]), None)
        if entry is None:
            return
        try:
            import audio_editor
        except ImportError as exc:
            messagebox.showerror("Audio editor unavailable", str(exc))
            return
        audio_editor.open_audio_editor(app, entry)

    # Used by app_core's "Edit audio…" button and by audio_editor itself.
    app.resolve_entry_audio_path = resolve_entry_path
    app.audio_preview = player
    app.action_edit_audio = edit_audio

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

    def on_player_state(_state, _path):
        update_preview_button()

    player.add_listener(on_player_state)

    def on_tree_double_click(_event=None):
        if settings.get("double_click_preview", False):
            play_pause()

    library.tree.bind("<Double-1>", on_tree_double_click, add="+")

    def on_app_destroy(_event=None):
        # The shared player outlives any single widget, so drop the
        # listener along with the buttons it updates.
        player.remove_listener(on_player_state)
        stop_preview()

    app.bind("<Destroy>", lambda _e: on_app_destroy(), add="+")
