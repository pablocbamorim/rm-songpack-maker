"""
app_core.py
-----------
The Tkinter GUI for the ReactiveMusic Songpack Editor.

Tabs:
  1. Songpack Info      -- the global yaml keys (name, author, ...)
  2. Music & Conditions  -- pick a song, check the conditions that should
                            trigger it, see a live preview + rarity score
  3. Simulation Map      -- pick a situation + a biome on the map and see /
                            hear which songs the mod would play (simulator_tab.py)
  4. Priority Order      -- the auto-computed (and freely drag-reorderable)
                            play-priority list
  5. Settings

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
import conditions
import biome_customization
import biome_chart
import mod_versions
import app_settings
import theme
import settings_tab
import simulator_tab
import case_grouping
import scopes
import pack_validation
import biome_tag_platforms
from models import Songpack, Entry, BiomeCondition, DimensionCondition, BlockCondition


# ---------------------------------------------------------------------------
# Typography
# ---------------------------------------------------------------------------
# A small, coherent font scale shared by every widget in the app. Keeping
# the whole scale in one place means future tweaks (or a global "larger
# text" toggle) are a one-line change, and there's no scatter of ad-hoc
# ``font=("", 9, "bold")`` literals.
#
# We deliberately use an empty font *family* so Tk / CustomTkinter resolve
# the native platform default (Segoe UI on Windows, SF Pro / Helvetica on
# macOS, DejaVu Sans on Linux) rather than hard-coding a family that may
# not be installed everywhere.
_BODY = ("", 13)          # normal labels, buttons, entries, checkboxes
_BODY_BOLD = ("", 13, "bold")
_SECTION = ("", 15, "bold")  # card / section headings
_TITLE = ("", 17, "bold")  # editor title, big screen headers
_SMALL = ("", 11)          # secondary / explanatory text
_SMALL_BOLD = ("", 11, "bold")
_TINY = ("", 10)          # rare; used for very compact hints

# ttk.Treeview rows need to grow with the body font or the text gets clipped.
_TREE_ROW_HEIGHT = 30


def _configure_ttk_typography(root: tk.Misc, dark: bool = True) -> None:
    """Push the shared typography scale into every ttk widget class the app
    uses, and theme the ttk.Treeview so it doesn't stand out as a bright
    white slab inside a dark CTk layout.

    Called after ``app_settings.apply_ttk_theme`` because switching ttk
    themes resets the style database -- without this reapplication fonts
    and colors would revert to the platform default on every theme toggle.
    """
    style = ttk.Style(root)

    style.configure("TLabel",       font=_BODY)
    style.configure("TButton",      font=_BODY)
    style.configure("TCheckbutton", font=_BODY)
    style.configure("TRadiobutton", font=_BODY)
    style.configure("TEntry",       font=_BODY)
    style.configure("TCombobox",    font=_BODY)
    style.configure("TSpinbox",     font=_BODY)
    style.configure("TMenubutton",  font=_BODY)
    style.configure("TNotebook.Tab", font=_BODY)

    # Theme-aware Treeview colors so the list views visually belong to the
    # surrounding CTk cards in both appearance modes.
    palette = theme.tree_colors(dark)
    tree_bg, tree_field_bg = palette["background"], palette["field"]
    tree_fg = palette["foreground"]
    tree_sel_bg, tree_sel_fg = palette["selected_bg"], palette["selected_fg"]
    heading_bg, heading_fg = palette["heading_bg"], palette["heading_fg"]

    style.configure(
        "Treeview",
        font=_BODY,
        rowheight=_TREE_ROW_HEIGHT,
        background=tree_bg,
        fieldbackground=tree_field_bg,
        foreground=tree_fg,
        borderwidth=0,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", tree_sel_bg)],
        foreground=[("selected", tree_sel_fg)],
    )
    style.configure(
        "Treeview.Heading",
        font=_BODY_BOLD,
        background=heading_bg,
        foreground=heading_fg,
        relief="flat",
    )
    style.map(
        "Treeview.Heading",
        background=[("active", tree_sel_bg)],
        foreground=[("active", tree_sel_fg)],
    )

    # Named variants for the cases where a section wants to stand apart.
    style.configure("Section.TLabel", font=_SECTION)
    style.configure("Title.TLabel",   font=_TITLE)
    style.configure("Small.TLabel",   font=_SMALL)
    style.configure("Status.TLabel",  font=_SMALL)
# ---------------------------------------------------------------------------
# Smoother wheel scrolling for CTkScrollableFrame
# ---------------------------------------------------------------------------


class _SmoothScrollFrame(ctk.CTkScrollableFrame):
    """CTkScrollableFrame with smoother, slightly faster mouse-wheel scrolling.

    CTk's built-in handler does ``canvas.yview_scroll(int(-delta/120), 'units')``
    against a canvas whose ``yscrollincrement`` is left at Tk's default of 0,
    which makes "one unit" equal 1/10 of the visible canvas height. The wheel
    jump therefore changes size with the window, and on macOS (where delta is
    a small integer, not a multiple of 120) ``int(delta/120)`` collapses to 0
    so nothing scrolls at all.

    Reimplementing ``_mouse_wheel_all`` in a subclass fixes both issues:

      * ``__init__`` pins the canvas scroll unit to 1 pixel, so
        ``yview_scroll(N, 'units')`` moves exactly N pixels.
      * The wheel handler normalises the platform delta and scrolls a fixed
        pixel amount per notch, which is consistent across window sizes and
        reads as smoother, with a small speed bump over the old default.

    Nested-scrollable behaviour is preserved: the mouse-over check is still
    delegated to CTk's own helper, so a nested CTkScrollableFrame keeps
    handling its own wheel events.
    """

    #: Pixels moved per wheel notch (Windows/X11 delta is 120 per notch).
    _PIXELS_PER_NOTCH = 60

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        canvas = getattr(self, "_parent_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(yscrollincrement=1)
            except Exception:
                pass

    def _mouse_wheel_all(self, event):  # noqa: D401 - override of CTk hook
        # CTk binds ``self._mouse_wheel_all`` in its own __init__; because
        # we're a subclass, the inherited binding picks up this override
        # automatically -- no monkeypatching, no risk of tearing down
        # unrelated bind_all handlers.
        checker = (getattr(self, "_check_if_mouse_is_over_this_widget", None)
                   or getattr(self, "check_if_mouse_is_over_this_widget", None))
        if checker is not None:
            try:
                if not checker():
                    return
            except Exception:
                pass

        canvas = getattr(self, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            if canvas.yview() == (0.0, 1.0):
                return
        except Exception:
            return

        delta = getattr(event, "delta", 0)
        if not delta:
            return

        # Windows / X11 send +/-120 per notch. macOS sends small integers
        # (often +/-1..+/-10) that are not multiples of 120; treating those
        # directly as notches keeps trackpads responsive.
        if abs(delta) >= 100:
            notches = delta / 120.0
        else:
            notches = float(delta)
        pixels = int(-notches * self._PIXELS_PER_NOTCH)
        if pixels == 0:
            pixels = -1 if delta > 0 else 1
        try:
            canvas.yview_scroll(pixels, "units")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Shared editor helpers
# ---------------------------------------------------------------------------


def _section(parent, title: str, compact: bool = False):
    """CTk has no LabelFrame. This builds the visual equivalent -- a
    rounded CTkFrame "card" with a bold section header -- and returns the
    *body* frame that section contents should be packed into.

    ``compact=True`` builds a much tighter card with a smaller header:
    used for the fixed checkbox categories, which are tiny groups that
    would otherwise waste most of their card on padding. Full-weight
    sections are still used for the picker-heavy groups (Biome,
    Dimension, Blocks, Advanced, Custom, Priority).
    """
    outer = ctk.CTkFrame(parent, corner_radius=8)

    if compact:
        outer.pack(fill="x", padx=8, pady=2)
        ctk.CTkLabel(
            outer, text=title, font=_SMALL_BOLD, anchor="w",
        ).pack(fill="x", padx=10, pady=(6, 0))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="x", padx=6, pady=(2, 6))
    else:
        outer.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(
            outer, text=title, font=_SECTION, anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 2))
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="x", padx=8, pady=(0, 8))

    return body


def _row(parent) -> ctk.CTkFrame:
    """A transparent row frame for horizontally packing widgets."""
    row = ctk.CTkFrame(parent, fg_color="transparent")
    row.pack(fill="x", padx=4, pady=2)
    return row


# Shared with biome_case_editor.py, which needs the exact same
# "get-or-create the OR/AND map" behaviour for the fixed categories.
_entry_fixed_combine = case_grouping.entry_fixed_combine


def _flow_group(container, widgets, gap_x: int = 14, gap_y: int = 3):
    """Lay out ``widgets`` inside ``container`` in a wrapping flow.

    Widgets are placed left-to-right; when the next widget plus the
    horizontal gap would exceed the container's current pixel width, a new
    grid row is started. The layout is recomputed whenever the container
    resizes, so the same code handles a wide default window and a narrow,
    cramped one -- without a hard-coded column count per category.

    Implementation notes (important for anyone touching this later):

    * Widgets are gridded *directly* into ``container`` -- no reparenting.
      CustomTkinter widgets don't take kindly to ``pack(in_=other)``.
    * ``container.bind("<Configure>", ...)`` on a CTkFrame is routed to
      the frame's internal canvas, so the handler must **not** guard on
      ``event.widget is container`` -- the incoming event's widget is the
      canvas, not the CTk frame. We therefore don't guard at all; a
      re-entrancy flag + ``last_width`` cache keeps things safe.
    * Reflow is synchronous inside the <Configure> handler. That keeps
      the event loop responsive between two rapid clicks, which preserves
      the Treeview's <Double-1> preview behaviour in ui_enhancements.
    """
    state = {"widths": None, "last_width": -1, "busy": False}

    def _apply(width: int) -> None:
        widths = state["widths"]
        # Greedy row packing.
        rows: list[list[int]] = [[]]
        cur = 0
        for i, ww in enumerate(widths):
            if cur > 0 and cur + gap_x + ww > width:
                rows.append([])
                cur = 0
            rows[-1].append(i)
            cur += ww + gap_x

        for w in widgets:
            try:
                w.grid_forget()
            except tk.TclError:
                pass
        for r, row_indices in enumerate(rows):
            for c, i in enumerate(row_indices):
                try:
                    widgets[i].grid(
                        row=r, column=c, sticky="w",
                        padx=(0, gap_x), pady=gap_y,
                    )
                except tk.TclError:
                    pass

    def _on_configure(_event=None) -> None:
        if state["busy"]:
            return
        state["busy"] = True
        try:
            try:
                width = int(container.winfo_width())
            except (tk.TclError, ValueError):
                return
            if width <= 1 or width == state["last_width"]:
                return
            if state["widths"] is None:
                # One-off measurement pass. CTk widgets expose their
                # requested width through the standard Tk geometry API
                # once the interpreter has processed pending idle tasks.
                try:
                    container.update_idletasks()
                except tk.TclError:
                    pass
                widths = []
                for w in widgets:
                    try:
                        widths.append(max(int(w.winfo_reqwidth()), 1))
                    except tk.TclError:
                        widths.append(1)
                state["widths"] = widths
            state["last_width"] = width
            _apply(width)
        finally:
            state["busy"] = False

    # Conservative initial layout (one per row) so nothing overflows the
    # editor before the real width is known. The first <Configure> reflows
    # this to the proper wrapping layout, and every subsequent resize
    # reflows again.
    for i, w in enumerate(widgets):
        try:
            w.grid(row=i, column=0, sticky="w",
                   padx=(0, gap_x), pady=gap_y)
        except tk.TclError:
            pass

    container.bind("<Configure>", _on_configure, add="+")


# ---------------------------------------------------------------------------
# Tab 1: Songpack Info
# ---------------------------------------------------------------------------
class InfoTab(ctk.CTkFrame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent)
        self.app = app
        pad = {"padx": 8, "pady": 5}

        container = ctk.CTkFrame(self)
        container.pack(anchor="nw", padx=10, pady=10)

        self.name_var = tk.StringVar()
        self.version_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.description_var = tk.StringVar()
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
        ]
        r = 0
        for label, var in text_rows:
            ctk.CTkLabel(container, text=label + ":", font=_BODY).grid(
                row=r, column=0, sticky="e", **pad)
            ctk.CTkEntry(container, textvariable=var, width=55 * 8,
                         font=_BODY).grid(
                row=r, column=1, sticky="w", **pad)
            r += 1

        # Credits is a YAML string that may legitimately span several lines
        # (the template's does), so it gets a multi-line box. A single-line
        # entry would show the line breaks as one run of text and made it easy
        # to rewrite them by accident.
        ctk.CTkLabel(container, text="Credits:", font=_BODY).grid(
            row=r, column=0, sticky="ne", **pad)
        self.credits_text = ctk.CTkTextbox(
            container, width=55 * 8, height=84, font=_BODY)
        self.credits_text.grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ctk.CTkLabel(container, text="Music Switch Speed:",
                     font=_BODY).grid(
            row=r, column=0, sticky="e", **pad)
        ctk.CTkComboBox(
            container, variable=self.switch_var, values=C.MUSIC_SWITCH_SPEEDS,
            width=15 * 8, font=_BODY).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ctk.CTkLabel(container, text="Music Delay Length:",
                     font=_BODY).grid(
            row=r, column=0, sticky="e", **pad)
        ctk.CTkComboBox(
            container, variable=self.delay_var, values=C.MUSIC_DELAY_LENGTHS,
            width=15 * 8, font=_BODY).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        # ---- target mod build -------------------------------------------
        ctk.CTkFrame(container, height=2).grid(
            row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        r += 1
        ctk.CTkLabel(
            container, text="Target build (editor only — not written to the YAML)",
            font=_SMALL_BOLD).grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        ctk.CTkLabel(container, text="Minecraft Version:",
                     font=_BODY).grid(
            row=r, column=0, sticky="e", **pad)
        mc_row = ctk.CTkFrame(container, fg_color="transparent")
        mc_row.grid(row=r, column=1, sticky="w", **pad)
        ctk.CTkComboBox(
            mc_row, variable=self.mc_var, values=mod_versions.MC_CHOICES,
            width=22 * 8, font=_BODY).pack(side="left")
        ctk.CTkLabel(
            mc_row, text="(you can also type a version that isn't listed)",
            font=_SMALL, text_color="#888").pack(side="left", padx=(8, 0))
        r += 1

        ctk.CTkLabel(container, text="Reactive Music Version:",
                     font=_BODY).grid(
            row=r, column=0, sticky="e", **pad)
        mod_row = ctk.CTkFrame(container, fg_color="transparent")
        mod_row.grid(row=r, column=1, sticky="w", **pad)
        ctk.CTkComboBox(
            mod_row, variable=self.mod_version_var,
            values=[mod_versions.MOD_VERSION_AUTO] +
            mod_versions.KNOWN_MOD_VERSIONS,
            width=22 * 8, font=_BODY,
        ).pack(side="left")
        r += 1
        self.resolved_label = ctk.CTkLabel(
            container, text="", font=_SMALL,
            text_color="#888", justify="left", wraplength=520)
        self.resolved_label.grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        ctk.CTkLabel(container, text="Mod Platform:",
                     font=_BODY).grid(
            row=r, column=0, sticky="e", **pad)
        ctk.CTkComboBox(
            container, variable=self.platform_var,
            values=mod_versions.PLATFORM_CHOICES, width=22 * 8, font=_BODY,
        ).grid(row=r, column=1, sticky="w", **pad)
        r += 1
        ctk.CTkLabel(
            container, text=mod_versions.PLATFORM_NOTE,
            font=_SMALL, text_color="#888", justify="left").grid(
                row=r, column=1, sticky="w", padx=8)
        r += 1

        for var in (self.mc_var, self.mod_version_var, self.platform_var):
            var.trace_add("write", lambda *_: self._on_target_changed())

        ctk.CTkFrame(container, height=2).grid(
            row=r, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        r += 1

        ctk.CTkLabel(container, text="Entries root key:",
                     font=_BODY).grid(
            row=r, column=0, sticky="e", **pad)
        ctk.CTkEntry(container, textvariable=self.root_key_var,
                     width=20 * 8, font=_BODY).grid(
                         row=r, column=1, sticky="w", **pad)
        r += 1
        ctk.CTkLabel(
            container,
            text=("Auto-detected when you load an existing file. MAKING_SONGPACKS.md doesn't\n"
                  "show this key explicitly, so only change it if your installed mod version\n"
                  "expects something other than the default ('entries')."),
            font=_SMALL, text_color="#888", justify="left",
        ).grid(row=r, column=1, sticky="w", padx=8)
        r += 1

        ctk.CTkButton(self, text="Apply changes", font=_BODY,
                      command=self._apply_clicked).pack(
            anchor="w", padx=10, pady=(0, 10))
        ctk.CTkLabel(
            self,
            text="(Changes here are also applied automatically when you switch tabs or save.)",
            font=_SMALL, text_color="#888",
        ).pack(anchor="w", padx=10)

    def _apply_clicked(self):
        self.pull_into_pack()
        self.app.mark_dirty()
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
        self.resolved_label.configure(text=explanation)

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
        self.credits_text.delete("1.0", "end")
        self.credits_text.insert("1.0", p.credits or "")
        self.switch_var.set(p.music_switch_speed)
        self.delay_var.set(p.music_delay_length)
        self.root_key_var.set(p.entries_root_key)

    def pull_into_pack(self):
        p = self.app.pack
        p.name = self.name_var.get()
        p.version = self.version_var.get()
        p.author = self.author_var.get()
        p.description = self.description_var.get()
        p.credits = self.credits_text.get("1.0", "end-1c")
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
# Cases: several sets of trigger conditions for the same song
# ---------------------------------------------------------------------------
# A "case" is one set of conditions under which a song plays. In
# ReactiveMusic.yaml a case is simply its own entry (its own ``events`` list
# and flags) that lists the same song, so the editor models "a song with N
# cases" as N ``Entry`` objects that happen to share a primary song. Because
# every case is still an ordinary entry, priority ordering, the simulator,
# mod-version checks and YAML saving all keep working unchanged, and each
# case takes its own place in the priority order (a rare case can sit high
# while a broad case of the same song sits low). A case's "number" (Case 1,
# Case 2, ...) is just its position among same-song entries in priority
# order -- see case_grouping.py.
#
# Song-centric ("cases of a song", used below) and biome-centric ("cases of
# a biome", see biome_case_editor.py -- right-click a biome on the Biome
# Simulator map) grouping both live in case_grouping.py, computed purely
# from each entry's own data (primary song text / biome conditions) rather
# than a separate id kept on the side. That is what makes the two tabs
# automatically agree with each other: there is only one underlying list,
# app.pack.entries, and both are just different groupings of it -- editing
# from either one is immediately visible in the other, nothing to resync by
# hand, and nothing extra to round-trip through a save/load.
# ---------------------------------------------------------------------------
_gid = case_grouping.gid
_group_by_song = case_grouping.group_by_song
_group_of = case_grouping.group_of
_add_case_to = case_grouping.add_case_to
_case_labels = case_grouping.case_labels


def _summarize_group(entries, max_len: int = 120) -> str:
    """Condition preview for a song row: one summary per case, numbered."""
    if len(entries) == 1:
        return condition_logic.summarize_entry(entries[0])
    parts = []
    for number, entry in enumerate(entries, start=1):
        events = condition_logic.build_events(entry)
        parts.append(f"{number}: " + (" & ".join(events)
                     if events else "(always)"))
    text = "  \u2502  ".join(parts)
    if len(text) > max_len:
        text = text[: max_len - 1] + "\u2026"
    return text


# ---------------------------------------------------------------------------
# Tab 2: Music & Conditions
# ---------------------------------------------------------------------------
class LibraryTab(ctk.CTkFrame):
    # Prefix shown next to entries that have no trigger conditions set yet
    # (i.e. they'd "always match" -- usually a sign the user forgot to
    # configure them, so we flag it visually in the list).
    WARNING_PREFIX = "\u26a0 "  # ⚠

    # Biome Map dimension-filter labels, mapped to the ids used in
    # default_biome_colors.json's "biome_dimensions" block.
    _CHART_DIMENSIONS = ["All", "Overworld", "Nether", "End"]
    _CHART_DIMENSION_IDS = {
        "Overworld": "minecraft:overworld",
        "Nether": "minecraft:the_nether",
        "End": "minecraft:the_end",
    }
    # Biome Map mode selector: the same chart shows biomes or biome tags.
    _CHART_MODE_BIOMES = "Biomes"
    _CHART_MODE_TAGS = "Biome tags"

    def __init__(self, parent, app: "App"):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.selected_entry_id = None
        self.selected_entry_ids: list[str] = []
        self.category_vars = {}  # cat -> {option: BooleanVar}
        # cat -> StringVar tracking the fixed-category OR/AND combine
        # mode currently displayed in the editor.
        self.fixed_combine_vars: dict = {}
        # Set while refresh_tree() re-sets the Treeview selection, so
        # _on_select() doesn't rebuild the condition editor in response to
        # a purely internal refresh. See _on_select for the full story.
        self._suppress_select_rebuild = False
        # What the editor is currently displaying: (selected tree rows,
        # active case). Used to skip redundant rebuilds when Tk re-emits
        # <<TreeviewSelect>> for the same selection (e.g. the second click
        # of a double-click).
        self._editor_showing_key = None
        # Cases: index (0 = "Case 1") of the case tab being edited, and the
        # tab buttons currently in the case bar. See "cases" section below.
        self.active_case = 0
        self._case_tab_buttons: list = []
        self._case_bar_visible = False
        self._multi_group_count = 0
        # Biome Map view state. Lives on the tab (not per-entry) so
        # switching songs doesn't reset the user's filter or collapse
        # state. Also initialised here -- not just in _clear_editor() --
        # because _build_biome_map_section() reads them the first time an
        # entry is selected, before _clear_editor() has ever run.
        self._biome_map_collapsed = False
        self._biome_map_dimension = "All"
        self._biome_map_mode = "biomes"      # "biomes" | "tags"
        self.biome_map = None
        self.biome_map_container = None

        # ---- left: entry list -------------------------------------------------
        left = ctk.CTkFrame(self, corner_radius=10)
        left.pack(side="left", fill="y", padx=(8, 4), pady=8)
        self.left = left

        btn_row = ctk.CTkFrame(left, fg_color="transparent")
        btn_row.pack(fill="x", padx=6, pady=(6, 0))
        ctk.CTkButton(btn_row, text="+ Add Entry", width=90, font=_BODY,
                      command=self._add_blank_entry).pack(side="left", padx=2)
        # Lambda so that ui_enhancements.install()'s reassignment of
        # app.action_load_music_folder is picked up regardless of when
        # install() runs relative to tab construction.
        ctk.CTkButton(btn_row, text="Load Music Folder…", width=150, font=_BODY,
                      command=lambda: self.app.action_load_music_folder()).pack(
                          side="left", padx=2)
        ctk.CTkButton(btn_row, text="Remove", width=80, font=_BODY,
                      **theme.DANGER_BUTTON,
                      command=self._remove_selected).pack(side="left", padx=2)

        # The collapse/expand control lives in the *left* panel so it stays
        # reachable when the right-side editor is fully forgotten (which is
        # how the collapsed state actually frees the horizontal space).
        self.toggle_btn = ctk.CTkButton(
            btn_row, text="▾ Hide editor", width=110, font=_BODY,
            command=self._toggle_editor)
        self.toggle_btn.pack(side="right", padx=2)

        # -- search box: filter the entry list by song name --
        search_row = ctk.CTkFrame(left, fg_color="transparent")
        search_row.pack(fill="x", padx=6, pady=(6, 0))
        ctk.CTkLabel(search_row, text="Search:", font=_BODY).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(
            search_row, textvariable=self.search_var, font=_BODY)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.search_var.trace_add(
            "write", lambda *_: self.refresh_tree(keep_selection=True))
        ctk.CTkButton(search_row, text="✕", width=28, font=_BODY,
                      command=lambda: self.search_var.set("")).pack(
                          side="left", padx=(4, 0))

        columns = ("song", "summary", "score")
        self.tree = ttk.Treeview(
            left, columns=columns, show="headings", selectmode="extended", height=20)
        self.tree.heading("song", text="Song")
        self.tree.heading("summary", text="Conditions (preview)")
        self.tree.heading("score", text="Rarity")
        self.tree.column("song", width=210, anchor="w")
        self.tree.column("summary", width=300, anchor="w")
        self.tree.column("score", width=65, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=6, pady=(8, 6))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # ui_enhancements adds a <Double-1> binding here with add="+".

        # ---- right: condition editor -------------------------------------------
        # Stored as self.right so _toggle_editor() can pack_forget()/re-pack
        # the entire panel -- that's what actually removes the editor's
        # width from the layout when collapsed.
        self.right = ctk.CTkFrame(self, corner_radius=10)
        self.right.pack(side="left", fill="both", expand=True,
                        padx=(4, 8), pady=8)

        header = ctk.CTkFrame(self.right, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(10, 4))
        self.editor_title = ctk.CTkLabel(
            header,
            text="Select a song on the left to view/edit its trigger conditions.",
            font=_TITLE, anchor="w", justify="left",
        )
        self.editor_title.pack(side="left", fill="x", expand=True)

        # Compact access to the underlying song list. The main editor is
        # for conditions; this button opens a small dialog for the rare
        # case where an entry needs extra songs added/removed.
        self.edit_songs_btn = ctk.CTkButton(
            header, text="Edit songs…", width=110, font=_BODY,
            state="disabled", command=self._edit_songs_clicked,
        )
        self.edit_songs_btn.pack(side="right", padx=(0, 6))

        # Opens the basic waveform/trim editor for the selected song's
        # audio file (audio_editor.py). Same single-selection rule as
        # "Edit songs…" -- see _update_edit_songs_btn().
        self.edit_audio_btn = ctk.CTkButton(
            header, text="Edit audio…", width=110, font=_BODY,
            state="disabled", command=self._edit_audio_clicked,
        )
        self.edit_audio_btn.pack(side="right", padx=(0, 6))

        # Case tabs ("Case 1", "Case 2", ... + "Add case"). Built and shown
        # by _refresh_case_bar() once a song is selected; packed between the
        # header and the editor so it stays put while the editor scrolls.
        self.case_bar = ctk.CTkFrame(self.right, fg_color="transparent")

        # editor_outer stays as a plain container so _toggle_editor() and
        # App.on_target_changed()/on_biome_colors_changed() can keep using
        # pack_forget()/winfo_ismapped() exactly as before.
        self.editor_outer = ctk.CTkFrame(self.right, fg_color="transparent")
        self.editor_outer.pack(fill="both", expand=True, padx=6, pady=(4, 8))

        self.editor_frame = _SmoothScrollFrame(
            self.editor_outer, fg_color="transparent")
        self.editor_frame.pack(fill="both", expand=True)

        ctk.CTkLabel(
            self.editor_frame,
            text="Select a song from the list on the left to configure what makes it play.",
            font=_BODY,
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", padx=10, pady=12)

    # -- themed raw-tk widgets (no CTk equivalent) ---------------------------
    def _themed_listbox(self, parent, height: int) -> tk.Listbox:
        dark = bool(self.app.settings.get("dark_theme", True))
        return tk.Listbox(
            parent, height=height, font=_BODY,
            **theme.listbox_colors(dark),
            highlightthickness=0, borderwidth=0, activestyle="none",
        )

    # -- list management -------------------------------------------------
    def refresh_tree(self, keep_selection=False):
        prev = list(self.selected_entry_ids) if keep_selection else []
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().lower()
        # One row per SONG. A song with several cases is a single row whose
        # iid is its first case's entry id (so every consumer that looks the
        # selected row up in pack.entries -- preview, audio editor -- lands
        # on that song's primary entry).
        for group in _group_by_song(self.app.pack.entries):
            if query and not any(query in s.lower()
                                 for e in group for s in e.songs):
                continue
            primary = group[0]
            # A YAML entry can hold a POOL of songs; show every song of the
            # row instead of only the first ("A + B, C").
            pool = case_grouping.pool_songs(group)
            name = primary.display_name()
            if len(pool) > 1:
                extra = ", ".join(pool[1:4])
                if len(pool) > 4:
                    extra += f", +{len(pool) - 4} more"
                name = f"{pool[0]}  +  {extra}"
            if len(group) > 1:
                name += f"  \u00b7  {len(group)} cases"
            marks = sorted({e.scope for e in group
                            if e.scope != C.SCOPE_NORMAL})
            if marks:
                name += "  \u00b7  " + "/".join(marks)
            if any(not e.has_any_condition() for e in group):
                name = self.WARNING_PREFIX + name
            self.tree.insert(
                "", "end", iid=primary.id,
                values=(name, _summarize_group(group),
                        max(priority.score_entry(e) for e in group)),
            )
        valid_prev = [iid for iid in prev if self.tree.exists(iid)]
        if valid_prev:
            # selection_set() fires <<TreeviewSelect>>; without this guard
            # _on_select() would rebuild the condition editor every time
            # this method runs (i.e. on every condition change), causing
            # the editor to visibly flash. The selection itself hasn't
            # actually changed from the user's point of view, so the
            # rebuild is redundant.
            self._suppress_select_rebuild = True
            try:
                self.tree.selection_set(valid_prev)
            finally:
                self._suppress_select_rebuild = False
        elif not keep_selection and self.selected_entry_ids:
            # A different songpack was loaded/created: the songs the editor
            # was showing no longer exist, so don't leave their widgets (and
            # case tabs) on screen.
            alive = {e.id for e in self.app.pack.entries}
            if not any(i in alive for i in self.selected_entry_ids):
                self.selected_entry_ids = []
                self.selected_entry_id = None
                self._clear_editor(
                    "Select a song from the list on the left to configure what makes it play.")

    def _add_blank_entry(self):
        name = simpledialog.askstring(
            "Add Entry", "Song filename (without extension), e.g. MyTrack:",
            parent=self,
        )
        if name is None:
            return
        entry = Entry(songs=[name.strip()] if name.strip() else [])
        self.app.pack.entries.append(entry)
        # New entries are normal ones: keep them above global/default entries.
        priority.enforce_scope_order(self.app.pack.entries)
        self.app.mark_dirty()
        self.refresh_tree()
        self.tree.selection_set(entry.id)
        self.tree.see(entry.id)
        self.app.priority_tab.refresh()
        self.app.set_status(
            f"Added entry '{entry.display_name()}'. Configure its conditions below.")

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        # A row is a whole song, so removing it removes all of its cases.
        selected_rows = set(sel)
        groups = [g for g in _group_by_song(self.app.pack.entries)
                  if g[0].id in selected_rows]
        ids_to_remove = {e.id for g in groups for e in g}
        if not groups:
            return

        if len(groups) == 1:
            msg = f"Remove '{groups[0][0].display_name()}' from the songpack?"
            if len(groups[0]) > 1:
                msg += f"\n\nThis also removes its {len(groups[0])} cases."
        else:
            names = ", ".join(g[0].display_name() for g in groups[:5])
            if len(groups) > 5:
                names += f", +{len(groups) - 5} more"
            msg = f"Remove {len(groups)} songs from the songpack?\n\n{names}"

        if not messagebox.askyesno("Remove entry", msg):
            return

        self.app.pack.entries = [
            e for e in self.app.pack.entries if e.id not in ids_to_remove]
        self.app.mark_dirty()

        self.selected_entry_ids = [
            i for i in self.selected_entry_ids if i not in ids_to_remove]
        if self.selected_entry_id in ids_to_remove:
            self.selected_entry_id = None
        if not self.selected_entry_ids:
            self._clear_editor(
                "Select a song from the list on the left to configure what makes it play.")

        self.refresh_tree()
        self.app.priority_tab.refresh()
        self._update_edit_songs_btn()

    def _on_select(self, _event=None):
        sel = self.tree.selection()
        self._update_edit_songs_btn()
        if not sel:
            return
        # A genuinely different selection starts on "Case 1" again.
        if frozenset(sel) != frozenset(self.selected_entry_ids):
            self.active_case = 0
        self.selected_entry_ids = list(sel)
        groups = self._selected_groups()

        if len(groups) == 1:
            self.selected_entry_id = groups[0][0].id
        elif len(groups) > 1:
            self.selected_entry_id = None

        # refresh_tree() re-sets the selection after rebuilding the list,
        # which re-fires <<TreeviewSelect>>. The selected entry hasn't
        # actually changed in that case, and the editor already reflects
        # its current state -- so skip the (visibly expensive) rebuild to
        # avoid the double/triple flash the user sees on every condition
        # edit. Selection IDs above are still kept in sync.
        if self._suppress_select_rebuild:
            return

        # If the resolved selection is exactly what the editor is already
        # showing, don't destroy and rebuild every widget. This is what
        # makes the second click of a double-click stop re-rendering the
        # editor while the <Double-1> preview handler runs.
        if groups and (frozenset(sel), self.active_case) == self._editor_showing_key:
            return

        self.rebuild_editor()

    def _update_edit_songs_btn(self):
        """The 'Edit songs…' and 'Edit audio…' actions only make sense for
        a single entry. Keep them disabled during multi-selection or when
        nothing is selected.
        """
        sel = self.tree.selection()
        state = "normal" if len(sel) == 1 and self.tree.exists(
            sel[0]) else "disabled"
        self.edit_songs_btn.configure(state=state)
        self.edit_audio_btn.configure(state=state)

    # -- multi-edit state helpers ------------------------------------------
    def _option_state(self, entries, cat, opt):
        statuses = [opt in e.selected.get(cat, set()) for e in entries]
        if all(statuses):
            return "all"
        if not any(statuses):
            return "none"
        return "some"

    def _bool_state(self, entries, attr):
        statuses = [bool(getattr(e, attr)) for e in entries]
        if all(statuses):
            return "all"
        if not any(statuses):
            return "none"
        return "some"

    def _apply_option_to_all(self, entries, cat, opt, turn_on):
        for e in entries:
            s = e.selected.setdefault(cat, set())
            s.add(opt) if turn_on else s.discard(opt)
        self._refresh_after_multi_change(entries)

    def _apply_bool_to_all(self, entries, attr, turn_on):
        for e in entries:
            setattr(e, attr, turn_on)
        self._refresh_after_multi_change(entries)

    def _apply_combine_to_all(self, entries, cat, value):
        """Multi-selection: apply the chosen OR/AND mode to every selected
        entry's fixed-combine setting for one category, then rebuild.
        """
        for e in entries:
            _entry_fixed_combine(e)[cat] = value
        self._refresh_after_multi_change(entries)

    def _refresh_after_multi_change(self, entries):
        self._build_multi_editor_for(entries)
        self.refresh_tree(keep_selection=True)
        self.app.priority_tab.refresh()

    def _multi_state_button(self, parent, label, state, on_click, enabled=True):
        """A CTkButton-shaped toggle used for multi-selection editing.

        CTkCheckBox has no tristate support, so we render state (on / off /
        mixed) explicitly via text and colour instead. Behaviour matches
        the original ttk.Checkbutton: clicking an all-on option turns it
        off for the whole selection; clicking anything else turns it on.
        """
        if state == "all":
            text = "\u2611 " + label            # ☑
            fg, hover, tc = theme.TAB_ON
        elif state == "some":
            text = "\u25A3 " + label            # ▣
            fg, hover, tc = theme.TAB_MIXED
        else:
            text = "\u2610 " + label            # ☐
            fg, hover, tc = theme.TAB_OFF

        btn = ctk.CTkButton(
            parent, text=text, command=on_click, font=_BODY,
            fg_color=fg, hover_color=hover, text_color=tc,
            corner_radius=6, height=28,
        )
        if not enabled:
            btn.configure(state="disabled")
        return btn

    def _build_multi_editor_for(self, entries):
        """``entries`` are the case entries being edited together: Case N of
        every selected song that has a Case N (see rebuild_editor).
        """
        self._editor_showing_key = (
            frozenset(self.selected_entry_ids), self.active_case)
        for w in self.editor_frame.winfo_children():
            w.destroy()

        skipped = self._multi_group_count - len(entries)
        scope = (f"Editing Case {self.active_case + 1} of {len(entries)} "
                 f"song{'s' if len(entries) != 1 else ''} at once.")
        if skipped > 0:
            scope += (f" ({skipped} selected song{'s' if skipped != 1 else ''} "
                      "without this case left alone.)")
        ctk.CTkLabel(
            self.editor_frame,
            text=(scope + "  "
                  "Clicking an off/mixed option turns it on for all selected; "
                  "clicking an all-on option turns it off for all selected."),
            font=_SMALL,
            text_color=("gray40", "gray70"), justify="left", anchor="w",
            wraplength=680,
        ).pack(anchor="w", padx=10, pady=(8, 4))

        self._target_banner(self.editor_frame)

        for cat in C.FIXED_CATEGORY_ORDER:
            definition = C.FIXED_CATEGORIES[cat]

            body = _section(
                self.editor_frame,
                definition['label'],
                compact=True,
            )

            # Combine mode: multi-selection reflects the first entry's
            # current choice, and changing it applies to all selected.
            fc_first = _entry_fixed_combine(entries[0])
            mode_var = tk.StringVar(value=fc_first.get(cat, C.COMBINE_OR))

            combine_row = ctk.CTkFrame(body, fg_color="transparent")
            combine_row.pack(fill="x", padx=4, pady=(0, 2))
            ctk.CTkLabel(
                combine_row, text="Combine checked options with:",
                font=_SMALL, text_color=("gray40", "gray70"),
            ).pack(side="left")
            ctk.CTkSegmentedButton(
                combine_row, values=[C.COMBINE_OR, C.COMBINE_AND],
                variable=mode_var, font=_BODY,
                command=lambda v, c=cat: self._apply_combine_to_all(
                    entries, c, v),
            ).pack(side="left", padx=8)

            grid = ctk.CTkFrame(body, fg_color="transparent")
            grid.pack(fill="x")
            widgets = []
            for opt in definition["options"]:
                state = self._option_state(entries, cat, opt)
                available = self._supports(opt)
                label = self._option_label(opt, available)

                def on_click(c=cat, o=opt, s=state):
                    self._apply_option_to_all(
                        entries, c, o, turn_on=(s != "all"))

                enabled = available or state != "none"
                btn = self._multi_state_button(
                    grid, label, state, on_click, enabled=enabled,
                )
                widgets.append(btn)
            # Wrapping flow: as many per row as fit at the current width.
            _flow_group(grid, widgets)

        adv_body = _section(
            self.editor_frame, "Advanced / Fallback Behaviour", compact=True)
        adv_grid = ctk.CTkFrame(adv_body, fg_color="transparent")
        adv_grid.pack(fill="x")
        for i, (attr, label) in enumerate([
            ("allow_fallback", "allowFallback"),
            ("force_stop_on_changed", "forceStopMusicOnChanged"),
            ("force_stop_on_valid", "forceStopMusicOnValid"),
            ("force_stop_on_invalid", "forceStopMusicOnInvalid"),
            ("force_start_on_valid", "forceStartMusicOnValid"),
        ]):
            state = self._bool_state(entries, attr)
            available = self._supports(attr)
            display = label if available else label + self._gate_suffix(attr)

            def on_click(a=attr, s=state):
                self._apply_bool_to_all(entries, a, turn_on=(s != "all"))

            enabled = available or state != "none"
            btn = self._multi_state_button(
                adv_grid, display, state, on_click, enabled=enabled,
            )
            btn.grid(row=i, column=0, sticky="w", padx=(0, 8), pady=1)

        ctk.CTkLabel(
            self.editor_frame,
            text=("Biome, dimension, nearby blocks and custom conditions can only be\n"
                  "edited with one song selected at a time."),
            font=_SMALL,
            text_color=("gray40", "gray70"), justify="left", anchor="w",
        ).pack(anchor="w", padx=10, pady=(6, 8))

    def _clear_editor(self, message):
        self._editor_showing_key = None
        self.active_case = 0
        self._hide_case_bar()
        # Biome Map view state. Kept on the tab (not rebuilt per entry) so
        # switching songs doesn't reset the user's filter or force the map
        # back open after they've collapsed it.
        self._biome_map_collapsed = False
        self._biome_map_dimension = "All"
        self._biome_map_mode = "biomes"
        for w in self.editor_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self.editor_frame, text=message, font=_BODY,
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", padx=10, pady=12)
        self.editor_title.configure(
            text="Select a song on the left to view/edit its trigger conditions.")
        self._update_edit_songs_btn()

    def _toggle_editor(self):
        """Collapse/expand the right-hand condition editor.

        When collapsed we forget the *entire* right panel (not just the
        scroll area inside it), which is what actually hands the freed
        horizontal space back to the left panel. The toggle button itself
        lives in the left panel's button row so it stays reachable.
        """
        if self.right.winfo_ismapped():
            # Collapse: drop the right panel entirely and let the left
            # panel expand into the freed width.
            self.right.pack_forget()
            self.left.pack_configure(fill="both", expand=True)
            self.toggle_btn.configure(text="▸ Show editor")
        else:
            # Expand: put the left panel back to its natural width and
            # re-attach the right panel. Rebuild the editor content for
            # whatever entry is currently selected, since while collapsed
            # _on_select() skipped the (invisible) rebuild.
            self.left.pack_configure(fill="y", expand=False)
            self.right.pack(side="left", fill="both", expand=True,
                            padx=(4, 8), pady=8)
            self.toggle_btn.configure(text="▾ Hide editor")

            self.rebuild_editor(force=True)

    # -- cases: several condition sets for one song --------------------------
    # The tab bar above the editor has one tab per case. Each tab edits one
    # Entry (see the case helpers above LibraryTab), so switching tabs simply
    # rebuilds the ordinary single-entry editor for that entry.
    _TAB_ON = theme.TAB_ON
    _TAB_OFF = theme.TAB_OFF

    def _selected_groups(self) -> list:
        """One list of case entries (Case 1, Case 2, ...) per selected song."""
        pack = self.app.pack
        by_id = {e.id: e for e in pack.entries}
        order: list = []
        seen: set = set()
        for iid in self.selected_entry_ids:
            entry = by_id.get(iid)
            if entry is not None and _gid(entry) not in seen:
                seen.add(_gid(entry))
                order.append(_gid(entry))
        if not order:
            return []
        members: dict = {gid: [] for gid in order}
        for entry in pack.entries:
            # Iterating pack.entries in order already yields each song's
            # cases in priority order -- no separate case-order key needed.
            if _gid(entry) in members:
                members[_gid(entry)].append(entry)
        return [members[gid] for gid in order]

    def rebuild_editor(self, force: bool = False, refresh_bar: bool = True):
        """(Re)build the case tabs and the editor for the current selection
        and active case. Skips the (expensive) editor rebuild while the
        editor is collapsed unless ``force``.
        """
        groups = self._selected_groups()
        if not groups:
            return
        entries = None
        if len(groups) == 1:
            group = groups[0]
            self.active_case = max(0, min(self.active_case, len(group) - 1))
            self.editor_title.configure(
                text=f"Conditions for: {group[0].display_name()}")
        else:
            widest = max(len(g) for g in groups)
            self.active_case = max(0, min(self.active_case, widest - 1))
            entries = [g[self.active_case]
                       for g in groups if len(g) > self.active_case]
            self._multi_group_count = len(groups)
            self.editor_title.configure(
                text=f"Editing {len(groups)} songs at once")

        if refresh_bar:
            self._refresh_case_bar(groups)
        else:
            self._restyle_case_tabs()

        if not (force or self.editor_outer.winfo_ismapped()):
            return
        if entries is None:
            self._build_editor_for(groups[0][self.active_case])
        else:
            self._build_multi_editor_for(entries)

    def _show_case_bar(self):
        if not self._case_bar_visible:
            self.case_bar.pack(fill="x", padx=10, pady=(0, 4),
                               before=self.editor_outer)
            self._case_bar_visible = True

    def _hide_case_bar(self):
        for w in self.case_bar.winfo_children():
            w.destroy()
        self._case_tab_buttons = []
        if self._case_bar_visible:
            self.case_bar.pack_forget()
            self._case_bar_visible = False

    def _refresh_case_bar(self, groups: list):
        """Rebuild the tab bar. One song selected: its cases + "Add case" and
        "Remove case". Several songs selected: Case 1..N tabs (N = the most
        cases any selected song has); hidden when nobody has more than one.
        """
        for w in self.case_bar.winfo_children():
            w.destroy()
        self._case_tab_buttons = []
        single = len(groups) == 1
        count = len(groups[0]) if single else max(len(g) for g in groups)
        if not single and count <= 1:
            self._hide_case_bar()
            return
        self._show_case_bar()

        top = ctk.CTkFrame(self.case_bar, fg_color="transparent")
        top.pack(fill="x")
        tabs = ctk.CTkFrame(top, fg_color="transparent")
        tabs.pack(side="left", fill="x", expand=True)

        if single:
            ctk.CTkButton(
                top, text="Remove case", width=110, font=_BODY,
                **theme.DANGER_BUTTON,
                state="normal" if count > 1 else "disabled",
                command=self._remove_case,
            ).pack(side="right", padx=(6, 0), anchor="n")

        # Tabs and the "+" button share one wrapping flow, so many cases
        # wrap onto extra rows instead of running off the panel.
        widgets = []
        for index in range(count):
            button = ctk.CTkButton(
                tabs, text=f"Case {index + 1}", width=96, height=30,
                corner_radius=6, font=_BODY,
                command=lambda n=index: self._select_case(n))
            widgets.append(button)
            self._case_tab_buttons.append(button)
        if single:
            widgets.append(ctk.CTkButton(
                tabs, text="+ Add case", width=110, height=30,
                corner_radius=6, font=_BODY, fg_color="transparent",
                border_width=1, text_color=theme.OUTLINE_TEXT,
                hover_color=theme.OUTLINE_HOVER,
                command=self._add_case))
        _flow_group(tabs, widgets, gap_x=6, gap_y=2)

        ctk.CTkLabel(
            self.case_bar,
            text=("A song plays whenever ANY of its cases matches. Each case has its own "
                  "conditions and advanced settings." if single else
                  "Editing the same case number across the selected songs; songs that "
                  "don't have it are left alone. Select a single song to add or remove cases."),
            font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
            justify="left", wraplength=620,
        ).pack(fill="x", padx=4, pady=(2, 0))
        self._restyle_case_tabs()

    def _restyle_case_tabs(self):
        """Highlight the active tab, and flag single-song cases that have no
        conditions yet (they would always match).
        """
        buttons = self._case_tab_buttons
        if not buttons:
            return
        groups = self._selected_groups()
        group = groups[0] if len(groups) == 1 else None
        for index, button in enumerate(buttons):
            text = f"Case {index + 1}"
            if group is not None and index < len(group) \
                    and not group[index].has_any_condition():
                text = self.WARNING_PREFIX + text
            fg, hover, tc = (self._TAB_ON if index == self.active_case
                             else self._TAB_OFF)
            try:
                button.configure(text=text, fg_color=fg, hover_color=hover,
                                 text_color=tc)
            except tk.TclError:
                pass

    def _select_case(self, index: int):
        if index == self.active_case:
            return
        self.active_case = index
        self.rebuild_editor(refresh_bar=False)

    def _add_case(self):
        groups = self._selected_groups()
        if len(groups) != 1:
            return
        group = groups[0]
        new_entry = _add_case_to(self.app.pack, group[0].id)
        if new_entry is None:
            return
        self.app.mark_dirty()
        # A new case is a normal one, so it may have to hop above a
        # global/default case of the same song; re-derive row and tab.
        priority.enforce_scope_order(self.app.pack.entries)
        group = _group_of(self.app.pack, new_entry.id)
        row_id = group[0].id
        self.selected_entry_ids = [row_id]
        self.selected_entry_id = row_id
        self.active_case = group.index(new_entry)
        self.refresh_tree(keep_selection=True)
        self.rebuild_editor()
        self.app.priority_tab.refresh()
        self.app.set_status(
            f"Added Case {self.active_case + 1} to '{group[0].display_name()}'. Set its "
            "conditions below, then use Priority Order > Auto-arrange to place it.")

    def _remove_case(self):
        groups = self._selected_groups()
        if len(groups) != 1 or len(groups[0]) < 2:
            return
        group = groups[0]
        index = max(0, min(self.active_case, len(group) - 1))
        victim = group[index]
        if not messagebox.askyesno(
                "Remove case",
                f"Remove Case {index + 1} from '{group[0].display_name()}'?\n\n"
                "The song stays in the songpack; only this case's conditions "
                "are deleted."):
            return
        old_row = group[0].id
        remaining = [e for e in group if e.id != victim.id]
        self.app.pack.entries = [
            e for e in self.app.pack.entries if e.id != victim.id]
        self.app.mark_dirty()
        # The row is keyed by the first case, which may just have been removed.
        new_row = remaining[0].id
        self.selected_entry_ids = [
            new_row if i == old_row else i for i in self.selected_entry_ids]
        self.selected_entry_id = new_row
        self.active_case = max(0, min(index, len(remaining) - 1))
        self.refresh_tree(keep_selection=True)
        self.rebuild_editor()
        self.app.priority_tab.refresh()
        self.app.set_status(
            f"Removed Case {index + 1} from '{remaining[0].display_name()}'.")

    # -- helpers -------------------------------------------------
    def _available_biome_values(self, entry: Entry, is_tag: bool):
        """Biome/biome-tag options not already added to this entry, so the
        picker doesn't keep offering values that are already selected.
        Includes both the built-in list and any custom biomes/tags the
        user has defined for this songpack.
        """
        builtins = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
        if is_tag:
            builtins = [b for b in builtins if self._tag_supported(b)]
        custom = self.app.biome_custom_tags if is_tag else self.app.biome_custom_biomes
        used = {b.value for b in entry.biomes if b.is_tag == is_tag}
        return [v for v in [*builtins, *custom] if v not in used]

    def _biome_color(self, value: str, is_tag: bool) -> str:
        """Colour for a biome or biome tag. A songpack override wins; a tag
        without one is the average of the colours of the biomes it contains
        (each resolved through this same method, so recoloured biomes carry
        through), then falls back to the automatic colour.
        """
        custom = self.app.biome_custom_tags if is_tag else self.app.biome_custom_biomes
        if value in custom:
            return custom[value]
        if is_tag:
            averaged = biome_customization.tag_color(
                value, lambda biome: self._biome_color(biome, False))
            if averaged:
                return averaged
        return biome_customization.default_color(value, is_tag)

    # -- option labels (gate suffix) ----------------------------------------
    def _option_label(self, opt: str, available: bool = True) -> str:
        """Return the checkbox label for a single fixed option."""
        text = opt
        if not available:
            text += self._gate_suffix(opt)
        return text

    # -- target mod version gating -------------------------------------------
    def _supports(self, feature: str) -> bool:
        """Does the songpack's target mod build have this condition? With
        no target chosen this is always True, so the editor never gets in
        the way until you've told it what you're building for.
        """
        return mod_versions.supports(self.app.effective_mod_version(), feature)

    # add near _supports()/_gate_suffix()
    def _tag_supported(self, tag: str) -> bool:
        """Is this BIOMETAG= tag registered on the songpack's target platform?
        With no platform chosen, or no data for this tag, nothing is filtered --
        see biome_tag_platforms.py for the philosophy and how to fill in data.
        """
        return biome_tag_platforms.tag_available(
            tag, self.app.pack.platform, self.app.pack.minecraft_version)

    @staticmethod
    def _gate_suffix(feature: str) -> str:
        req = mod_versions.requirement(feature)
        return f"  (needs RM {req}+)" if req else ""

    def _target_banner(self, parent):
        """One line at the top of the editor saying what's being targeted,
        so a greyed-out checkbox is never a mystery.
        """
        version = self.app.effective_mod_version()
        if not version:
            text = ("No target build set — every documented condition is available. "
                    "Set a Minecraft version in the Songpack Info tab to have the editor "
                    "hide conditions your mod build doesn't have.")
        else:
            text = (f"Targeting Reactive Music {version}. Conditions added in later versions are "
                    "disabled below. Ones already set on this entry stay editable so you can "
                    "remove them.")
        ctk.CTkLabel(
            parent, text=text, font=_SMALL, justify="left", wraplength=620,
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", padx=8, pady=(6, 2))

    def _pool_banner(self, entry: Entry):
        """When one entry holds several songs (a YAML song pool), say so: the
        conditions edited here decide when ANY of them plays, and the list row
        only names the first one as the case's identity.
        """
        if len(entry.songs) < 2:
            return
        ctk.CTkLabel(
            self.editor_frame,
            text=(f"This case is a song pool of {len(entry.songs)}: "
                  + ", ".join(entry.songs[:6])
                  + (f", +{len(entry.songs) - 6} more" if len(entry.songs) > 6 else "")
                  + ". These conditions decide when ANY of them plays; "
                  "use \"Edit songs…\" to change the pool."),
            font=_SMALL, justify="left", wraplength=620,
            text_color=("gray40", "gray70"),
        ).pack(anchor="w", padx=8, pady=(2, 2))

    # -- fixed categories (with per-category OR/AND combine control) --------
    def _set_fixed_combine(self, entry: Entry, cat: str, value: str):
        """Single-entry editor: record the user's OR/AND choice for one
        fixed category. This directly affects what ``build_events`` emits
        on save, so it's a real functional setting, not a label.
        """
        _entry_fixed_combine(entry)[cat] = value
        self._refresh_after_change(entry, rebuild=False)

    def _build_fixed_categories(self, entry: Entry):
        """The fixed checkbox groups.

        Each category is its own compact card. Right under the header sits
        a small OR/AND segmented control that decides how the checked
        options in that category are combined in the generated ``events``
        array:

          * OR  -> one array item, options joined by " || "
          * AND -> one array item per option (separate items are AND'd)

        Below that, the options flow left-to-right and wrap onto additional
        rows as the editor width allows. Options the target build predates
        are disabled unless the entry already uses them, and the gate
        suffix is still rendered.
        """
        for cat in C.FIXED_CATEGORY_ORDER:
            definition = C.FIXED_CATEGORIES[cat]

            body = _section(
                self.editor_frame,
                definition['label'],
                compact=True,
            )

            # -- OR/AND control for this category -----------------------
            fc = _entry_fixed_combine(entry)
            mode_var = tk.StringVar(value=fc.get(cat, C.COMBINE_OR))
            self.fixed_combine_vars[cat] = mode_var

            combine_row = ctk.CTkFrame(body, fg_color="transparent")
            combine_row.pack(fill="x", padx=4, pady=(0, 2))
            ctk.CTkLabel(
                combine_row, text="Combine checked options with:",
                font=_SMALL, text_color=("gray40", "gray70"),
            ).pack(side="left")
            ctk.CTkSegmentedButton(
                combine_row, values=[C.COMBINE_OR, C.COMBINE_AND],
                variable=mode_var, font=_BODY,
                command=lambda v, e=entry, c=cat: self._set_fixed_combine(
                    e, c, v),
            ).pack(side="left", padx=8)

            # -- checkbox flow -------------------------------------------
            grid = ctk.CTkFrame(body, fg_color="transparent")
            grid.pack(fill="x")
            option_vars = {}
            widgets = []
            for opt in definition["options"]:
                already_set = opt in entry.selected.get(cat, set())
                available = self._supports(opt)
                var = tk.BooleanVar(value=already_set)
                check = ctk.CTkCheckBox(
                    grid, text=self._option_label(opt, available),
                    variable=var, font=_BODY,
                    command=lambda c=cat: self._on_fixed_changed(entry, c),
                )
                if not available and not already_set:
                    check.configure(state="disabled")
                widgets.append(check)
                option_vars[opt] = var
            self.category_vars[cat] = option_vars
            # Wrapping flow: as many per row as fit at the current width.
            _flow_group(grid, widgets)

    # -- editor construction -------------------------------------------------
    def _build_editor_for(self, entry: Entry):
        """Build the editor for one case (``entry``). Every widget below edits
        this entry directly, exactly as it did before cases existed.
        """
        self._editor_showing_key = (
            frozenset(self.selected_entry_ids), self.active_case)
        for w in self.editor_frame.winfo_children():
            w.destroy()
        self.category_vars = {}
        self.fixed_combine_vars = {}

        self.biome_map = None

        # -- target banner --
        self._target_banner(self.editor_frame)
        self._pool_banner(entry)

        # -- biome map chart: deliberately first, above every other group --
        self._build_biome_map_section(entry)

        # -- fixed checkbox categories --
        self._build_fixed_categories(entry)

        self._build_biome_section(entry)
        self._build_dimension_section(entry)
        self._build_block_section(entry)
        self._build_scope_section(entry)
        self._build_advanced_section(entry)
        self._build_custom_section(entry)
        self._build_priority_section(entry)

    # -- songs dialog ---------------------------------------------------------
    def _edit_songs_clicked(self):
        groups = self._selected_groups()
        if len(groups) != 1:
            return
        group = groups[0]
        # The song list is edited for the case currently shown in the editor.
        entry = group[max(0, min(self.active_case, len(group) - 1))]
        self._open_songs_dialog(entry)

    # -- audio editor ---------------------------------------------------------
    def _edit_audio_clicked(self):
        """Open the waveform/trim editor for the selected entry's audio.

        ui_enhancements.install() publishes app.action_edit_audio (which
        also knows how to resolve the file through its own preview
        helper); this falls back to calling the editor directly so the
        button still works when the enhancement isn't installed.
        """
        sel = self.tree.selection()
        if len(sel) != 1:
            return
        entry = next(
            (e for e in self.app.pack.entries if e.id == sel[0]), None)
        if entry is None:
            return

        action = getattr(self.app, "action_edit_audio", None)
        if callable(action):
            action()
            return
        try:
            import audio_editor  # imported lazily: optional dependency
        except ImportError as exc:
            messagebox.showerror(
                "Audio editor unavailable",
                "The audio editor needs the 'soundfile' and 'numpy' packages.\n\n"
                "Install them with:\n    python -m pip install -r requirements.txt\n\n"
                f"Import error: {exc}")
            return
        audio_editor.open_audio_editor(self.app, entry)

    def _open_songs_dialog(self, entry: Entry):
        """Small dialog for editing the entry's underlying song list. The
        primary track is the first line; extra lines are fallback filler
        (see the "Mix into this entry" button under Priority & Variety).
        Kept out of the main editor because most entries only have one
        song and the list would dominate the condition UI.
        """
        group = _group_of(self.app.pack, entry.id)
        window = tk.Toplevel(self)
        window.title("Edit songs" if len(group) < 2
                     else f"Edit songs \u2014 Case {group.index(entry) + 1}")
        window.transient(self)
        window.grab_set()
        window.minsize(420, 260)
        window.configure(bg=theme.toplevel_bg(
            bool(self.app.settings.get("dark_theme", True))))

        body = ctk.CTkFrame(window, corner_radius=0)
        body.pack(fill="both", expand=True, padx=14, pady=14)

        ctk.CTkLabel(
            body,
            text=("One song filename (without extension) per line.\n"
                  "The first line is the primary track shown in the list; any\n"
                  "extra lines are fallback / mixed-in songs."
                  + ("" if len(group) < 2 else
                     "\nThis list belongs to the case being edited; renaming the\n"
                     "first line renames the song in every case.")),
            font=_BODY, justify="left", anchor="w",
        ).pack(anchor="w")

        songs_box = ctk.CTkTextbox(body, height=140, font=_BODY)
        songs_box.pack(fill="both", expand=True, pady=(8, 10))
        songs_box.insert("1.0", "\n".join(entry.songs))

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.pack(fill="x")

        def save():
            old_primary = entry.songs[0] if entry.songs else None
            entry.songs = [
                line.strip()
                for line in songs_box.get("1.0", "end").splitlines()
                if line.strip()
            ]
            new_primary = entry.songs[0] if entry.songs else None
            if old_primary and new_primary and old_primary != new_primary:
                # The primary song is the song's identity: keep the other
                # cases pointing at it.
                for sibling in group:
                    if sibling is not entry and sibling.songs \
                            and sibling.songs[0] == old_primary:
                        sibling.songs[0] = new_primary
            window.destroy()
            # The display name (and therefore the tree row and editor title)
            # may have changed if songs were added or removed.
            self.editor_title.configure(
                text=f"Conditions for: {group[0].display_name()}")
            self.refresh_tree(keep_selection=True)
            self.app.priority_tab.refresh()
            self.app.set_status("Updated songs for this entry.")

        ctk.CTkButton(btns, text="Cancel", width=90, font=_BODY,
                      **theme.NEUTRAL_BUTTON,
                      command=window.destroy).pack(side="right", padx=(6, 0))
        ctk.CTkButton(btns, text="Apply", width=90, font=_BODY,
                      command=save).pack(side="right")

        window.bind("<Escape>", lambda _e: window.destroy())
        window.bind("<Return>", lambda _e: save())

    # -- biome map (temperature x humidity chart) ------------------------------
    def _build_biome_map_section(self, entry: Entry):
        """Chart of every biome at its temperature/humidity coordinate.
        Clicking an icon adds/removes a plain ``BIOME=`` condition on the
        entry -- the same list the Biome section below edits -- and the
        OR/AND selector here drives the same ``biome_combine`` setting.

        A Biomes / Biome tags selector sits above them. In tag mode the same
        chart draws one icon per biome tag (placed at the average
        temperature/humidity of its biomes, see
        biome_customization.tag_attributes) and a click toggles a BIOMETAG=
        condition on the entry instead of a BIOME= one.

        Two view controls sit in the header row:

          * a Dimension selector that restricts the chart to biomes that
            spawn in the chosen dimension (sourced from the
            ``biome_dimensions`` block in default_biome_colors.json), and
          * a Hide/Show toggle that collapses the chart + its hint text
            so the editor below can reclaim the vertical space.
        """
        body = _section(self.editor_frame,
                        "Biome Map (temperature × humidity)")

        # -- mode row: biome map / biome tag map -------------------------
        mode_row = _row(body)
        ctk.CTkLabel(mode_row, text="Map:", font=_BODY).pack(side="left")
        self.chart_mode_var = tk.StringVar(
            value=(self._CHART_MODE_TAGS if self._biome_map_mode == "tags"
                   else self._CHART_MODE_BIOMES))
        ctk.CTkSegmentedButton(
            mode_row, values=[self._CHART_MODE_BIOMES, self._CHART_MODE_TAGS],
            variable=self.chart_mode_var, font=_BODY,
            command=self._on_chart_mode_changed,
        ).pack(side="left", padx=8)

        # -- header row: OR/AND + dimension + collapse toggle ----------
        row = _row(body)
        ctk.CTkLabel(row, text="Combine enabled biomes/tags with:",
                     font=_BODY).pack(side="left")
        self.chart_combine_var = tk.StringVar(value=entry.biome_combine)
        ctk.CTkSegmentedButton(
            row, values=[C.COMBINE_OR, C.COMBINE_AND],
            variable=self.chart_combine_var, font=_BODY,
            command=lambda v: self._set_combine(entry, "biome_combine", v),
        ).pack(side="left", padx=8)

        ctk.CTkLabel(row, text="Dimension:", font=_BODY).pack(
            side="left", padx=(16, 0))
        self.chart_dimension_var = tk.StringVar(
            value=self._biome_map_dimension)
        ctk.CTkSegmentedButton(
            row, values=self._CHART_DIMENSIONS,
            variable=self.chart_dimension_var, font=_BODY,
            command=self._on_chart_dimension_changed,
        ).pack(side="left", padx=8)

        # Right-aligned so the (potentially many) filter widgets on the
        # left can never push it off screen.
        self.biome_map_toggle_btn = ctk.CTkButton(
            row,
            text=("▸ Show map" if self._biome_map_collapsed else "▾ Hide map"),
            width=110, font=_BODY,
            command=self._toggle_biome_map,
        )
        self.biome_map_toggle_btn.pack(side="right", padx=(6, 2))

        # -- chart + hint, wrapped in a single forgettable container ----
        # A container (rather than packing/forgetting the chart and hint
        # separately) keeps the collapse/expand to a single pack_forget()
        # and guarantees the two can never get out of sync.
        self.biome_map_container = ctk.CTkFrame(body, fg_color="transparent")
        if not self._biome_map_collapsed:
            self.biome_map_container.pack(fill="x", padx=4, pady=(4, 2))

        self.biome_map = biome_chart.BiomeChart(
            self.biome_map_container,
            # Bound method, not a lambda: _chart_biomes reads the current
            # dimension filter on every call, so the chart re-filters
            # itself on each redraw() without ever being rebuilt.
            biomes=self._chart_biomes,
            color_of=self._chart_color,
            active=lambda: self._chart_active(entry),
            tooltip_lines=self._chart_tooltip_lines,
            on_toggle=lambda name: self._on_chart_toggle(entry, name),
            dark=bool(self.app.settings.get("dark_theme", True)),
            height=460,
        )
        self.biome_map.pack(fill="x", padx=4, pady=(4, 2))

        self.biome_map_hint = ctk.CTkLabel(
            self.biome_map_container, text=self._chart_hint_text(),
            font=_SMALL, text_color=("gray40", "gray70"), justify="left",
            anchor="w", wraplength=620,
        )
        self.biome_map_hint.pack(anchor="w", padx=6, pady=(0, 4))

    # -- biome map: data source + view state ---------------------------
    def _chart_biomes(self) -> dict:
        """Data source handed to BiomeChart. Called fresh on every
        redraw, so switching the dimension selector or the Biomes / Biome tags
        mode and calling redraw() is enough -- no widget rebuild required.
        Both modes are {name: {temperature, humidity, erosion, weirdness}}.
        """
        attrs = biome_customization.all_attributes(
            self.app.biome_custom_attributes)
        tags_mode = self._biome_map_mode == "tags"
        if tags_mode:
            attrs = biome_customization.tag_attributes(attrs)
            attrs = {t: a for t, a in attrs.items() if self._tag_supported(t)}
        wanted = self._CHART_DIMENSION_IDS.get(self.chart_dimension_var.get())
        if not wanted:
            return attrs
        dimension_of = biome_customization.load_app_dimensions()
        if tags_mode:
            # A tag belongs to a dimension when any of its biomes does; its
            # position is unaffected, so icons don't jump when filtering.
            return {t: a for t, a in attrs.items()
                    if any(dimension_of.get(b) == wanted
                           for b in biome_customization.tag_members(t))}
        return {name: a for name, a in attrs.items()
                if dimension_of.get(name) == wanted}

    def _chart_color(self, name: str) -> str:
        return self._biome_color(name, self._biome_map_mode == "tags")

    def _chart_tooltip_lines(self, name: str) -> list:
        if self._biome_map_mode != "tags":
            return []
        count = len(biome_customization.tag_members(name))
        return [f"contains {count} biome{'' if count == 1 else 's'}"]

    def _chart_hint_text(self) -> str:
        if self._biome_map_mode == "tags":
            text = ("Click a biome tag to enable/disable it as a BIOMETAG= condition "
                    "(enabled = \u2714). Each tag sits at the average temperature/humidity of "
                    "the biomes it contains, and plays in all of them. The Dimension filter "
                    "keeps tags that contain at least one biome of that dimension. Custom tags "
                    "have no biome list, so they are added from the Biome section below. ")
            version = self.app.effective_mod_version()
            if not mod_versions.supports(version, "BIOMETAG"):
                text += (f"{self.WARNING_PREFIX}The target build (Reactive Music {version}) "
                         f"predates BIOMETAG= (needs {mod_versions.requirement('BIOMETAG')}+): "
                         "tags already on this case can be removed, new ones are refused.")
            return text
        return ("Click a biome to enable/disable it as a BIOME= condition (enabled = \u2714). "
                "Lobe depth follows erosion and lobe count follows weirdness. Biomes that "
                "share exactly the same coordinates are fanned out slightly so each stays "
                "clickable. The Dimension filter above limits the map to biomes that spawn "
                "in the chosen dimension; custom biomes (which have no dimension recorded) "
                "show only under 'All'.")

    def _on_chart_mode_changed(self, label: str):
        """Biomes <-> Biome tags. Redrawn synchronously (unlike the dimension
        filter): the icons must match the mode before the next mouse move asks
        the chart for a tooltip.
        """
        self._biome_map_mode = "tags" if label == self._CHART_MODE_TAGS else "biomes"
        hint = getattr(self, "biome_map_hint", None)
        if hint is not None and hint.winfo_exists():
            hint.configure(text=self._chart_hint_text())
        chart = getattr(self, "biome_map", None)
        if chart is not None and chart.winfo_exists():
            chart.redraw()

    def _on_chart_dimension_changed(self, value: str):
        """The chart's Dimension selector moved: remember the choice and
        ask the chart to re-read its data (which the new filter now
        restricts). Redraw is deferred by one idle cycle so the segmented
        button paints its new state before we rebuild the canvas.
        """
        self._biome_map_dimension = value
        chart = getattr(self, "biome_map", None)
        if chart is not None and chart.winfo_exists():
            self.after_idle(chart.redraw)

    def _toggle_biome_map(self):
        """Collapse/expand the biome map (chart + hint text)."""
        self._biome_map_collapsed = not self._biome_map_collapsed
        container = getattr(self, "biome_map_container", None)
        if container is None or not container.winfo_exists():
            return
        if self._biome_map_collapsed:
            container.pack_forget()
            self.biome_map_toggle_btn.configure(text="▸ Show map")
        else:
            container.pack(fill="x", padx=4, pady=(4, 2))
            self.biome_map_toggle_btn.configure(text="▾ Hide map")
            # Un-hiding takes the canvas from ~0×0 to its real size, but
            # Tk doesn't always deliver <Configure> in the same event
            # cycle as the re-pack. Kick off an explicit redraw on the
            # next idle so the plot is populated the moment it becomes
            # visible, rather than on the first mouse move.
            chart = getattr(self, "biome_map", None)
            if chart is not None and chart.winfo_exists():
                self.after_idle(chart.redraw)

    def _active_biome_keys(self, entry: Entry) -> set:
        """Chart icons to draw as enabled: every biome that any BIOME=
        condition of the entry matches, by the mod's soft matching
        (conditions.soft_match) and including conditions that live in a
        verbatim / cross-category item. BIOME=forest therefore lights up
        dark_forest, birch_forest, ... as it does in the game.
        """
        atoms = [a for a in condition_logic.entry_atoms(entry)
                 if a.kind == conditions.KIND_BIOME]
        if not atoms:
            return set()
        names = biome_customization.all_attributes(
            self.app.biome_custom_attributes)
        return {biome_chart.normalize_name(n) for n in names
                if any(conditions.soft_match(a.value, n) for a in atoms)}

    def _chart_active(self, entry: Entry) -> set:
        """Icons to draw as enabled for the current map mode."""
        if self._biome_map_mode == "tags":
            return self._active_tag_keys(entry)
        return self._active_biome_keys(entry)

    def _active_tag_keys(self, entry: Entry) -> set:
        """Tag-map icons to draw as enabled: every tag any BIOMETAG= condition
        of the entry names (IS_ prefix optional, as in the mod), including
        conditions living in a verbatim / cross-category item.
        """
        wanted = {conditions.normalize_tag(a.value)
                  for a in condition_logic.entry_atoms(entry)
                  if a.kind == conditions.KIND_BIOMETAG}
        if not wanted:
            return set()
        tags = biome_customization.tag_attributes(
            biome_customization.all_attributes(self.app.biome_custom_attributes))
        return {biome_chart.normalize_name(t) for t in tags
                if conditions.normalize_tag(t) in wanted}

    def _on_chart_tag_toggle(self, entry: Entry, name: str):
        """Tag-map click: add/remove a plain BIOMETAG= condition. Mirrors the
        biome path: a tag matched only inside a verbatim condition is reported
        instead of duplicated, and adding is refused (removing is not) when the
        target build predates BIOMETAG=.
        """
        key = conditions.normalize_tag(name)
        matches = [b for b in entry.biomes
                   if b.is_tag and conditions.normalize_tag(b.value) == key]
        if matches:
            entry.biomes = [b for b in entry.biomes if b not in matches]
        elif biome_chart.normalize_name(name) in self._active_tag_keys(entry):
            self.app.set_status(
                f"'{name}' is already matched by a BIOMETAG= inside a custom condition of "
                "this case. Edit or remove that condition to change it.")
            return
        elif not self._supports("BIOMETAG"):
            self.app.set_status(
                f"The target build predates BIOMETAG= (needs "
                f"{mod_versions.requirement('BIOMETAG')}+), so '{name}' was not added.")
            return
        else:
            entry.biomes.append(BiomeCondition(value=name, is_tag=True))
        self._sync_biome_widgets(entry)
        self._refresh_after_change(entry, rebuild=False)

    def _on_chart_toggle(self, entry: Entry, name: str):
        if self._biome_map_mode == "tags":
            self._on_chart_tag_toggle(entry, name)
            return
        key = biome_chart.normalize_name(name)
        matches = [b for b in entry.biomes
                   if not b.is_tag and biome_chart.normalize_name(b.value) == key]
        if matches:
            entry.biomes = [b for b in entry.biomes if b not in matches]
        elif key in self._active_biome_keys(entry):
            # Already matched by a broader BIOME= (or one inside a verbatim
            # condition). Adding a duplicate would change nothing and removing
            # the broad one is not what a click on this icon means.
            self.app.set_status(
                f"'{name}' is already matched by another BIOME= condition of this "
                "case (a broader name, or one inside a custom condition). Edit or "
                "remove that condition to change it.")
            return
        else:
            entry.biomes.append(BiomeCondition(value=name, is_tag=False))
        # Update the Biome section below in place (rebuilding the whole
        # editor here would make the chart flash on every click).
        self._sync_biome_widgets(entry)
        self._refresh_after_change(entry, rebuild=False)

    def _sync_biome_widgets(self, entry: Entry):
        """Refresh the Biome section's listbox and picker after the entry's
        biome list was changed from somewhere other than that section.
        """
        try:
            listbox = getattr(self, "biome_listbox", None)
            if listbox is not None and listbox.winfo_exists():
                listbox.delete(0, "end")
                for index, b in enumerate(entry.biomes):
                    listbox.insert(
                        "end", ("[TAG] " if b.is_tag else "") + b.value)
                    listbox.itemconfig(
                        index, foreground=self._biome_color(b.value, b.is_tag))
                listbox.configure(height=min(4, max(2, len(entry.biomes))))
            combo = getattr(self, "biome_combobox", None)
            if combo is not None:
                combo.configure(values=self._available_biome_values(
                    entry, self.biome_is_tag_var.get()))
        except tk.TclError:
            pass

    # -- biome ---------------------------------------------------------------
    def _build_biome_section(self, entry: Entry):
        biome_body = _section(self.editor_frame, "Biome")

        row1 = _row(biome_body)
        ctk.CTkLabel(row1, text="Biome:", font=_BODY).pack(side="left")
        self.biome_search_var = tk.StringVar()
        self.biome_is_tag_var = tk.BooleanVar(value=False)
        self.biome_combobox = ctk.CTkComboBox(
            row1, variable=self.biome_search_var,
            values=self._available_biome_values(entry, False),
            width=220, font=_BODY,
        )
        self.biome_combobox.pack(side="left", padx=6)

        def _on_biome_tag_toggle():
            self.biome_combobox.configure(
                values=self._available_biome_values(
                    entry, self.biome_is_tag_var.get())
            )

        tag_available = self._supports("BIOMETAG")
        tag_label = ("Use as BIOMETAG (broader match)"
                     if tag_available
                     else "Use as BIOMETAG (broader match)" + self._gate_suffix("BIOMETAG"))
        tag_check = ctk.CTkCheckBox(
            row1, text=tag_label, variable=self.biome_is_tag_var,
            command=_on_biome_tag_toggle, font=_BODY,
        )
        if not tag_available:
            self.biome_is_tag_var.set(False)
            tag_check.configure(state="disabled")
        tag_check.pack(side="left", padx=8)
        ctk.CTkButton(row1, text="Add", width=64, font=_BODY,
                      command=lambda: self._add_biome(entry)).pack(side="left", padx=4)
        ctk.CTkButton(row1, text="Add custom…", width=110, font=_BODY,
                      command=lambda: self._open_custom_biome_dialog(entry)).pack(
                          side="left", padx=4)

        row2 = _row(biome_body)
        ctk.CTkLabel(row2, text="Combine multiple biomes with:",
                     font=_BODY).pack(side="left")
        self.biome_combine_var = tk.StringVar(value=entry.biome_combine)
        self.biome_combine_seg = ctk.CTkSegmentedButton(
            row2, values=[C.COMBINE_OR, C.COMBINE_AND],
            variable=self.biome_combine_var, font=_BODY,
            command=lambda v: self._set_combine(entry, "biome_combine", v),
        )
        self.biome_combine_seg.pack(side="left", padx=8)

        listbox_wrap = ctk.CTkFrame(biome_body, corner_radius=6)
        listbox_wrap.pack(fill="x", padx=4, pady=4)
        self.biome_listbox = self._themed_listbox(
            listbox_wrap, height=min(4, max(2, len(entry.biomes))))
        self.biome_listbox.pack(fill="x", padx=2, pady=2)
        for index, b in enumerate(entry.biomes):
            self.biome_listbox.insert(
                "end", ("[TAG] " if b.is_tag else "") + b.value)
            self.biome_listbox.itemconfig(
                index, foreground=self._biome_color(b.value, b.is_tag))
        ctk.CTkButton(biome_body, text="Remove selected", width=140,
                      font=_BODY,
                      **theme.NEUTRAL_BUTTON,
                      command=lambda: self._remove_biome(entry)).pack(
                          anchor="w", padx=4, pady=(0, 4))

    # -- dimension -----------------------------------------------------------
    def _build_dimension_section(self, entry: Entry):
        dim_body = _section(self.editor_frame, "Dimension")

        drow1 = _row(dim_body)
        ctk.CTkLabel(drow1, text="Dimension:", font=_BODY).pack(side="left")
        self.dim_search_var = tk.StringVar()
        self.dim_combobox = ctk.CTkComboBox(
            drow1, variable=self.dim_search_var,
            values=C.COMMON_DIMENSIONS, width=220, font=_BODY)
        self.dim_combobox.pack(side="left", padx=6)
        ctk.CTkButton(drow1, text="Add", width=64, font=_BODY,
                      command=lambda: self._add_dimension(entry)).pack(side="left", padx=4)

        drow2 = _row(dim_body)
        ctk.CTkLabel(drow2, text="Combine multiple dimensions with:",
                     font=_BODY).pack(side="left")
        self.dim_combine_var = tk.StringVar(value=entry.dimension_combine)
        self.dim_combine_seg = ctk.CTkSegmentedButton(
            drow2, values=[C.COMBINE_OR, C.COMBINE_AND],
            variable=self.dim_combine_var, font=_BODY,
            command=lambda v: self._set_combine(entry, "dimension_combine", v),
        )
        self.dim_combine_seg.pack(side="left", padx=8)

        listbox_wrap = ctk.CTkFrame(dim_body, corner_radius=6)
        listbox_wrap.pack(fill="x", padx=4, pady=4)
        self.dim_listbox = self._themed_listbox(
            listbox_wrap, height=min(4, max(2, len(entry.dimensions))))
        self.dim_listbox.pack(fill="x", padx=2, pady=2)
        for d in entry.dimensions:
            self.dim_listbox.insert("end", d.value)
        ctk.CTkButton(dim_body, text="Remove selected", width=140,
                      font=_BODY,
                      **theme.NEUTRAL_BUTTON,
                      command=lambda: self._remove_dimension(entry)).pack(
                          anchor="w", padx=4, pady=(0, 4))

    # -- block ---------------------------------------------------------------
    def _build_block_section(self, entry: Entry):
        block_body = _section(self.editor_frame,
                              "Nearby Blocks (25-block radius)")

        # BLOCK= only exists from 1.2.0 onward. If the target build is older
        # and the entry doesn't already use it, the whole section collapses
        # to an explanation instead of being silently broken.
        block_available = self._supports("BLOCK") or bool(entry.blocks)
        if not block_available:
            ctk.CTkLabel(
                block_body,
                text=("Nearby-block detection was added in Reactive Music "
                      f"{mod_versions.requirement('BLOCK')}. Raise the target build in the "
                      "Songpack Info tab to use it."),
                font=_BODY, text_color=("gray40", "gray70"),
                justify="left", wraplength=560, anchor="w",
            ).pack(anchor="w", padx=6, pady=6)
            return

        if not self._supports("BLOCK"):
            ctk.CTkLabel(
                block_body,
                text=(f"{self.WARNING_PREFIX}This entry already uses BLOCK=, which the target "
                      f"build predates (needs {mod_versions.requirement('BLOCK')}+). It is kept "
                      "editable so you can remove it."),
                font=_SMALL, text_color=("#b45309", "#E0A030"),
                justify="left", wraplength=560, anchor="w",
            ).pack(anchor="w", padx=6, pady=(4, 0))

        brow1 = _row(block_body)
        ctk.CTkLabel(brow1, text="Block:", font=_BODY).pack(side="left")
        self.block_search_var = tk.StringVar()
        self.block_combobox = ctk.CTkComboBox(
            brow1, variable=self.block_search_var,
            values=block_data.COMMON_BLOCK_IDS, width=240, font=_BODY)
        self.block_combobox.pack(side="left", padx=6)
        self.block_search_var.trace_add(
            "write", lambda *_: self._filter_block_options())
        ctk.CTkLabel(brow1, text="Min count:", font=_BODY).pack(
            side="left", padx=(10, 0))
        self.block_count_var = tk.StringVar(value="1")
        ctk.CTkEntry(brow1, textvariable=self.block_count_var, width=70,
                     font=_BODY).pack(side="left", padx=4)
        ctk.CTkButton(brow1, text="Add", width=64, font=_BODY,
                      command=lambda: self._add_block(entry)).pack(side="left", padx=4)
        ctk.CTkLabel(
            block_body,
            text="Tip: use /reactivemusic logBlockCounter in-game to see real counts.",
            font=_SMALL, text_color=("gray40", "gray70"), anchor="w",
        ).pack(anchor="w", padx=4)

        brow2 = _row(block_body)
        ctk.CTkLabel(brow2, text="Combine multiple blocks with:",
                     font=_BODY).pack(side="left")
        self.block_combine_var = tk.StringVar(value=entry.block_combine)
        self.block_combine_seg = ctk.CTkSegmentedButton(
            brow2, values=[C.COMBINE_AND, C.COMBINE_OR],
            variable=self.block_combine_var, font=_BODY,
            command=lambda v: self._set_combine(entry, "block_combine", v),
        )
        self.block_combine_seg.pack(side="left", padx=8)

        listbox_wrap = ctk.CTkFrame(block_body, corner_radius=6)
        listbox_wrap.pack(fill="x", padx=4, pady=4)
        self.block_listbox = self._themed_listbox(
            listbox_wrap, height=min(4, max(2, len(entry.blocks))))
        self.block_listbox.pack(fill="x", padx=2, pady=2)
        for b in entry.blocks:
            self.block_listbox.insert(
                "end", f"{b.block_id}  (min {b.min_count})")
        ctk.CTkButton(block_body, text="Remove selected", width=140,
                      font=_BODY,
                      **theme.NEUTRAL_BUTTON,
                      command=lambda: self._remove_block(entry)).pack(
                          anchor="w", padx=4, pady=(0, 4))

    # -- scope: global / default songs ---------------------------------------
    _SCOPE_HELP = {
        C.SCOPE_NORMAL: "An ordinary entry.",
        C.SCOPE_GLOBAL: (
            "Plays in every biome where its conditions hold (leave out BIOME=). It is pinned "
            "below all normal entries, so it only plays where they don't win or where they "
            "have allowFallback on. Use Priority Order > \"Check global songs\" to find and "
            "fix entries that block it."),
        C.SCOPE_DEFAULT: (
            "A gap filler: plays only where no entry above handles the situation. Pinned "
            "below all normal entries. Nothing to fix when a biome already has its own "
            "song for these conditions; that is the point."),
    }

    def _build_scope_section(self, entry: Entry):
        body = _section(self.editor_frame, "Scope (global / default songs)")
        self.scope_var = tk.StringVar(
            value=C.SCOPE_LABELS.get(entry.scope, C.SCOPE_LABELS[C.SCOPE_NORMAL]))
        ctk.CTkSegmentedButton(
            body, values=[C.SCOPE_LABELS[s] for s in C.SCOPES],
            variable=self.scope_var, font=_BODY,
            command=lambda v, e=entry: self._set_scope(e, v),
        ).pack(anchor="w", padx=4, pady=4)
        ctk.CTkLabel(
            body, text=self._SCOPE_HELP.get(entry.scope, ""), font=_SMALL,
            text_color=("gray40", "gray70"), justify="left", anchor="w",
            wraplength=620,
        ).pack(anchor="w", padx=6, pady=(0, 4))
        if entry.scope == C.SCOPE_NORMAL:
            return
        warn = ("#b45309", "#E0A030")
        if entry.biomes:
            ctk.CTkLabel(
                body,
                text=(f"{self.WARNING_PREFIX}This case has BIOME=/BIOMETAG= conditions, so it "
                      "will not play everywhere. Remove them, or set the scope back to Normal."),
                font=_SMALL, text_color=warn, justify="left", anchor="w",
                wraplength=620,
            ).pack(anchor="w", padx=6, pady=(0, 4))
        if not self._supports("allow_fallback"):
            ctk.CTkLabel(
                body,
                text=(f"{self.WARNING_PREFIX}The target build predates allowFallback (needs "
                      f"{mod_versions.requirement('allow_fallback')}+), so entries above this "
                      "one cannot be made to fall through to it."),
                font=_SMALL, text_color=warn, justify="left", anchor="w",
                wraplength=620,
            ).pack(anchor="w", padx=6, pady=(0, 4))

    def _set_scope(self, entry: Entry, label: str):
        scope = C.SCOPE_BY_LABEL.get(label, C.SCOPE_NORMAL)
        if scope == entry.scope:
            return
        entry.scope = scope
        self.app.mark_dirty()
        priority.enforce_scope_order(self.app.pack.entries)
        # Moving the entry can change which case is "Case 1" (the row key).
        group = _group_of(self.app.pack, entry.id)
        row_id = group[0].id
        self.selected_entry_ids = [row_id]
        self.selected_entry_id = row_id
        self.active_case = group.index(entry)
        self.refresh_tree(keep_selection=True)
        self.rebuild_editor()
        self.app.priority_tab.refresh()
        self.app.set_status(
            f"Scope set to {C.SCOPE_LABELS[scope]}. "
            + ("It now sits below all normal entries in the priority order."
               if scope != C.SCOPE_NORMAL else
               "It is an ordinary entry again."))

    # -- advanced / fallback -------------------------------------------------
    def _build_advanced_section(self, entry: Entry):
        adv_body = _section(self.editor_frame,
                            "Advanced / Fallback Behaviour")

        self.allow_fallback_var = tk.BooleanVar(value=entry.allow_fallback)
        fallback_available = self._supports("allow_fallback")
        fallback_label = (
            "allowFallback — once this entry's own song(s) are exhausted, let another valid\n"
            "entry play instead of repeating (ReactiveMusic default: off)"
            + ("" if fallback_available else self._gate_suffix("allow_fallback"))
        )
        fallback_check = ctk.CTkCheckBox(
            adv_body, text=fallback_label, variable=self.allow_fallback_var,
            font=_BODY,
            command=lambda: self._on_advanced_changed(entry),
        )
        if not fallback_available and not entry.allow_fallback:
            fallback_check.configure(state="disabled")
        fallback_check.pack(anchor="w", padx=4, pady=2)

        self.force_stop_changed_var = tk.BooleanVar(
            value=entry.force_stop_on_changed)
        ctk.CTkCheckBox(
            adv_body,
            text="forceStopMusicOnChanged (stop current music whenever this event's validity flips)",
            variable=self.force_stop_changed_var, font=_BODY,
            command=lambda: self._on_advanced_changed(entry),
        ).pack(anchor="w", padx=4, pady=1)

        self.force_stop_valid_var = tk.BooleanVar(
            value=entry.force_stop_on_valid)
        ctk.CTkCheckBox(
            adv_body,
            text="forceStopMusicOnValid (stop current music when this event becomes valid)",
            variable=self.force_stop_valid_var, font=_BODY,
            command=lambda: self._on_advanced_changed(entry),
        ).pack(anchor="w", padx=4, pady=1)

        self.force_stop_invalid_var = tk.BooleanVar(
            value=entry.force_stop_on_invalid)
        ctk.CTkCheckBox(
            adv_body,
            text="forceStopMusicOnInvalid (stop current music when this event becomes invalid)",
            variable=self.force_stop_invalid_var, font=_BODY,
            command=lambda: self._on_advanced_changed(entry),
        ).pack(anchor="w", padx=4, pady=1)

        self.force_start_var = tk.BooleanVar(value=entry.force_start_on_valid)
        ctk.CTkCheckBox(
            adv_body,
            text="forceStartMusicOnValid (immediately start this entry once valid, if music stopped)",
            variable=self.force_start_var, font=_BODY,
            command=lambda: self._on_advanced_changed(entry),
        ).pack(anchor="w", padx=4, pady=1)

        chance_row = _row(adv_body)
        ctk.CTkLabel(chance_row, text="forceChance:",
                     font=_BODY).pack(side="left")
        self.force_chance_var = tk.DoubleVar(value=entry.force_chance)
        self.force_chance_slider = ctk.CTkSlider(
            chance_row, from_=0.0, to=1.0, number_of_steps=100,
            variable=self.force_chance_var,
            command=lambda _v: self._on_advanced_changed(entry),
        )
        self.force_chance_slider.pack(
            side="left", padx=8, fill="x", expand=True)
        self.force_chance_label = ctk.CTkLabel(
            chance_row, text=f"{entry.force_chance:.2f}", font=_BODY, width=48)
        self.force_chance_label.pack(side="left", padx=(6, 0))

    # -- custom raw conditions ----------------------------------------------
    def _build_custom_section(self, entry: Entry):
        custom_body = _section(
            self.editor_frame,
            "Custom / unrecognised raw conditions (one per line)")
        self.custom_text = ctk.CTkTextbox(custom_body, height=90, font=_BODY)
        self.custom_text.insert("1.0", "\n".join(entry.custom_raw_conditions))
        self.custom_text.pack(fill="x", padx=4, pady=4)
        self.custom_text.bind(
            "<FocusOut>", lambda _e: self._on_custom_changed(entry))
        ctk.CTkLabel(
            custom_body,
            text=("Conditions the checkboxes and lists above can't represent exactly land here,\n"
                  "one YAML item per line, verbatim: an OR across categories\n"
                  "(BIOME=ocean || UNDERWATER), several OR groups in one category, or\n"
                  "anything unrecognised. The simulator, priority scoring, biome views and\n"
                  "version checks all read them; each line is AND'd with everything else."),
            font=_SMALL,
            text_color=("gray40", "gray70"), justify="left", anchor="w",
        ).pack(anchor="w", padx=4, pady=(0, 4))

    # -- priority / variety --------------------------------------------------
    def _build_priority_section(self, entry: Entry):
        info_body = _section(self.editor_frame, "Priority & Variety")
        self.score_label = ctk.CTkLabel(
            info_body,
            text=f"Rarity score: {priority.score_entry(entry)}   "
            f"(higher = more specific = plays before broader/common entries)",
            font=_BODY, anchor="w", justify="left",
        )
        self.score_label.pack(anchor="w", padx=4, pady=2)

        if not entry.has_any_condition():
            ctk.CTkLabel(
                info_body,
                text=(f"{self.WARNING_PREFIX}This entry has no conditions set, so it always "
                      "matches -- it will play whenever nothing higher in the priority list is valid."),
                font=_BODY, text_color=("#b45309", "#E0A030"),
                anchor="w", justify="left",
            ).pack(anchor="w", padx=4, pady=(0, 6))

        # Other cases of this same song aren't "fallbacks": they already play
        # this very song, so there is nothing to mix in from them.
        fallbacks = [
            fb for fb in priority.find_broader_fallbacks(
                entry, self.app.pack.entries, limit=1000)
            if _gid(fb) != _gid(entry)
        ][:5]
        if fallbacks:
            ctk.CTkLabel(
                info_body,
                text=("These broader entries would also be valid whenever this one is. Mixing one\n"
                      "of their songs directly into this entry's own rotation lets it play here too,\n"
                      "right away, instead of waiting for this entry's songs to fully exhaust first\n"
                      "(so this song doesn't loop as annoyingly in rare situations):"),
                font=_BODY, justify="left", anchor="w", wraplength=640,
            ).pack(anchor="w", padx=4, pady=(2, 4))
            for fb in fallbacks:
                row = ctk.CTkFrame(info_body, fg_color="transparent")
                row.pack(fill="x", padx=12, pady=2)
                ctk.CTkLabel(
                    row,
                    text=f"{fb.display_name()}  —  "
                    f"{condition_logic.summarize_entry(fb, 40)}",
                    font=_BODY, anchor="w",
                ).pack(side="left", fill="x", expand=True)
                ctk.CTkButton(
                    row, text="Mix into this entry", width=150, font=_BODY,
                    command=lambda fb=fb: self._mix_in_fallback(entry, fb),
                ).pack(side="right")
        else:
            ctk.CTkLabel(
                info_body,
                text="No broader entries currently detected to mix in.",
                font=_BODY, text_color=("gray40", "gray70"), anchor="w",
            ).pack(anchor="w", padx=4)

    # -- change handlers -------------------------------------------------
    def _on_fixed_changed(self, entry: Entry, cat: str):
        chosen = {opt for opt,
                  var in self.category_vars[cat].items() if var.get()}
        entry.selected[cat] = chosen
        self._refresh_after_change(entry, rebuild=False)

    def _on_advanced_changed(self, entry: Entry):
        entry.allow_fallback = self.allow_fallback_var.get()
        entry.force_stop_on_changed = self.force_stop_changed_var.get()
        entry.force_stop_on_valid = self.force_stop_valid_var.get()
        entry.force_stop_on_invalid = self.force_stop_invalid_var.get()
        entry.force_start_on_valid = self.force_start_var.get()
        entry.force_chance = round(float(self.force_chance_var.get()), 2)
        self.force_chance_label.configure(text=f"{entry.force_chance:.2f}")
        self._refresh_after_change(entry, rebuild=False)

    def _on_custom_changed(self, entry: Entry):
        text = self.custom_text.get("1.0", "end").strip()
        entry.custom_raw_conditions = [
            line.strip() for line in text.splitlines() if line.strip()]
        self._refresh_after_change(entry, rebuild=False)

    def _set_combine(self, entry: Entry, attr: str, value: str):
        setattr(entry, attr, value)
        if attr == "biome_combine":
            # The Biome Map and the Biome section each have an OR/AND
            # selector for the same setting; keep them showing the same value.
            for name in ("chart_combine_var", "biome_combine_var"):
                var = getattr(self, name, None)
                if var is not None and var.get() != value:
                    var.set(value)
        self._refresh_after_change(entry, rebuild=False)

    def _filter_block_options(self):
        text = self.block_search_var.get().strip().lower()
        if text:
            filtered = [
                b for b in block_data.COMMON_BLOCK_IDS if text in b.lower()]
        else:
            filtered = block_data.COMMON_BLOCK_IDS
        self.block_combobox.configure(values=filtered[:50])

    def _add_biome(self, entry: Entry):
        value = self.biome_search_var.get().strip()
        if not value:
            return
        entry.biomes.append(BiomeCondition(
            value=value, is_tag=self.biome_is_tag_var.get()))
        self.biome_search_var.set("")
        self._refresh_after_change(entry, rebuild=True)

    def _remove_biome(self, entry: Entry):
        sel = self.biome_listbox.curselection()
        if not sel:
            return
        del entry.biomes[sel[0]]
        self._refresh_after_change(entry, rebuild=True)

    def _open_custom_biome_dialog(self, entry: Entry):
        """Define a brand-new custom biome or biome tag (with its own text
        color) so it becomes available in the picker above. This does NOT
        add a condition to the entry by itself -- use "Add" for that once
        the new value is defined.
        """
        window = tk.Toplevel(self)
        window.title("Add Custom Biome / Biome Tag")
        window.resizable(False, False)
        window.transient(self)
        window.grab_set()
        window.configure(bg=theme.toplevel_bg(
            bool(self.app.settings.get("dark_theme", True))))

        body = ctk.CTkFrame(window, corner_radius=0)
        body.pack(padx=14, pady=14)
        name_var = tk.StringVar()
        type_var = tk.StringVar(value="Biome")
        color_var = tk.StringVar(
            value=biome_customization.default_color("custom"))

        ctk.CTkLabel(body, text="Name / identifier:", font=_BODY).grid(
            row=0, column=0, padx=6, pady=5)
        ctk.CTkEntry(body, textvariable=name_var, width=280,
                     font=_BODY).grid(
            row=0, column=1, columnspan=2, padx=2, pady=5, sticky="ew")
        ctk.CTkLabel(body, text="Type:", font=_BODY).grid(
            row=1, column=0, padx=6, pady=5)
        ctk.CTkComboBox(
            body, variable=type_var, values=("Biome", "Biome Tag"),
            state="readonly", width=140, font=_BODY,
        ).grid(row=1, column=1, padx=2, pady=5, sticky="w")
        ctk.CTkLabel(body, text="Text color:", font=_BODY).grid(
            row=2, column=0, padx=6, pady=5)
        swatch = tk.Label(body, text="        ",
                          bg=color_var.get(), relief="sunken")
        swatch.grid(row=2, column=1, padx=2, pady=5, sticky="w")

        def pick():
            result = colorchooser.askcolor(
                color=color_var.get(), parent=window, title="Biome text color")
            if result[1]:
                color = result[1].lower()
                color_var.set(color)
                swatch.configure(bg=color)

        ctk.CTkButton(body, text="Choose…", width=90, font=_BODY,
                      command=pick).grid(row=2, column=2, padx=4, pady=5)

        def add():
            name = name_var.get().strip()
            is_tag = type_var.get() == "Biome Tag"
            color = color_var.get().strip().lower()
            builtins = C.COMMON_BIOME_TAGS if is_tag else C.COMMON_BIOMES
            custom = (self.app.biome_custom_tags if is_tag
                      else self.app.biome_custom_biomes)
            if not name:
                messagebox.showwarning(
                    "Custom biome", "Enter a name.", parent=window)
                return
            if name in builtins or name in custom:
                messagebox.showwarning(
                    "Custom biome", "That name already exists.", parent=window)
                return
            if not biome_customization.valid_color(color):
                messagebox.showwarning(
                    "Custom biome", "Choose a valid text color.", parent=window)
                return
            custom[name] = color
            window.destroy()
            self._build_editor_for(entry)
            self.app.set_status(
                f"Added custom {'biome tag' if is_tag else 'biome'} '{name}'. "
                "Save the songpack to keep this definition."
            )

        ctk.CTkButton(body, text="Cancel", width=90, font=_BODY,
                      **theme.NEUTRAL_BUTTON,
                      command=window.destroy).grid(
            row=3, column=1, padx=4, pady=(8, 0), sticky="e")
        ctk.CTkButton(body, text="Add", width=90, font=_BODY,
                      command=add).grid(
            row=3, column=2, padx=4, pady=(8, 0), sticky="e")
        window.bind("<Return>", lambda _e: add())
        window.bind("<Escape>", lambda _e: window.destroy())

    def _add_dimension(self, entry: Entry):
        value = self.dim_search_var.get().strip()
        if not value:
            return
        entry.dimensions.append(DimensionCondition(value=value))
        self.dim_search_var.set("")
        self._refresh_after_change(entry, rebuild=True)

    def _remove_dimension(self, entry: Entry):
        sel = self.dim_listbox.curselection()
        if not sel:
            return
        del entry.dimensions[sel[0]]
        self._refresh_after_change(entry, rebuild=True)

    def _add_block(self, entry: Entry):
        value = self.block_search_var.get().strip()
        if not value:
            return
        try:
            count = max(1, int(self.block_count_var.get()))
        except (tk.TclError, ValueError):
            count = 1
        entry.blocks.append(BlockCondition(block_id=value, min_count=count))
        self.block_search_var.set("")
        self._refresh_after_change(entry, rebuild=True)

    def _remove_block(self, entry: Entry):
        sel = self.block_listbox.curselection()
        if not sel:
            return
        del entry.blocks[sel[0]]
        self._refresh_after_change(entry, rebuild=True)

    def _mix_in_fallback(self, target_entry: Entry, source_entry: Entry):
        added = [s for s in source_entry.songs
                 if s and s not in target_entry.songs]
        if not added:
            messagebox.showinfo(
                "Nothing to mix in",
                "That entry's song(s) are already part of this rotation.")
            return
        target_entry.songs.extend(added)
        target_entry.allow_fallback = True
        self._refresh_after_change(target_entry, rebuild=True)
        self.app.set_status(
            f"Mixed {', '.join(added)} into '{target_entry.songs[0]}' "
            "so it can play there too."
        )

    def _refresh_after_change(self, entry: Entry, rebuild: bool):
        if rebuild:
            self._build_editor_for(entry)
        else:
            # `score_label` only exists once the priority section has been
            # built. On the very first editor build for an entry this
            # method can be reached (e.g. if a widget fires its command
            # during construction) before that section exists -- guard
            # against it so the editor never ends up half-built.
            label = getattr(self, "score_label", None)
            if label is not None:
                label.configure(
                    text=f"Rarity score: {priority.score_entry(entry)}   "
                    f"(higher = more specific = plays before broader/common entries)"
                )
        self._restyle_case_tabs()
        self.app.on_entry_conditions_changed(entry)


# ---------------------------------------------------------------------------
# Tab 3: Priority Order (drag & drop)
# ---------------------------------------------------------------------------
class PriorityTab(ctk.CTkFrame):
    def __init__(self, parent, app: "App"):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._drag_start_iid = None

        top = ctk.CTkFrame(self, corner_radius=10)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(
            top,
            text=("Drag rows to reorder. The mod plays the first entry (top of this list) whose "
                  "conditions are currently true, so more specific/rare entries should sit above "
                  "broader, more common ones."),
            font=_BODY, wraplength=760, justify="left", anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=12, pady=10)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(4, 6))
        ctk.CTkButton(btns, text="Auto-arrange by rarity (recommended)",
                      width=230, font=_BODY,
                      command=self._auto_arrange).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Move Up", width=90, font=_BODY,
                      command=lambda: self._nudge(-1)).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Move Down", width=100, font=_BODY,
                      command=lambda: self._nudge(1)).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Check global songs…", width=160, font=_BODY,
                      command=self._check_globals).pack(side="left", padx=3)

        columns = ("idx", "song", "score", "summary", "fallback")
        self.tree = ttk.Treeview(
            self, columns=columns, show="headings",
            selectmode="browse", height=20)
        headers = {"idx": "#", "song": "Song", "score": "Rarity",
                   "summary": "Conditions", "fallback": "Fallback"}
        widths = {"idx": 45, "song": 220, "score": 75,
                  "summary": 380, "fallback": 85}
        anchors = {"idx": "center", "song": "w", "score": "center",
                   "summary": "w", "fallback": "center"}
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=widths[c], anchor=anchors[c])
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.tree.bind("<ButtonPress-1>", self._on_press)
        self.tree.bind("<B1-Motion>", self._on_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_release)

    def refresh(self):
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        # Global/default entries always sit below normal ones. This only
        # moves entries across those tiers; manual order inside a tier is
        # left alone, so do NOT replace it with priority.order_entries().
        priority.enforce_scope_order(self.app.pack.entries)
        labels = _case_labels(self.app.pack)
        for i, entry in enumerate(self.app.pack.entries, start=1):
            name = entry.display_name()
            if entry.id in labels:          # one of several cases of a song
                name += f"  [{labels[entry.id]}]"
            if entry.scope != C.SCOPE_NORMAL:
                name += f"  [{entry.scope}]"
            if not entry.has_any_condition():
                name = LibraryTab.WARNING_PREFIX + name
            self.tree.insert(
                "", "end", iid=entry.id,
                values=(
                    i, name, priority.score_entry(entry),
                    condition_logic.summarize_entry(entry),
                    "yes" if entry.allow_fallback else "no",
                ),
            )
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])

    def _check_globals(self):
        """Report entries that keep a global song from being reached, and
        offer to turn allowFallback on for them (scopes.py).
        """
        pack = self.app.pack
        if not any(e.scope == C.SCOPE_GLOBAL for e in pack.entries):
            messagebox.showinfo(
                "Global songs",
                "No entry is marked Global yet. Set an entry's scope under "
                "Music & Conditions > Scope.")
            return
        biomes = scopes.biome_dimensions(self.app.biome_custom_attributes)
        blockers = scopes.find_blockers(pack.entries, biomes)
        if not blockers:
            messagebox.showinfo(
                "Global songs",
                "Every global song can be reached in every known biome when only "
                "its own conditions are true.")
            return
        report = scopes.describe_blockers(pack.entries, blockers)
        if not mod_versions.supports(
                self.app.effective_mod_version(), "allow_fallback"):
            messagebox.showwarning(
                "Global songs are blocked",
                report + "\n\nThe target build predates allowFallback, so this "
                "cannot be fixed by enabling it.")
            return
        if not messagebox.askyesno(
                "Global songs are blocked",
                report + "\n\nEnable allowFallback on the blocking entries?\n\n"
                "Note: a blocking entry then falls through to the next valid "
                "entry once its songs are used up, which is not necessarily the "
                "global song."):
            return
        changed = scopes.enable_fallback_on_blockers(pack.entries, biomes)
        self.app.on_pack_entries_changed()
        lib = self.app.library_tab
        if lib.selected_entry_ids:
            lib.rebuild_editor(force=True, refresh_bar=False)
        self.app.set_status(
            f"allowFallback enabled on {len(changed)} entr"
            f"{'y' if len(changed) == 1 else 'ies'}.")

    def _auto_arrange(self):
        self.app.pack.entries = priority.auto_priority_order(
            self.app.pack.entries)
        self.app.mark_dirty()
        self.refresh()
        self.app.library_tab.refresh_tree(keep_selection=True)
        self.app.set_status(
            "Priority order recomputed: rarest/most-specific entries now sit at the top.")

    def _nudge(self, direction: int):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        entries = self.app.pack.entries
        idx = next((i for i, e in enumerate(entries) if e.id == iid), None)
        if idx is None:
            return
        new_idx = idx + direction
        if 0 <= new_idx < len(entries):
            entries[idx], entries[new_idx] = entries[new_idx], entries[idx]
            self.app.mark_dirty()
            self.refresh()
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _on_press(self, event):
        self._drag_start_iid = self.tree.identify_row(event.y)

    def _on_motion(self, event):
        if not self._drag_start_iid:
            return
        target = self.tree.identify_row(event.y)
        if target and target != self._drag_start_iid:
            self.tree.move(self._drag_start_iid, "", self.tree.index(target))

    def _on_release(self, _event):
        if self._drag_start_iid:
            self._sync_order_from_tree()
        self._drag_start_iid = None

    def _sync_order_from_tree(self):
        order_ids = self.tree.get_children("")
        id_to_entry = {e.id: e for e in self.app.pack.entries}
        self.app.pack.entries = [id_to_entry[i]
                                 for i in order_ids if i in id_to_entry]
        self.app.mark_dirty()
        self.refresh()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        theme.install_ctk_theme()
        self.settings = app_settings.load()
        ctk.set_appearance_mode(
            "dark" if self.settings.get("dark_theme", True) else "light")
        super().__init__()
        self.title("ReactiveMusic Songpack Editor")
        self.minsize(900, 600)

        # Keep the native window manager state intact while hiding startup
        # rendering. withdraw() + deiconify() can leave a Tk window
        # withdrawn on Windows, which makes the process keep running while
        # the GUI appears to have closed. A transparent window avoids that
        # state transition entirely.
        self.attributes("-alpha", 0.0)
        self.geometry("1120x760")

        self.pack_data = Songpack()
        self.music_source_folder = None
        self.current_save_folder = None
        self.biome_custom_biomes = {}
        self.biome_custom_tags = {}
        # Songpack-specific biome chart attributes (custom biomes only; the
        # bundled ones come from default_biome_colors.json).
        self.biome_custom_attributes = {}

        # Unsaved-changes tracking (README "Coming soon" #1). Sits on the
        # App itself, not the Songpack, because it is about the *session*
        # (has anything changed since the last load/save), not the data.
        # Set via mark_dirty()/mark_clean() -- see those methods for which
        # actions flip it, and _on_close_window/action_new_songpack/
        # action_load_config for where it's checked or reset.
        self._dirty = False

        # Editor-wide preferences are loaded before the tabs are built so
        # SettingsTab reads the persisted values on construction.
        self.status_var = tk.StringVar(
            value="Ready. Start with File > New Songpack, Load Config…, or Load Music Folder…"
        )

        self._build_menu()
        self.protocol("WM_DELETE_WINDOW", self._on_close_window)
        # Ctrl+S: save back to the current songpack folder without asking
        # for it again (see action_quick_save). bind_all so it works no
        # matter which widget has focus.
        self.bind_all("<Control-s>", lambda _e: self.action_quick_save())
        self._update_title()

        # Logo-gradient backdrop behind the application, kept deliberately subtle.
        self.brand_background = theme.build_background(
            self, bool(self.settings.get("dark_theme", True)))
        self.brand_background.place(x=0, y=0, relwidth=1, relheight=1)
        # Canvas.lower() is the canvas-item API, not the widget-stacking API.
        # Use Tk's window-level command so the backdrop stays behind all CTk widgets.
        self.brand_background.tk.call("lower", self.brand_background._w)

        # Logo-gradient banner above the tabs (theme.build_header).
        self.brand_header = theme.build_header(self)
        self.brand_header.pack(fill="x")

        self.notebook = ctk.CTkTabview(self, command=self._on_tab_changed)
        self.notebook.pack(fill="both", expand=True)

        self.info_tab = InfoTab(self.notebook.add("Songpack Info"), self)
        self.library_tab = LibraryTab(
            self.notebook.add("Music & Conditions"), self)
        self.simulator_tab = simulator_tab.SimulatorTab(
            self.notebook.add("Simulation Map"), self)
        self.priority_tab = PriorityTab(
            self.notebook.add("Priority Order"), self)
        self.settings_tab = settings_tab.SettingsTab(
            self.notebook.add("Settings"), self)

        # The simulation workspace is the primary interactive view, so land
        # there for both a fresh session and a restored songpack.
        self.notebook.set("Simulation Map")

        # Status bar uses the small variant so it doesn't dominate the
        # layout now that the body font is larger.
        status_bar = ctk.CTkLabel(
            self, textvariable=self.status_var,
            font=_SMALL, anchor="w", corner_radius=0,
        )
        status_bar.pack(fill="x", side="bottom")

        self.refresh_all()
        self.apply_theme()

        # Restore the last successfully opened songpack after the UI exists.
        # Like VSCode, a failed restore falls back to a fresh editor session.
        self.after_idle(self._restore_last_songpack)

        # Maximize only after the complete UI has been constructed. The
        # window is transparent during this operation, so the user never
        # sees the intermediate 1120x760 frame or a maximize flash.
        self.after(10, self._maximize_window)
        self.after_idle(lambda: self.attributes("-alpha", 1.0))

    def _restore_last_songpack(self):
        """Restore the last songpack session when its folder still exists.

        Startup restoration is deliberately best-effort: a deleted/moved
        songpack must not prevent the editor from opening. A successful
        restore lands on the Biome Simulator so the restored pack is
        immediately usable as a preview rather than reopening on metadata.
        """
        path = str(self.settings.get("last_songpack_folder", "") or "").strip()
        if not path:
            return
        if not os.path.isdir(path):
            self.settings["last_songpack_folder"] = ""
            self.save_settings()
            return
        try:
            self.pack_data = yaml_io.load_songpack(path)
            biomes, tags = biome_customization.load(path)
            attributes = biome_customization.load_attributes(path)
            mod_versions.apply_to_pack(self.pack_data, mod_versions.load(path))
        except Exception:
            # The session may refer to a folder that still exists but no
            # longer contains a valid songpack. Treat that exactly like a
            # missing restore target rather than interrupting startup.
            self.settings["last_songpack_folder"] = ""
            self.save_settings()
            return

        self.biome_custom_biomes = biomes
        self.biome_custom_tags = tags
        self.biome_custom_attributes = attributes
        self.current_save_folder = path
        music_folder = os.path.join(path, "music")
        self.music_source_folder = music_folder if os.path.isdir(
            music_folder) else None
        self.simulator_tab.reset()
        self.refresh_all()
        self.mark_clean()
        self.notebook.set("Simulation Map")
        self.set_status(
            f"Restored {len(self.pack_data.entries)} entries from {path}")

    def _maximize_window(self):
        """Maximize to the current screen — same effect as clicking the
        window's maximize button. Deferred by self.after(10, ...) in
        __init__ because state('zoomed') can silently no-op if it runs
        before the window has actually been mapped on screen.
        """
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        if self.winfo_width() < screen_w * 0.9 or self.winfo_height() < screen_h * 0.9:
            # state("zoomed") didn't actually take -- fall back to sizing
            # the window to the full screen by hand.
            self.geometry(f"{screen_w}x{screen_h}+0+0")

    @property
    def pack(self) -> Songpack:
        return self.pack_data

    def set_status(self, text: str):
        self.status_var.set(text)

    # -- unsaved-changes tracking -------------------------------------------
    def mark_dirty(self) -> None:
        """Record that app.pack (or its songpack-metadata sidecars) has
        changed since the last successful load/save. Cheap and idempotent,
        so call sites don't need to check first.
        """
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def mark_clean(self) -> None:
        """Call after a load/save/new-songpack has just made the in-memory
        pack match what's on disk (or made a blank pack the new baseline).
        """
        was_dirty = self._dirty
        self._dirty = False
        if was_dirty:
            self._update_title()

    def _update_title(self) -> None:
        self.title("ReactiveMusic Songpack Editor" +
                   ("  \u2022 unsaved changes" if self._dirty else ""))

    def _on_close_window(self) -> None:
        """WM_DELETE_WINDOW handler and File > Exit: confirm before
        discarding unsaved work, exactly like New/Load Config already do.
        """
        if self._dirty and not messagebox.askyesno(
                "Unsaved changes",
                "This songpack has unsaved changes. Exit without saving?"):
            return
        self.destroy()

    def refresh_all(self):
        self.info_tab.push_from_pack()
        self.library_tab.refresh_tree()
        self.priority_tab.refresh()
        self.simulator_tab.refresh()
        self.settings_tab.refresh()

    def _on_tab_changed(self, _event=None):
        self.info_tab.pull_into_pack()
        self.priority_tab.refresh()
        self.library_tab.refresh_tree(keep_selection=True)
        # The simulator caches its plans; entries may have been edited on
        # another tab, so rebuild them whenever the simulator comes into view.
        if self.notebook.get() == "Simulation Map":
            self.simulator_tab.refresh()

    def on_entry_conditions_changed(self, _entry: Entry):
        self.mark_dirty()
        self.library_tab.refresh_tree(keep_selection=True)
        self.priority_tab.refresh()

    def on_pack_entries_changed(self):
        """Entries were added, removed, or edited from somewhere other than
        the Music & Conditions tab's own editor -- currently: the Biome
        Simulator's right-click "edit songs for this biome" case editor
        (biome_case_editor.py). Refresh every view of app.pack.entries so
        the two tabs stay in agreement.
        """
        self.mark_dirty()
        self.library_tab.refresh_tree(keep_selection=True)
        self.priority_tab.refresh()
        self.simulator_tab.refresh()

    def focus_entry_in_library(self, entry_id: str) -> None:
        """Switch to Music & Conditions and select the song row that owns
        ``entry_id`` (its case group's primary entry). Used by the Biome
        Simulator's case editor's "Open full editor" button, for the
        biome/dimension/block/advanced-flag controls it doesn't duplicate.
        """
        group = case_grouping.group_of(self.pack_data, entry_id)
        if not group:
            return
        row_id = group[0].id
        self.notebook.set("Music & Conditions")
        self.library_tab.refresh_tree(keep_selection=False)
        try:
            self.library_tab.tree.selection_set(row_id)
            self.library_tab.tree.see(row_id)
        except Exception:  # noqa: BLE001 - selection is a nicety, not the job
            pass

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
        self.mark_dirty()
        # Rebuilds the editor for the current selection *and* case tab.
        self.library_tab.rebuild_editor(refresh_bar=False)
        self.settings_tab.refresh()
        self.simulator_tab.refresh()
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
        """Apply the current persisted light/dark preference to both CTk and
        the ttk widgets (Treeviews) that CTk doesn't manage.

        Note: app_settings.apply_ttk_theme() may call ttk.Style.theme_use(),
        which resets the ttk style database. We therefore re-apply our
        typography + color scale immediately afterwards so the larger fonts
        and themed Treeviews survive every theme toggle.
        """
        dark = bool(self.settings.get("dark_theme", True))
        ctk.set_appearance_mode("dark" if dark else "light")
        app_settings.apply_ttk_theme(self, dark)
        _configure_ttk_typography(self, dark)
        simulator = getattr(self, "simulator_tab", None)
        if simulator is not None:
            simulator.apply_theme()

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
        self.mark_dirty()
        lib = self.library_tab
        if len(lib.selected_entry_ids) == 1:
            lib.rebuild_editor(refresh_bar=False)
        self.simulator_tab.on_biome_colors_changed()

    # -- menu -------------------------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)

        # Every command goes through a lambda so ui_enhancements.install()'s
        # instance-level reassignment of action_* methods takes effect no
        # matter when install() is called relative to menu construction.
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="New Songpack",
                             command=lambda: self.action_new_songpack())
        filemenu.add_command(label="Load Config…",
                             command=lambda: self.action_load_config())
        filemenu.add_command(label="Load Music Folder…",
                             command=lambda: self.action_load_music_folder())
        filemenu.add_separator()
        filemenu.add_command(label="Save", accelerator="Ctrl+S",
                             command=lambda: self.action_quick_save())
        filemenu.add_command(label="Save Config…",
                             command=lambda: self.action_save_config())
        filemenu.add_separator()
        filemenu.add_command(label="Exit",
                             command=lambda: self._on_close_window())
        menubar.add_cascade(label="File", menu=filemenu)

        helpmenu = tk.Menu(menubar, tearoff=0)
        helpmenu.add_command(
            label="How priority & variety work",
            command=lambda: self.action_show_about())
        menubar.add_cascade(label="Help", menu=helpmenu)

        self.config(menu=menubar)

    # -- actions -------------------------------------------------
    def action_new_songpack(self):
        prompt = "Discard the current songpack and start a new one?"
        if self._dirty:
            prompt = "This songpack has unsaved changes. " + prompt
        if not messagebox.askyesno("New Songpack", prompt):
            return
        self.pack_data = Songpack()
        self.music_source_folder = None
        self.current_save_folder = None
        self.biome_custom_biomes = {}
        self.biome_custom_tags = {}
        self.biome_custom_attributes = {}
        self.simulator_tab.reset()
        self.refresh_all()
        self.mark_clean()
        self.set_status(
            "Started a new, empty songpack. Set its Minecraft version in Songpack Info "
            "so the editor can match the conditions to your mod build.")

    def action_load_config(self):
        if self._dirty and not messagebox.askyesno(
                "Unsaved changes",
                "This songpack has unsaved changes. Discard them and load "
                "a different songpack?"):
            return
        path = filedialog.askdirectory(
            title="Select the songpack folder (containing ReactiveMusic.yaml)")
        if not path:
            return
        try:
            self.pack_data = yaml_io.load_songpack(path)
            # No separate grouping step needed on load any more: cases are
            # derived live from each entry's primary song / biome
            # conditions (see case_grouping.py), so they're correct the
            # moment the entries exist.
            biomes, tags = biome_customization.load(path)
            attributes = biome_customization.load_attributes(path)
            mod_versions.apply_to_pack(self.pack_data, mod_versions.load(path))
        except Exception as exc:  # noqa: BLE001 - surface any load error to the user
            messagebox.showerror("Load failed", str(exc))
            return
        self.biome_custom_biomes = biomes
        self.biome_custom_tags = tags
        self.biome_custom_attributes = attributes
        self.current_save_folder = path
        self.settings["last_songpack_folder"] = path
        self.save_settings()
        self.simulator_tab.reset()
        self.refresh_all()
        self.mark_clean()
        version = self.effective_mod_version()
        target = f", targeting Reactive Music {version}" if version else ""
        self.set_status(
            f"Loaded {len(self.pack_data.entries)} entries from {path}{target}")

    def action_load_music_folder(self):
        # NOTE: ui_enhancements.install() replaces this method with a version
        # that calls _translate_music_folder() first, so the filename
        # normalization still happens when the enhancement is installed.
        # This fallback is only used when the enhancement is not installed.
        folder = filedialog.askdirectory(
            title="Select the folder containing your .mp3/.ogg/.wav files")
        if not folder:
            return
        stems = yaml_io.scan_music_folder(folder)
        self.pack_data.entries, expanded, added = (
            entry_pools.reconcile_music_folder_entries(
                self.pack_data.entries, stems)
        )
        self.music_source_folder = folder
        if added:
            self.mark_dirty()
        self.refresh_all()
        self.set_status(
            f"Found {len(stems)} audio file(s) in {folder}, expanded {expanded} "
            f"pooled song(s), added {added} new blank entries. "
            f"Configure their conditions in the 'Music & Conditions' tab."
        )

    def action_save_config(self):
        # NOTE: ui_enhancements.install() wraps this method to add a
        # save-verification step (reloading the YAML and comparing entries).
        # Keep this method's body intact so the wrapper's original_save()
        # call still works as intended.
        self.info_tab.pull_into_pack()
        if not self.pack_data.entries:
            if not messagebox.askyesno(
                    "Save Config",
                    "This songpack has no entries yet. Save anyway?"):
                return
        if not self._confirm_target_problems():
            return
        if not self._confirm_pack_issues():
            return
        folder = filedialog.askdirectory(
            title="Choose (or create) a folder to save this songpack into")
        if not folder:
            return
        try:
            path = yaml_io.save_songpack(
                self.pack_data, folder, copy_music_from=None)
            biome_customization.save(
                folder, self.biome_custom_biomes, self.biome_custom_tags,
                self.biome_custom_attributes)
            mod_versions.save(folder, self.pack_data)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.current_save_folder = folder
        self.settings["last_songpack_folder"] = folder
        self.save_settings()
        self.mark_clean()
        self.set_status(f"Saved to {path}")
        messagebox.showinfo(
            "Saved",
            f"Songpack saved to:\n{path}\n\n"
            f"Biome customization saved to:\n"
            f"{os.path.join(folder, biome_customization.CONFIG_FILENAME)}\n\n"
            f"Target build saved to:\n"
            f"{os.path.join(folder, mod_versions.TARGET_FILENAME)}",
        )

    def action_quick_save(self) -> None:
        """Ctrl+S / File > Save: write back to the folder this songpack was
        last loaded from or saved to, without asking again. Falls back to
        the full "Save Config…" flow (which prompts for a folder and shows
        the confirmation dialog) the first time a brand-new songpack is
        saved, since there's no folder to reuse yet.

        Unlike "Save Config…", this skips the "Saved" popup (a quick-save
        shouldn't interrupt typing) and skips ui_enhancements' reload/verify
        step, trading a little extra safety for speed on every keystroke of
        Ctrl+S. Use "Save Config…" for the verified, defensive save.
        """
        if not self.current_save_folder:
            self.action_save_config()
            return
        self.info_tab.pull_into_pack()
        if not self._confirm_target_problems():
            return
        if not self._confirm_pack_issues():
            return
        folder = self.current_save_folder
        try:
            path = yaml_io.save_songpack(
                self.pack_data, folder, copy_music_from=None)
            biome_customization.save(
                folder, self.biome_custom_biomes, self.biome_custom_tags,
                self.biome_custom_attributes)
            mod_versions.save(folder, self.pack_data)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.settings["last_songpack_folder"] = folder
        self.save_settings()
        self.mark_clean()
        self.set_status(f"Saved to {path}")

    def _confirm_pack_issues(self) -> bool:
        """Sanity check before writing (pack_validation.py): songless or
        condition-less entries, a bad forceChance, entries that can never play.
        Nothing is changed for the user; they decide whether to save anyway.
        """
        issues = pack_validation.validate_pack(self.pack_data)
        if not issues:
            return True
        shown = "\n".join(f"\u2022 {i.message}" for i in issues[:12])
        if len(issues) > 12:
            shown += f"\n\u2026 and {len(issues) - 12} more"
        return messagebox.askyesno(
            "Check before saving",
            f"{len(issues)} thing(s) look wrong in this songpack:\n\n{shown}\n\n"
            "Nothing was changed. Save anyway?",
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
            "allowFallback defaults to OFF, matching ReactiveMusic's documented YAML default. "
            "Turn it on for entries where you want the mod to fall through to another valid "
            "event after this entry's own song(s) have all played.\n\n"
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
