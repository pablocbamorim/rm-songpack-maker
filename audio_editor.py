"""
audio_editor.py
----------------
Tab-adjacent feature: a basic, songpack-oriented audio editor.

    Music & Conditions -> select a song -> "Edit audio…" -> this window.

SCOPE
-----
Waveform + trim + preview + preview volume + save-as-new / replace. That
is the whole feature; there is deliberately no mixing, no effects, no
metadata editing. Anything heavier belongs in a real audio editor.

HOW IT FITS THE EXISTING APP
----------------------------
* It is a ``ctk.CTkToplevel`` built from the same CustomTkinter widgets,
  fonts and card layout as app_core, so it reads as part of the program
  rather than a bolted-on tk utility. The only raw-tk widgets are the two
  ``tk.Canvas`` instances, because CTk has no canvas equivalent -- the
  same compromise app_core already makes for its Treeviews and Listboxes.
* Playback goes through ``audio_preview.get_player()``, the same object
  the song list's Preview/Stop buttons use, so the two can never fight
  over pygame's single music channel.
* Decoding/encoding lives in audio_io (soundfile + numpy); see that
  module for why that dependency was chosen.

THREADING RULES
---------------
Scanning a file for its waveform and encoding a trimmed copy both take
long enough to freeze Tk on a big track, so both run on a daemon thread
and come back through ``_post`` -> ``after(0, ...)``. Worker functions
never touch a widget; the window is flagged ``_closing`` on close and
every posted callback re-checks it, so a thread finishing after the
window is gone is a no-op rather than a TclError.

NON-DESTRUCTIVE BY CONSTRUCTION
-------------------------------
Trim points and the volume slider are pure UI state. The source file is
only ever *read* until the user presses Save as New or Replace, and even
then audio_io.export_segment writes a temp file and os.replace()s it into
position.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import audio_io
import audio_preview
import theme

try:  # the editor can add a trimmed copy to the songpack after saving
    from models import Entry
except Exception:  # noqa: BLE001 - never block the editor on this
    Entry = None  # type: ignore[assignment]


# Mirrors app_core's typography scale. Duplicated rather than imported to
# keep this module importable on its own (app_core imports it lazily).
_BODY = ("", 13)
_BODY_BOLD = ("", 13, "bold")
_SECTION = ("", 15, "bold")
_TITLE = ("", 17, "bold")
_SMALL = ("", 11)

#: Peak buckets scanned per file. Far above any realistic window width, so
#: resizing re-buckets in memory instead of re-reading the file.
_WAVE_BUCKETS = 4000

_WAVE_HEIGHT = 190
_RULER_HEIGHT = 24
_HANDLE_GRAB_PX = 7

#: Open windows keyed by absolute source path, so the same file can't be
#: opened in two editors at once (they would disagree after a save).
_OPEN: dict = {}


def _palette(dark: bool) -> dict:
    return theme.waveform_palette(dark)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def open_audio_editor(app, entry=None, path=None) -> None:
    """Open the editor for `entry`'s primary song (or an explicit `path`).

    Handles the boring-but-common failures up front -- missing dependency,
    no music folder loaded, file moved/renamed since the folder was
    scanned -- with a message the user can act on, and offers to locate
    the file by hand rather than dead-ending.
    """
    if not audio_io.available():
        messagebox.showerror("Audio editor unavailable",
                             audio_io.unavailable_reason(), parent=app)
        return

    if path is None:
        path = _resolve_entry_path(app, entry)
    if path is None:
        song = (entry.songs[0] if entry is not None and entry.songs
                else "this entry")
        folder = getattr(app, "music_source_folder", None)
        hint = (f"No audio file named '{song}' was found in:\n{folder}"
                if folder else
                "No music folder is loaded yet, so the editor doesn't know "
                "where this song's audio file lives.")
        if not messagebox.askyesno(
                "Audio file not found",
                f"{hint}\n\nLocate the audio file manually?", parent=app):
            return
        path = filedialog.askopenfilename(
            parent=app, title="Select the audio file to edit",
            initialdir=folder or os.path.expanduser("~"),
            filetypes=[("Audio files", "*.mp3 *.ogg *.wav *.flac"),
                       ("All files", "*.*")])
        if not path:
            return

    key = os.path.abspath(path)
    existing = _OPEN.get(key)
    if existing is not None:
        try:
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return
        except tk.TclError:
            _OPEN.pop(key, None)

    try:
        # Probed before the window exists: a corrupt file should produce a
        # message box, not an empty editor that then fails to populate.
        info = audio_io.probe(path)
    except audio_io.AudioError as exc:
        messagebox.showerror("Could not open audio file", str(exc), parent=app)
        return

    _OPEN[key] = AudioEditorWindow(app, path, info, entry=entry)


def _resolve_entry_path(app, entry):
    """Reuse ui_enhancements' resolver when it's installed; fall back to
    the same lookup so the button also works from a bare app.py run.
    """
    resolver = getattr(app, "resolve_entry_audio_path", None)
    if callable(resolver) and entry is not None:
        try:
            found = resolver(entry)
            if found:
                return found
        except Exception:  # noqa: BLE001
            pass
    if entry is None or not entry.songs:
        return None
    folder = getattr(app, "music_source_folder", None)
    extensions = audio_io.DEFAULT_EXTENSIONS
    try:
        import yaml_io
        extensions = tuple(getattr(yaml_io, "AUDIO_EXTENSIONS", extensions))
    except Exception:  # noqa: BLE001
        pass
    return audio_io.resolve_song_path(folder, entry.songs[0], extensions)


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
class AudioEditorWindow(ctk.CTkToplevel):
    MIN_SEL = audio_io.MIN_SELECTION_SECONDS

    def __init__(self, app, path: str, info: "audio_io.AudioInfo", entry=None):
        super().__init__(app)
        self.app = app
        self.entry = entry
        self.source_path = path
        self.player = audio_preview.get_player()

        # Header data, probed by open_audio_editor before this window was
        # created. The full peak scan happens on a worker thread below.
        self.info = info
        self.duration = self.info.duration

        self.waveform = None
        self.sel_start = 0.0
        self.sel_end = self.duration
        self._closing = False
        self._busy = False
        self._drag_mode = None
        self._wave_width = -1
        self._preview_path = None
        self._preview_key = None
        self._poll_job = None
        self._volume_save_job = None

        self.dark = bool(getattr(app, "settings", {}).get("dark_theme", True))
        self.pal = _palette(self.dark)

        self.title(f"Audio Editor — {os.path.basename(path)}")
        self.geometry("980x640")
        self.minsize(820, 560)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._sync_time_fields()
        self._start_analysis()

        self.after(60, self.focus_force)

    # -- construction ----------------------------------------------------
    def _build_ui(self) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        # ---- header ----
        header = ctk.CTkFrame(outer, corner_radius=8)
        header.pack(fill="x")
        ctk.CTkLabel(header, text=os.path.basename(self.source_path),
                     font=_TITLE, anchor="w").pack(
                         fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(header, text=self.info.describe(), font=_SMALL,
                     text_color=("gray40", "gray70"), anchor="w").pack(
                         fill="x", padx=14, pady=(0, 10))

        # ---- waveform ----
        wave_card = ctk.CTkFrame(outer, corner_radius=8)
        wave_card.pack(fill="both", expand=True, pady=(10, 0))

        self.canvas = tk.Canvas(
            wave_card, height=_WAVE_HEIGHT, bg=self.pal["canvas"],
            highlightthickness=0, bd=0, cursor="left_ptr")
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(12, 0))
        self.ruler = tk.Canvas(
            wave_card, height=_RULER_HEIGHT, bg=self.pal["canvas"],
            highlightthickness=0, bd=0)
        self.ruler.pack(fill="x", padx=12, pady=(0, 12))

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_hover)

        # ---- trim controls ----
        trim = ctk.CTkFrame(outer, corner_radius=8)
        trim.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(trim, text="Trim", font=_SECTION, anchor="w").pack(
            fill="x", padx=14, pady=(10, 0))

        row = ctk.CTkFrame(trim, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(4, 10))

        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        self.start_entry = self._time_field(row, "Start:", self.start_var,
                                            "start")
        self.end_entry = self._time_field(row, "End:", self.end_var, "end")

        self.length_label = ctk.CTkLabel(row, text="", font=_BODY_BOLD)
        self.length_label.pack(side="left", padx=(16, 0))

        self.select_all_btn = ctk.CTkButton(
            row, text="Select whole track", width=140, font=_BODY,
            **theme.NEUTRAL_BUTTON,
            command=self._select_all)
        self.select_all_btn.pack(side="right", padx=4)

        ctk.CTkLabel(
            trim,
            text=("Drag the handles over the waveform, or drag anywhere on it to select a new "
                  "region. Times accept seconds (12.5) or m:ss.mmm (1:23.400)."),
            font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
            justify="left", wraplength=880,
        ).pack(fill="x", padx=14, pady=(0, 10))

        # ---- preview ----
        preview = ctk.CTkFrame(outer, corner_radius=8)
        preview.pack(fill="x", pady=(10, 0))
        prow = ctk.CTkFrame(preview, fg_color="transparent")
        prow.pack(fill="x", padx=10, pady=10)

        self.play_btn = ctk.CTkButton(prow, text="▶  Play selection",
                                      width=160, font=_BODY,
                                      command=self._toggle_play)
        self.play_btn.pack(side="left", padx=4)
        self.stop_btn = ctk.CTkButton(
            prow, text="■  Stop", width=90, font=_BODY,
            **theme.NEUTRAL_BUTTON,
            command=self._stop_play)
        self.stop_btn.pack(side="left", padx=4)

        ctk.CTkLabel(prow, text="Preview volume:", font=_BODY).pack(
            side="left", padx=(20, 6))
        start_volume = float(getattr(self.app, "settings", {}).get(
            "preview_volume", self.player.get_volume()))
        self.volume_var = tk.DoubleVar(value=max(0.0, min(1.0, start_volume)))
        self.volume_slider = ctk.CTkSlider(
            prow, from_=0.0, to=1.0, number_of_steps=100,
            variable=self.volume_var, width=180,
            command=lambda _v: self._on_volume_changed())
        self.volume_slider.pack(side="left")
        self.volume_label = ctk.CTkLabel(prow, text="", font=_BODY, width=48)
        self.volume_label.pack(side="left", padx=(8, 0))
        self.player.set_volume(self.volume_var.get())
        self._update_volume_label()

        ctk.CTkLabel(
            preview,
            text="Volume affects playback only — it is never written into the file.",
            font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

        # ---- footer ----
        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", pady=(10, 0))

        self.status_label = ctk.CTkLabel(
            footer, text="", font=_SMALL, anchor="w", justify="left",
            text_color=("gray40", "gray70"), wraplength=480)
        self.status_label.pack(side="left", fill="x", expand=True, padx=(4, 8))

        self.progress = ctk.CTkProgressBar(footer, width=140)
        self.progress.set(0)

        self.close_btn = ctk.CTkButton(
            footer, text="Close", width=90, font=_BODY,
            **theme.NEUTRAL_BUTTON,
            command=self._on_close)
        self.close_btn.pack(side="right", padx=4)
        self.replace_btn = ctk.CTkButton(
            footer, text="Replace original…", width=150, font=_BODY,
            **theme.DANGER_BUTTON,
            command=self._replace_original)
        self.replace_btn.pack(side="right", padx=4)
        self.save_new_btn = ctk.CTkButton(
            footer, text="Save as New…", width=130, font=_BODY,
            command=self._save_as_new)
        self.save_new_btn.pack(side="right", padx=4)

        self.bind("<Escape>", lambda _e: self._on_close())
        self.bind("<space>", self._on_space)

        self._set_controls_enabled(False)

    def _time_field(self, parent, label: str, var: tk.StringVar, which: str):
        ctk.CTkLabel(parent, text=label, font=_BODY).pack(
            side="left", padx=(6, 4))
        field = ctk.CTkEntry(parent, textvariable=var, width=110, font=_BODY)
        field.pack(side="left")
        field.bind("<Return>", lambda _e, w=which: self._commit_time(w))
        field.bind("<FocusOut>", lambda _e, w=which: self._commit_time(w))
        for text, delta in (("−", -0.1), ("+", 0.1)):
            ctk.CTkButton(
                parent, text=text, width=30, font=_BODY,
                **theme.NEUTRAL_BUTTON,
                command=lambda w=which, d=delta: self._nudge(w, d),
            ).pack(side="left", padx=2)
        return field

    # -- threading helpers ------------------------------------------------
    def _post(self, fn) -> None:
        """Run `fn` on the Tk thread, unless the window is on its way out."""
        if self._closing:
            return

        def guarded():
            if self._closing:
                return
            try:
                if not self.winfo_exists():
                    return
            except tk.TclError:
                return
            fn()

        try:
            self.after(0, guarded)
        except (tk.TclError, RuntimeError):
            pass

    def _run_async(self, work, on_done, on_error=None) -> None:
        def runner():
            try:
                result = work()
            except audio_io.Cancelled:
                return
            except Exception as exc:  # noqa: BLE001 - reported, never raised at Tk
                # Bound as a default argument: Python deletes the `exc`
                # name when the except block ends, and this lambda runs
                # later, on the Tk thread.
                handler = on_error or self._report_error
                self._post(lambda error=exc: handler(error))
                return
            self._post(lambda: on_done(result))

        threading.Thread(target=runner, daemon=True).start()

    def _report_error(self, exc: Exception, title: str = "Audio error") -> None:
        self._set_busy(False)
        self._set_status("Failed: " + str(exc).splitlines()[0])
        messagebox.showerror(title, str(exc), parent=self)

    # -- waveform analysis ------------------------------------------------
    def _start_analysis(self) -> None:
        self._set_busy(True, "Analysing audio…")
        path = self.source_path
        last = [0]

        def progress(fraction: float) -> None:
            step = int(fraction * 40)
            if step != last[0]:
                last[0] = step
                self._post(lambda f=fraction: self.progress.set(f))

        def work():
            return audio_io.compute_waveform(
                path, buckets=_WAVE_BUCKETS, progress=progress,
                should_cancel=lambda: self._closing)

        def done(waveform):
            self.waveform = waveform
            self.info = waveform.info
            self.duration = self.info.duration
            self.sel_start = 0.0
            self.sel_end = self.duration
            self._wave_width = -1
            self._set_busy(False)
            self._set_controls_enabled(True)
            self._sync_time_fields()
            self._redraw_all()
            note = ("  Note: re-saving a lossy file re-encodes it, which loses "
                    "a little quality." if self.info.lossy else "")
            self._set_status("Ready." + note)

        self._run_async(work, done)

    # -- drawing ----------------------------------------------------------
    def _on_canvas_resize(self, _event=None) -> None:
        self._redraw_all()

    def _redraw_all(self) -> None:
        self._redraw_wave()
        self._redraw_ruler()
        self._redraw_overlay()

    def _canvas_size(self):
        try:
            return int(self.canvas.winfo_width()), int(self.canvas.winfo_height())
        except tk.TclError:
            return 0, 0

    def _redraw_wave(self) -> None:
        canvas = self.canvas
        width, height = self._canvas_size()
        if width < 8 or height < 8:
            return
        canvas.delete("wave")
        mid = height / 2.0
        canvas.create_line(0, mid, width, mid, fill=self.pal["axis"],
                           tags="wave")
        if self.waveform is None:
            canvas.create_text(width / 2, mid, text="Analysing audio…",
                               fill=self.pal["text"], font=_BODY, tags="wave")
            return

        mins, maxs = self.waveform.resample(width)
        amp = mid - 8
        colour = self.pal["wave"]
        for x in range(width):
            top = mid - float(maxs[x]) * amp
            bottom = mid - float(mins[x]) * amp
            if bottom - top < 1.0:  # keep silence visible as a hairline
                top, bottom = mid - 0.5, mid + 0.5
            canvas.create_line(x, top, x, bottom, fill=colour, tags="wave")
        canvas.tag_lower("wave")
        self._wave_width = width

    def _redraw_ruler(self) -> None:
        ruler = self.ruler
        ruler.delete("all")
        width, _h = self._canvas_size()
        if width < 8 or self.duration <= 0:
            return
        step = _nice_step(self.duration, width)
        colour = self.pal["text"]
        grid = self.pal["grid"]
        ticks = int(self.duration / step) + 1
        for i in range(ticks + 1):
            seconds = i * step
            if seconds > self.duration:
                break
            x = self._time_to_x(seconds)
            ruler.create_line(x, 0, x, 6, fill=grid)
            anchor = "w" if i == 0 else ("e" if x > width - 24 else "center")
            ruler.create_text(x, 15, text=audio_io.format_time(seconds, False),
                              fill=colour, font=_SMALL, anchor=anchor)

    def _redraw_overlay(self) -> None:
        canvas = self.canvas
        width, height = self._canvas_size()
        canvas.delete("ov")
        if width < 8 or self.duration <= 0:
            return
        x1 = self._time_to_x(self.sel_start)
        x2 = self._time_to_x(self.sel_end)

        # Everything outside the selection is dimmed; a stippled rectangle
        # is the closest tk.Canvas gets to an alpha overlay, and it keeps
        # dragging cheap (two rectangles moved, not a redrawn waveform).
        for a, b in ((0, x1), (x2, width)):
            if b - a >= 1:
                canvas.create_rectangle(a, 0, b, height, fill=self.pal["dim"],
                                        outline="", stipple="gray50", tags="ov")
        for x in (x1, x2):
            canvas.create_line(x, 0, x, height, fill=self.pal["handle"],
                               width=2, tags="ov")
        # Grips, so the draggable bits look draggable.
        canvas.create_rectangle(x1 - 4, 0, x1 + 4, 14,
                                fill=self.pal["handle"], outline="", tags="ov")
        canvas.create_rectangle(x2 - 4, height - 14, x2 + 4, height,
                                fill=self.pal["handle"], outline="", tags="ov")
        canvas.create_text(
            min(width - 4, x1 + 6), 20, anchor="nw", font=_SMALL,
            fill=self.pal["handle"],
            text=audio_io.format_time(self.sel_start), tags="ov")
        canvas.create_text(
            max(4, x2 - 6), height - 20, anchor="se", font=_SMALL,
            fill=self.pal["handle"],
            text=audio_io.format_time(self.sel_end), tags="ov")

    def _redraw_playhead(self, seconds=None) -> None:
        canvas = self.canvas
        canvas.delete("ph")
        if seconds is None:
            return
        width, height = self._canvas_size()
        if width < 8:
            return
        x = self._time_to_x(seconds)
        canvas.create_line(x, 0, x, height, fill=self.pal["playhead"],
                           width=1, tags="ph")

    # -- coordinates ------------------------------------------------------
    def _time_to_x(self, seconds: float) -> float:
        width, _h = self._canvas_size()
        if self.duration <= 0 or width <= 0:
            return 0.0
        return max(0.0, min(float(width), seconds / self.duration * width))

    def _x_to_time(self, x: float) -> float:
        width, _h = self._canvas_size()
        if width <= 0:
            return 0.0
        return max(0.0, min(self.duration, float(x) / width * self.duration))

    # -- selection --------------------------------------------------------
    def _set_selection(self, start: float, end: float, source: str = "both") -> None:
        """Single funnel for every selection change (drag, typing, nudge,
        select-all), so the invalid-range rules live in exactly one place:
        inside [0, duration], never reversed, never shorter than MIN_SEL.
        """
        duration = self.duration
        if duration <= 0:
            return
        min_len = min(self.MIN_SEL, duration)
        start = max(0.0, min(float(start), duration))
        end = max(0.0, min(float(end), duration))

        if source == "start":
            start = min(start, duration - min_len)
            end = max(end, start + min_len)
        elif source == "end":
            end = max(end, min_len)
            start = min(start, end - min_len)
        else:
            if end - start < min_len:
                end = min(duration, start + min_len)
                start = max(0.0, end - min_len)

        changed = (abs(start - self.sel_start) > 1e-9
                   or abs(end - self.sel_end) > 1e-9)
        self.sel_start, self.sel_end = start, end
        if changed:
            # The rendered preview clip no longer matches the selection.
            self._preview_key = None
        self._sync_time_fields()
        self._redraw_overlay()

    def _sync_time_fields(self) -> None:
        self.start_var.set(audio_io.format_time(self.sel_start))
        self.end_var.set(audio_io.format_time(self.sel_end))
        if hasattr(self, "length_label"):
            self.length_label.configure(
                text=f"Length: {audio_io.format_time(self.sel_end - self.sel_start)}"
                f"   (of {audio_io.format_time(self.duration)})")

    def _commit_time(self, which: str) -> None:
        var = self.start_var if which == "start" else self.end_var
        try:
            value = audio_io.parse_time(var.get())
        except ValueError:
            self._set_status(
                f"'{var.get()}' isn't a valid time — use seconds (12.5) or "
                "m:ss.mmm (1:23.400).")
            self._sync_time_fields()
            return
        if value > self.duration + 1e-6:
            self._set_status(
                f"Clamped to the end of the audio ({audio_io.format_time(self.duration)}).")
        if which == "start":
            self._set_selection(value, self.sel_end, source="start")
        else:
            self._set_selection(self.sel_start, value, source="end")

    def _nudge(self, which: str, delta: float) -> None:
        if which == "start":
            self._set_selection(self.sel_start + delta, self.sel_end,
                                source="start")
        else:
            self._set_selection(self.sel_start, self.sel_end + delta,
                                source="end")

    def _select_all(self) -> None:
        self._set_selection(0.0, self.duration)
        self._set_status("Selected the whole track.")

    # -- mouse ------------------------------------------------------------
    def _near_handle(self, x: float):
        if self.waveform is None:
            return None
        if abs(x - self._time_to_x(self.sel_start)) <= _HANDLE_GRAB_PX:
            return "start"
        if abs(x - self._time_to_x(self.sel_end)) <= _HANDLE_GRAB_PX:
            return "end"
        return None

    def _on_hover(self, event) -> None:
        if self.waveform is None or self._busy:
            return
        cursor = "sb_h_double_arrow" if self._near_handle(
            event.x) else "left_ptr"
        try:
            self.canvas.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _on_press(self, event) -> None:
        if self.waveform is None or self._busy:
            return
        handle = self._near_handle(event.x)
        if handle:
            self._drag_mode = handle
            return
        # Drag on empty waveform: start a brand-new selection here.
        self._drag_mode = "new"
        self._drag_anchor = self._x_to_time(event.x)
        self._set_selection(self._drag_anchor,
                            self._drag_anchor + self.MIN_SEL)

    def _on_drag(self, event) -> None:
        if not self._drag_mode:
            return
        time_at = self._x_to_time(event.x)
        if self._drag_mode == "start":
            self._set_selection(time_at, self.sel_end, source="start")
        elif self._drag_mode == "end":
            self._set_selection(self.sel_start, time_at, source="end")
        else:
            anchor = getattr(self, "_drag_anchor", time_at)
            low, high = min(anchor, time_at), max(anchor, time_at)
            self._set_selection(low, high)

    def _on_release(self, _event=None) -> None:
        if self._drag_mode:
            self._drag_mode = None
            self._set_status(
                f"Selection: {audio_io.format_time(self.sel_start)} → "
                f"{audio_io.format_time(self.sel_end)}")

    def _on_space(self, event):
        # Don't hijack the space bar while the user is typing a time.
        widget = self.focus_get()
        if isinstance(widget, (tk.Entry, tk.Text)):
            return None
        self._toggle_play()
        return "break"

    # -- preview ----------------------------------------------------------
    def _preview_selection_key(self):
        return (round(self.sel_start, 3), round(self.sel_end, 3))

    def _toggle_play(self) -> None:
        if self.waveform is None or self._busy:
            return
        if not self.player.available():
            messagebox.showerror(
                "Preview unavailable",
                "Audio preview needs the 'pygame' package.\n\n"
                "Install it with:  python -m pip install pygame", parent=self)
            return

        # Already playing/paused *our* clip: just toggle it.
        if (self._preview_path and self.player.is_current(self._preview_path)
                and self._preview_key == self._preview_selection_key()):
            try:
                state = self.player.toggle(self._preview_path,
                                           volume=self.volume_var.get())
            except audio_preview.PreviewError as exc:
                self._report_error(exc, "Preview failed")
                return
            self._update_play_button()
            if state == audio_preview.PLAYING:
                self._poll_playback()
            return

        self._render_and_play()

    def _render_and_play(self) -> None:
        try:
            audio_io.validate_range(
                self.sel_start, self.sel_end, self.duration)
        except audio_io.AudioError as exc:
            messagebox.showwarning("Invalid selection", str(exc), parent=self)
            return

        self._discard_preview_clip()
        self._set_busy(True, "Preparing preview…")
        src, start, end = self.source_path, self.sel_start, self.sel_end
        key = self._preview_selection_key()

        def work():
            return audio_io.export_preview_wav(
                src, start, end, should_cancel=lambda: self._closing)

        def done(temp_path):
            self._preview_path = temp_path
            self._preview_key = key
            self._set_busy(False)
            try:
                self.player.play(temp_path, volume=self.volume_var.get())
            except audio_preview.PreviewError as exc:
                self._report_error(exc, "Preview failed")
                return
            self._update_play_button()
            self._set_status(
                f"Previewing {audio_io.format_time(start)} → "
                f"{audio_io.format_time(end)}")
            self._poll_playback()

        self._run_async(work, done,
                        on_error=lambda exc: self._report_error(
                            exc, "Preview failed"))

    def _poll_playback(self) -> None:
        if self._closing:
            return
        self._poll_job = None
        if self.player.is_current(self._preview_path):
            if self.player.is_playing():
                position = self.sel_start + self.player.position()
                self._redraw_playhead(min(position, self.sel_end))
                self._poll_job = self.after(60, self._poll_playback)
                return
            if self.player.is_paused():
                self._poll_job = self.after(150, self._poll_playback)
                return
        self._redraw_playhead(None)
        self._update_play_button()

    def _stop_play(self) -> None:
        if self.player.is_current(self._preview_path):
            self.player.stop()
        self._redraw_playhead(None)
        self._update_play_button()

    def _update_play_button(self) -> None:
        try:
            if self.player.is_current(self._preview_path):
                if self.player.is_playing():
                    self.play_btn.configure(text="⏸  Pause")
                    return
                if self.player.is_paused():
                    self.play_btn.configure(text="▶  Resume")
                    return
            self.play_btn.configure(text="▶  Play selection")
        except tk.TclError:
            pass

    def _discard_preview_clip(self) -> None:
        """Stop playback of, and delete, the rendered preview clip.

        Order matters on Windows: pygame keeps the file open, so it has to
        be released before the unlink.
        """
        if self._preview_path:
            if self.player.is_current(self._preview_path):
                self.player.unload()
            audio_io.silent_unlink(self._preview_path)
        self._preview_path = None
        self._preview_key = None

    # -- volume -----------------------------------------------------------
    def _on_volume_changed(self) -> None:
        volume = float(self.volume_var.get())
        self.player.set_volume(volume)
        self._update_volume_label()
        # The slider fires continuously; debounce the settings write so a
        # drag doesn't hit the disk 100 times.
        if self._volume_save_job is not None:
            try:
                self.after_cancel(self._volume_save_job)
            except tk.TclError:
                pass
        self._volume_save_job = self.after(600, self._persist_volume)

    def _persist_volume(self) -> None:
        self._volume_save_job = None
        settings = getattr(self.app, "settings", None)
        if not isinstance(settings, dict):
            return
        settings["preview_volume"] = round(float(self.volume_var.get()), 3)
        saver = getattr(self.app, "save_settings", None)
        if callable(saver):
            saver()

    def _update_volume_label(self) -> None:
        self.volume_label.configure(
            text=f"{int(round(self.volume_var.get() * 100))}%")

    # -- saving -----------------------------------------------------------
    def _save_as_new(self) -> None:
        if not self._ready_to_export():
            return
        source_ext = self.info.ext or ".wav"
        if not audio_io.can_write(source_ext):
            messagebox.showwarning(
                "Format not writable",
                f"This build of libsndfile cannot write {source_ext} files.\n\n"
                "Save as one of: " +
                ", ".join(sorted(audio_io.writable_extensions())),
                parent=self)
            source_ext = ".wav"

        stem = os.path.splitext(os.path.basename(self.source_path))[0]
        initial_dir = (getattr(self.app, "music_source_folder", None)
                       or os.path.dirname(self.source_path))
        dest = filedialog.asksaveasfilename(
            parent=self, title="Save trimmed audio as…",
            initialdir=initial_dir, initialfile=f"{stem}_trimmed{source_ext}",
            defaultextension=source_ext,
            filetypes=[("Audio files", "*.mp3 *.ogg *.wav *.flac"),
                       ("All files", "*.*")])
        if not dest:
            self._set_status("Save cancelled — nothing was written.")
            return

        ext = os.path.splitext(dest)[1].lower()
        if not audio_io.can_write(ext):
            messagebox.showerror(
                "Unsupported format",
                f"'{ext or dest}' is not a format this editor can write.\n\n"
                "Supported: " +
                ", ".join(sorted(audio_io.writable_extensions())),
                parent=self)
            return

        same_file = (os.path.abspath(dest) ==
                     os.path.abspath(self.source_path))
        if same_file and not self._confirm_replace(
                "You picked the file you are currently editing."):
            return
        if (not same_file and os.path.exists(dest)
                and not messagebox.askyesno(
                    "Overwrite file?",
                    f"'{os.path.basename(dest)}' already exists.\n\nOverwrite it?",
                    parent=self)):
            self._set_status("Save cancelled — nothing was written.")
            return

        self._export(dest, replacing=same_file)

    def _replace_original(self) -> None:
        if not self._ready_to_export():
            return
        ext = self.info.ext
        if not audio_io.can_write(ext):
            messagebox.showerror(
                "Format not writable",
                f"This build of libsndfile cannot write {ext} files, so the "
                "original cannot be replaced.\n\nUse 'Save as New…' and pick "
                "a supported format instead.", parent=self)
            return
        if not self._confirm_replace():
            return
        self._export(self.source_path, replacing=True)

    def _confirm_replace(self, prefix: str = "") -> bool:
        lossy_note = ("\n\nThis is a lossy format, so it will be re-encoded "
                      "and lose a little quality." if self.info.lossy else "")
        message = (
            (prefix + "\n\n" if prefix else "")
            + f"Replace '{os.path.basename(self.source_path)}' with the "
            f"selected region?\n\n"
            f"Keeping: {audio_io.format_time(self.sel_start)} → "
            f"{audio_io.format_time(self.sel_end)}  "
            f"({audio_io.format_time(self.sel_end - self.sel_start)})\n\n"
            "The rest of the audio is discarded and this cannot be undone."
            + lossy_note)
        return bool(messagebox.askyesno("Replace original audio?", message,
                                        parent=self, icon="warning"))

    def _ready_to_export(self) -> bool:
        if self._busy:
            return False
        if self.waveform is None:
            self._set_status(
                "Still analysing the audio — try again in a moment.")
            return False
        if not os.path.isfile(self.source_path):
            messagebox.showerror(
                "File missing",
                f"The source file no longer exists:\n{self.source_path}",
                parent=self)
            return False
        try:
            audio_io.validate_range(
                self.sel_start, self.sel_end, self.duration)
        except audio_io.AudioError as exc:
            messagebox.showwarning("Invalid trim range", str(exc), parent=self)
            return False
        return True

    def _export(self, dest: str, replacing: bool) -> None:
        # Release the source file before overwriting it: on Windows a file
        # that pygame still has loaded cannot be replaced.
        self._discard_preview_clip()
        if self.player.is_current(self.source_path):
            self.player.unload()

        self._set_busy(True, "Replacing original…" if replacing else "Saving…")
        src, start, end = self.source_path, self.sel_start, self.sel_end
        last = [0]

        def progress(fraction: float) -> None:
            step = int(fraction * 40)
            if step != last[0]:
                last[0] = step
                self._post(lambda f=fraction: self.progress.set(f))

        def work():
            return audio_io.export_segment(
                src, dest, start, end, progress=progress,
                should_cancel=lambda: self._closing)

        def done(written_path):
            self._set_busy(False)
            if replacing and os.path.abspath(written_path) == os.path.abspath(
                    self.source_path):
                self._set_status(
                    f"Replaced {os.path.basename(written_path)}. Reloading waveform…")
                self._after_replace()
            else:
                self._set_status(f"Saved {written_path}")
                self._offer_add_entry(written_path)
            app_status = getattr(self.app, "set_status", None)
            if callable(app_status):
                app_status(f"Audio editor: wrote {written_path}")

        self._run_async(work, done,
                        on_error=lambda exc: self._report_error(exc, "Save failed"))

    def _after_replace(self) -> None:
        """The source changed underneath us, so re-read it and reset the
        selection to the whole (new, shorter) file.
        """
        self.waveform = None
        self._preview_key = None
        try:
            self.info = audio_io.probe(self.source_path)
            self.duration = self.info.duration
        except audio_io.AudioError as exc:
            self._report_error(exc, "Reload failed")
            return
        self.sel_start, self.sel_end = 0.0, self.duration
        self._redraw_all()
        self._start_analysis()

    def _offer_add_entry(self, dest: str) -> None:
        """A trimmed copy dropped into the loaded music folder is almost
        always meant to become a song in the pack -- offer it, don't
        silently add it.
        """
        if Entry is None:
            return
        folder = getattr(self.app, "music_source_folder", None)
        if not folder:
            return
        if os.path.dirname(os.path.abspath(dest)) != os.path.abspath(folder):
            return
        stem = os.path.splitext(os.path.basename(dest))[0]
        pack = getattr(self.app, "pack", None)
        if pack is None:
            return
        if any(stem in entry.songs for entry in pack.entries):
            return
        if not messagebox.askyesno(
                "Add to songpack",
                f"Add '{stem}' to this songpack as a new entry?", parent=self):
            return
        pack.entries.append(Entry(songs=[stem]))
        try:
            self.app.library_tab.refresh_tree(keep_selection=True)
            self.app.priority_tab.refresh()
        except Exception:  # noqa: BLE001 - refreshing is a nicety, not the job
            pass
        self._set_status(f"Added '{stem}' to the songpack.")

    # -- chrome -----------------------------------------------------------
    def _set_status(self, text: str) -> None:
        try:
            self.status_label.configure(text=text)
        except tk.TclError:
            pass

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        if busy:
            self._set_status(message)
            self.progress.set(0)
            self.progress.pack(side="right", padx=10)
            self._set_controls_enabled(False)
        else:
            try:
                self.progress.pack_forget()
            except tk.TclError:
                pass
            self._set_controls_enabled(self.waveform is not None)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in (self.play_btn, self.stop_btn, self.save_new_btn,
                       self.replace_btn, self.select_all_btn,
                       self.start_entry, self.end_entry):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

    def _on_close(self) -> None:
        if self._busy:
            messagebox.showinfo(
                "Please wait",
                "An audio operation is still running. It will finish in a "
                "moment.", parent=self)
            return
        self._closing = True
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
            self._poll_job = None
        if self._volume_save_job is not None:
            try:
                self.after_cancel(self._volume_save_job)
            except tk.TclError:
                pass
            self._persist_volume()
        self._discard_preview_clip()
        _OPEN.pop(os.path.abspath(self.source_path), None)
        try:
            self.destroy()
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# Ruler helper
# ---------------------------------------------------------------------------
def _nice_step(duration: float, width: int) -> float:
    """A round tick interval giving roughly one label per 90 pixels."""
    target = max(1, int(width / 90))
    raw = max(duration / target, 0.001)
    for step in (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if raw <= step:
            return float(step)
    return 900.0
