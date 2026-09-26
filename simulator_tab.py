"""
simulator_tab.py
-----------------
Tab 4: "Simulation Map".

Pick a simulated situation with the sliders at the top (time of day, weather,
world height, underwater, plus an optional collapsible box with the remaining
conditions and a manual text box), then hover / click a biome on the map to
see which songs the mod would play there, in priority order. Double-click a
song to start a playlist that imitates the mod (see simulation.py for the
exact rules); the song that is playing gets a sound-wave marker.

Hovering a biome previews its list. Clicking pins the biome so the list stops
following the pointer (needed to reach the list without crossing other
biomes). While a playlist runs the list stays on the playing biome; pinning
another biome is like "teleporting" there: the current song keeps playing,
unless a forceStop* flag says otherwise, and the next song comes from the
new situation.

A selector above the map switches between two maps of the same style: the
Biomes map (one icon per biome) and the Biome tags map (one icon per tag,
placed at the average temperature/humidity of the biomes it contains, see
biome_customization.tag_attributes). Everything below the map -- list,
playlist, embedded editor -- works on a "subject": a biome name, or "#" + a
tag name. On the tags map the list shows what would play "somewhere inside a
biome of that tag" (simulation.make_tag_state) and the editor edits BIOMETAG=
cases; since the simulator resolves tags through the same membership table,
songs added to a tag also show up on each biome the tag contains.

"Focus on the case matching this situation" (a switch above the list, on by
default): the list is limited to the biome's / tag's own cases that are valid
under the simulated conditions and were written most precisely for them
(case_grouping.best_matching_cases), plus whichever case the editor has open,
and the embedded editor opens the tab of that case. It is a VIEW filter only:
rows keep their index in the full plan as their iid, and playback still follows
the complete mod order (simulation.py), so nothing about fallback chains,
forceStart/Stop or the playlist changes when it is toggled.

All the mod logic lives in simulation.py; this module is view + playback.
Playback goes through audio_preview.get_player(), the same shared player the
song list and the audio editor use.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Set

import customtkinter as ctk

import audio_io
import audio_preview
import biome_case_editor
import biome_chart
import biome_customization
import biome_pooling
import case_grouping
import constants as C
import entry_pools
import mod_versions
import simulation
import theme
import biome_tag_platforms
import yaml_io
from models import Entry

_BODY = ("", 13)
_BODY_BOLD = ("", 13, "bold")
_SECTION = ("", 15, "bold")
_SMALL = ("", 11)
_SMALL_BOLD = ("", 11, "bold")

_TIME_OPTIONS = [("SUNRISE", "SUNRISE"), ("DAY", "DAY"),
                 ("SUNSET", "SUNSET"), ("NIGHT", "NIGHT")]
_WEATHER_OPTIONS = [(None, "NONE"), ("RAIN", "RAIN"),
                    ("STORM", "STORM"), ("SNOW", "SNOW")]
_HEIGHT_OPTIONS = [("DEEP_UNDERGROUND", "DEEP UNDRG"), ("UNDERGROUND", "UNDERG"),
                   (None, "NONE"), ("HIGH_UP", "HIGH UP")]

# Categories already covered by the sliders / switch at the top.
_SLIDER_CATEGORIES = (C.CATEGORY_TIME, C.CATEGORY_WEATHER,
                      C.CATEGORY_HEIGHT, C.CATEGORY_UNDERWATER)

#: Marks a subject as a biome tag ("#IS_HOT"), as opposed to a biome ("desert").
#: Never occurs at the start of a biome id, so the two can share one cache/state.
_TAG_PREFIX = "#"

_MANUAL_HINT = (
    "Facts that are true in this situation, one per line. Examples:\n"
    "  DIM=NETHER      BLOCK=nether_bricks,1000      BIOMETAG=IS_WET      HOME\n"
    "BLOCK= and tags missing from the built-in table can only match if listed here."
)


# ---------------------------------------------------------------------------
# A discrete slider: N labelled positions, exactly one selected
# ---------------------------------------------------------------------------
class StepSlider(ctk.CTkFrame):
    def __init__(self, parent, title: str, options, index: int = 0,
                 command=None):
        super().__init__(parent, fg_color="transparent")
        self._choices = list(options)
        self._on_change = command
        count = len(self._choices)
        self._selected = max(0, min(index, count - 1))

        ctk.CTkLabel(self, text=title, font=_SMALL_BOLD, anchor="w").pack(
            fill="x", padx=10, pady=(4, 0))
        self._step_slider = ctk.CTkSlider(
            self, from_=0, to=count - 1, number_of_steps=count - 1,
            command=self._on_slide)
        self._step_slider.set(self._selected)
        self._step_slider.pack(fill="x", padx=10, pady=(4, 0))

        row = ctk.CTkFrame(self, fg_color="transparent", height=22)
        row.pack(fill="x", pady=(0, 4))
        self._tick_labels: List[ctk.CTkLabel] = []
        for i, (_token, text) in enumerate(self._choices):
            t = i / (count - 1)
            label = ctk.CTkLabel(row, text=text, font=_SMALL)
            if i == 0:
                label.place(relx=0.0, x=6, rely=0.5, anchor="w")
            elif i == count - 1:
                label.place(relx=1.0, x=-6, rely=0.5, anchor="e")
            else:
                # Line the label up with the slider handle, which travels
                # roughly 18 px inside each edge of the widget.
                label.place(relx=t, x=int(18 - 36 * t), rely=0.5,
                            anchor="center")
            label.bind("<Button-1>", lambda _e, n=i: self.select(n))
            self._tick_labels.append(label)
        self._style()

    def value(self) -> Optional[str]:
        return self._choices[self._selected][0]

    def select(self, index: int) -> None:
        self._step_slider.set(index)
        self._apply(index)

    def _on_slide(self, raw) -> None:
        self._apply(int(round(float(raw))))

    def _apply(self, index: int) -> None:
        if index == self._selected:
            return
        self._selected = index
        self._style()
        if self._on_change:
            self._on_change()

    def _style(self) -> None:
        for i, label in enumerate(self._tick_labels):
            if i == self._selected:
                label.configure(text_color=theme.ACCENT_TEXT,
                                font=_SMALL_BOLD)
            else:
                label.configure(text_color=("gray40", "gray70"), font=_SMALL)


# ---------------------------------------------------------------------------
# The tab
# ---------------------------------------------------------------------------
class SimulatorTab(ctk.CTkFrame):
    _DIMENSIONS = ["All", "Overworld", "Nether", "End"]
    _DIMENSION_IDS = {"Overworld": "minecraft:overworld",
                      "Nether": "minecraft:the_nether",
                      "End": "minecraft:the_end"}
    _WAVE_FRAMES = ("(♪)", "((♪))", "(((♪)))")
    _POLL_MS = 300
    _MODE_BIOMES = "Biomes"
    _MODE_TAGS = "Biome tags"

    def __init__(self, parent, app: "App"):  # noqa: F821
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.player = audio_preview.get_player()

        # Which map is showing: "biomes" or "tags".
        self._map_mode = "biomes"

        # Which subject (biome, or "#tag") the list shows.
        self._pinned: Optional[str] = None      # clicked
        self._preview: Optional[str] = None     # last hovered (sticky)
        self._play_biome: Optional[str] = None  # subject the playlist follows

        # Playlist state.
        self._playlist_active = False
        self._followed_valid: Set[str] = set()
        self._now_song: Optional[str] = None
        self._now_path: Optional[str] = None
        self._external_stop = False
        self._self_call = False        # True while WE drive the player
        self._tick_job = None
        self._manual_job = None
        self._wave_step = 0
        self._selected_case_id: Optional[str] = None
        # Focus on the case that matches the simulated conditions (see the
        # module docstring). Session-only, like the other simulator controls.
        self.focus_var = tk.BooleanVar(master=self, value=True)

        self._more_open = False
        self._extra_vars: Dict[str, tk.BooleanVar] = {}
        self._plan_cache: Dict[str, simulation.Plan] = {}
        self._view_cache: Optional[entry_pools.LogicalView] = None
        # forceStartMusicOnValid entries waiting for the music to stop.
        self._armed_start: Set[str] = set()
        self._facts_cache = None
        self._path_cache: Dict[str, Optional[str]] = {}

        self._build_conditions()
        self._build_body()
        self.player.add_listener(self._on_player_state)
        self._refresh_panel()
        self._show_editor_for(self._pinned)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_conditions(self) -> None:
        card = ctk.CTkFrame(self, corner_radius=10)
        card.pack(fill="x", padx=8, pady=(8, 4))

        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(head, text="Simulated situation", font=_SECTION).pack(
            side="left")
        self.more_btn = ctk.CTkButton(
            head, text="▸ More conditions", width=160, font=_BODY,
            command=self._toggle_more)
        self.more_btn.pack(side="right")

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=(0, 6))
        for col, weight in enumerate((3, 3, 3, 2)):
            row.grid_columnconfigure(col, weight=weight)

        self.time_slider = StepSlider(
            row, "Time of day", _TIME_OPTIONS, index=1,
            command=self._on_conditions_changed)
        self.weather_slider = StepSlider(
            row, "Weather", _WEATHER_OPTIONS, index=0,
            command=self._on_conditions_changed)
        self.height_slider = StepSlider(
            row, "World height", _HEIGHT_OPTIONS, index=2,
            command=self._on_conditions_changed)
        self.time_slider.grid(row=0, column=0, sticky="ew", padx=4)
        self.weather_slider.grid(row=0, column=1, sticky="ew", padx=4)
        self.height_slider.grid(row=0, column=2, sticky="ew", padx=4)

        water = ctk.CTkFrame(row, fg_color="transparent")
        water.grid(row=0, column=3, sticky="ew", padx=4)
        ctk.CTkLabel(water, text="Underwater", font=_SMALL_BOLD,
                     anchor="w").pack(fill="x", padx=10, pady=(4, 0))
        self.underwater_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            water, text="UNDERWATER", variable=self.underwater_var,
            font=_SMALL, command=self._on_conditions_changed,
        ).pack(anchor="w", padx=10, pady=(6, 0))

        # ---- collapsible: remaining conditions + manual facts (hidden) ----
        self.more_frame = ctk.CTkFrame(card, fg_color="transparent")

        left = ctk.CTkFrame(self.more_frame, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True)
        for cat in C.FIXED_CATEGORY_ORDER:
            if cat in _SLIDER_CATEGORIES:
                continue
            definition = C.FIXED_CATEGORIES[cat]
            line = ctk.CTkFrame(left, fg_color="transparent")
            line.pack(fill="x", pady=1)
            ctk.CTkLabel(line, text=definition["label"] + ":",
                         font=_SMALL_BOLD, width=72, anchor="w").pack(
                             side="left")
            for option in definition["options"]:
                var = tk.BooleanVar(value=False)
                self._extra_vars[option] = var
                ctk.CTkCheckBox(
                    line, text=option, variable=var, font=_BODY,
                    command=self._on_conditions_changed,
                ).pack(side="left", padx=(0, 12))

        right = ctk.CTkFrame(self.more_frame, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        ctk.CTkLabel(right, text="Manual conditions", font=_SMALL_BOLD,
                     anchor="w").pack(fill="x")
        self.manual_text = ctk.CTkTextbox(right, height=84, font=_BODY)
        self.manual_text.pack(fill="x", pady=(2, 2))
        self.manual_text.bind("<KeyRelease>", self._on_manual_key)
        ctk.CTkLabel(right, text=_MANUAL_HINT, font=_SMALL,
                     text_color=("gray40", "gray70"), justify="left",
                     anchor="w", wraplength=520).pack(fill="x")

    def _build_body(self) -> None:
        """Build the simulator as three persistent columns.

        The map, playlist, and biome editor are sibling panels so selecting a
        biome no longer requires opening a separate editor window. The map is
        kept square and centred in its column; the other two columns use the
        full available height for their scrollable content.
        """
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        body.grid_columnconfigure(0, weight=5, uniform="simulation_columns")
        body.grid_columnconfigure(1, weight=3, uniform="simulation_columns")
        body.grid_columnconfigure(2, weight=3, uniform="simulation_columns")
        body.grid_rowconfigure(0, weight=1)

        # ---- map ---------------------------------------------------------
        chart_wrap = ctk.CTkFrame(body, corner_radius=10)
        chart_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        # Switch between the biome map and the biome-tag map.
        self.map_mode_var = tk.StringVar(value=self._MODE_BIOMES)
        ctk.CTkSegmentedButton(
            chart_wrap, values=[self._MODE_BIOMES, self._MODE_TAGS],
            variable=self.map_mode_var, font=_BODY,
            command=self._on_map_mode_changed,
        ).pack(fill="x", padx=10, pady=(8, 0))

        bar = ctk.CTkFrame(chart_wrap, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(6, 0))
        self.map_title_label = ctk.CTkLabel(
            bar, text=self._map_title(), font=_BODY_BOLD)
        self.map_title_label.pack(side="left")
        self.chart_dimension_var = tk.StringVar(value="All")
        ctk.CTkSegmentedButton(
            bar, values=self._DIMENSIONS, variable=self.chart_dimension_var,
            font=_BODY, command=lambda _v: self.after_idle(self._redraw_chart),
        ).pack(side="right")

        map_host = ctk.CTkFrame(chart_wrap, fg_color="transparent")
        map_host.pack(fill="both", expand=True, padx=6, pady=6)
        self._map_host = map_host

        self.chart = biome_chart.BiomeChart(
            map_host,
            biomes=self._chart_biomes,
            color_of=self._chart_color,
            active=self._active_keys,
            on_toggle=self._on_chart_click,
            on_hover=self._on_chart_hover,
            tooltip_lines=self._tooltip_lines,
            action_labels=("click to select", "click to deselect"),
            on_right_click=self._on_chart_right_click,
            backdrop=self._chart_backdrop,
            dark=bool(self.app.settings.get("dark_theme", True)),
            height=460,
        )
        # Let the chart frame fill the map column. Its actual Canvas is the
        # square element; sizing the Canvas directly avoids depending on
        # CustomTkinter's frame geometry propagation for the renderer.
        self.chart.pack(fill="both", expand=True)
        self._chart_side = 0
        map_host.bind("<Configure>", self._fit_chart_square, add="+")
        self.after_idle(self._fit_chart_square)

        # ---- playlist ----------------------------------------------------
        panel = ctk.CTkFrame(body, corner_radius=10)
        panel.grid(row=0, column=1, sticky="nsew", padx=4)

        self.title_label = ctk.CTkLabel(
            panel, text="Biome: —", font=_SECTION, anchor="w")
        self.title_label.pack(fill="x", padx=12, pady=(10, 0))
        self.mode_label = ctk.CTkLabel(
            panel, text="", font=_SMALL, anchor="w", justify="left",
            text_color=("gray40", "gray70"), wraplength=360)
        self.mode_label.pack(fill="x", padx=12)
        ctk.CTkSwitch(
            panel, text="Focus on the case matching this situation",
            variable=self.focus_var, font=_SMALL,
            command=self._on_focus_toggled,
        ).pack(anchor="w", padx=12, pady=(6, 0))
        self.now_label = ctk.CTkLabel(
            panel, text="Not playing", font=_BODY_BOLD, anchor="w",
            justify="left", wraplength=360)
        self.now_label.pack(fill="x", padx=12, pady=(6, 0))

        transport = ctk.CTkFrame(panel, fg_color="transparent")
        transport.pack(fill="x", padx=8, pady=(6, 0))
        self.play_btn = ctk.CTkButton(
            transport, text="▶ Play playlist", width=130, font=_BODY,
            command=self._on_play_clicked)
        self.play_btn.pack(side="left", padx=3)
        ctk.CTkButton(transport, text="⏭ Next", width=72, font=_BODY,
                      command=self._on_next_clicked).pack(side="left", padx=3)
        ctk.CTkButton(
            transport, text="■ Stop", width=72, font=_BODY,
            **theme.NEUTRAL_BUTTON,
            command=lambda: self._stop_playlist("Playlist stopped."),
        ).pack(side="left", padx=3)

        tree_wrap = ctk.CTkFrame(panel, fg_color="transparent")
        tree_wrap.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self.tree = ttk.Treeview(
            tree_wrap, columns=("wave", "song", "entry", "info"),
            show="headings", selectmode="browse")
        for key, text, width, anchor, stretch in (
            ("wave", "", 58, "center", False),
            ("song", "Song", 150, "w", True),
            ("entry", "Entry", 48, "center", False),
            ("info", "Notes", 120, "w", False),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=stretch)
        self.tree.tag_configure("dim", foreground="gray50")
        self._style_tree_tags()
        scroll = ttk.Scrollbar(
            tree_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        self.legend_label = ctk.CTkLabel(
            panel, text="", font=_SMALL, anchor="w", justify="left",
            text_color=("gray40", "gray70"), wraplength=360)
        self.legend_label.pack(fill="x", padx=12, pady=(0, 10))

        # ---- biome editor ------------------------------------------------
        self.editor_wrap = ctk.CTkFrame(body, corner_radius=10)
        self.editor_wrap.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        self.editor_placeholder = ctk.CTkLabel(
            self.editor_wrap,
            text=self._placeholder_text(),
            font=_BODY, text_color=("gray40", "gray70"),
            justify="center", wraplength=300,
        )
        self.editor_placeholder.pack(expand=True, padx=20)
        self.editor_panel = None

    def _fit_chart_square(self, _event=None) -> None:
        """Keep the biome map Canvas 1:1 and centred in its column.

        The chart frame itself fills the column, while its Canvas is placed
        as a square. This keeps the renderer's coordinate system square
        without relying on nested CustomTkinter frame propagation.
        """
        host = getattr(self, "_map_host", None)
        chart = getattr(self, "chart", None)
        if host is None or chart is None:
            return
        try:
            width = max(1, host.winfo_width() - 12)
            height = max(1, host.winfo_height() - 12)
            side = max(160, min(width, height))
            if side == self._chart_side:
                return
            self._chart_side = side
            canvas = chart.canvas
            canvas.place(
                relx=0.5, rely=0.5, anchor="center",
                width=side, height=side,
            )
            canvas.after_idle(chart.redraw)
        except tk.TclError:
            pass

    def _show_editor_for(self, biome: Optional[str]) -> None:
        """Show the embedded case editor only for the selected subject: a
        biome, or (on the tags map) a biome tag.
        """
        if self.editor_panel is not None:
            try:
                self.editor_panel.destroy()
            except tk.TclError:
                pass
            self.editor_panel = None
        if not biome:
            self.editor_placeholder.pack(expand=True, padx=20)
            return
        self.editor_placeholder.pack_forget()
        _kind, name = self._describe(biome)
        self.editor_panel = biome_case_editor.BiomeCaseEditorPanel(
            self.editor_wrap, self.app, name,
            is_tag=self._is_tag_subject(biome),
            on_case_selected=self._on_case_selected)
        self.editor_panel.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # public hooks used by App
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """The songpack (entries / order / songs) or music folder may have
        changed: drop cached plans and repaint.
        """
        self._invalidate()
        self._path_cache.clear()
        if self._playlist_active and self._play_biome:
            self._followed_valid = set(
                self._plan_for(self._play_biome).valid_ids)
        self._refresh_panel()
        self.after_idle(self._redraw_chart)

    def reset(self) -> None:
        """A different songpack was loaded / created."""
        if self._playlist_active:
            self._stop_playlist()
        self._pinned = None
        self._preview = None
        self._show_editor_for(None)
        self.refresh()

    def apply_theme(self) -> None:
        self.chart.set_dark(bool(self.app.settings.get("dark_theme", True)))
        self._style_tree_tags()

    def _style_tree_tags(self) -> None:
        """Colour the playlist's "playing" / "selected case" rows. A ttk tag
        holds one colour, not a light/dark pair, so this is re-applied from
        apply_theme() whenever the theme flips.
        """
        dark = bool(self.app.settings.get("dark_theme", True))
        selected = theme.pick(theme.TREE_SELECTED_CASE, dark)
        self.tree.tag_configure("playing",
                                foreground=theme.pick(theme.TREE_PLAYING, dark))
        self.tree.tag_configure("selected_case", foreground=selected)
        self.tree.tag_configure("playing_selected", foreground=selected)

    def on_biome_colors_changed(self) -> None:
        self._redraw_chart()

    # ------------------------------------------------------------------
    # map mode + subjects
    # ------------------------------------------------------------------
    @staticmethod
    def _is_tag_subject(subject: Optional[str]) -> bool:
        return bool(subject) and subject.startswith(_TAG_PREFIX)

    @staticmethod
    def _describe(subject: str):
        """('Biome' | 'Biome tag', bare name) for a subject."""
        if subject.startswith(_TAG_PREFIX):
            return "Biome tag", subject[len(_TAG_PREFIX):]
        return "Biome", subject

    def _subject(self, name: str) -> str:
        """The subject for an icon of the map currently showing."""
        return _TAG_PREFIX + name if self._map_mode == "tags" else name

    def _map_title(self) -> str:
        noun = "Biome tag" if self._map_mode == "tags" else "Biome"
        return f"{noun} map — click to select"

    def _placeholder_text(self) -> str:
        if self._map_mode == "tags":
            return ("Select a biome tag on the map to edit its cases.\n\n"
                    "Songs added to a tag play in every biome it contains, "
                    "and show up for those biomes on the Biomes map.")
        return ("Select a biome on the map to edit its cases.\n\n"
                "The editor stays here while you work, so the map and playlist "
                "remain visible.")

    def _on_map_mode_changed(self, label: str) -> None:
        """Swap the map between biomes and biome tags. The pinned / hovered
        subject belongs to the map it was picked on, so it is dropped; a
        running playlist is left alone (the list keeps following the playing
        subject, exactly as when a biome is unpinned).
        """
        mode = "tags" if label == self._MODE_TAGS else "biomes"
        if mode == self._map_mode:
            return
        self._map_mode = mode
        self._pinned = None
        self._preview = None
        self._selected_case_id = None
        self.map_title_label.configure(text=self._map_title())
        self.editor_placeholder.configure(text=self._placeholder_text())
        self._show_editor_for(None)
        self._refresh_panel()
        # Synchronous on purpose: the chart's icons must match the new mode
        # before the next mouse move asks for a tooltip.
        self._redraw_chart()

    # ------------------------------------------------------------------
    # conditions
    # ------------------------------------------------------------------
    def _toggle_more(self) -> None:
        self._more_open = not self._more_open
        if self._more_open:
            self.more_frame.pack(fill="x", padx=10, pady=(0, 8))
            self.more_btn.configure(text="▾ More conditions")
        else:
            self.more_frame.pack_forget()
            self.more_btn.configure(text="▸ More conditions")

    def _on_manual_key(self, _event=None) -> None:
        if self._manual_job is not None:
            try:
                self.after_cancel(self._manual_job)
            except tk.TclError:
                pass
        self._manual_job = self.after(300, self._commit_manual)

    def _commit_manual(self) -> None:
        self._manual_job = None
        self._on_conditions_changed()

    def _invalidate(self) -> None:
        self._plan_cache.clear()
        self._view_cache = None
        self._facts_cache = None

    def _view(self) -> entry_pools.LogicalView:
        """The entries as ReactiveMusic will read them (neighbouring entries
        with identical rules are one song pool, exactly as saved -- see
        entry_pools.py). Every plan is built from this, never from the raw
        list, so what is simulated is what the saved file does.
        """
        if self._view_cache is None:
            self._view_cache = entry_pools.logical_view(self.app.pack.entries)
        return self._view_cache

    def _facts(self):
        if self._facts_cache is None:
            flags: Set[str] = set()
            for slider in (self.time_slider, self.weather_slider,
                           self.height_slider):
                value = slider.value()
                if value:
                    flags.add(value)
            if self.underwater_var.get():
                flags.add("UNDERWATER")
            for token, var in self._extra_vars.items():
                if var.get():
                    flags.add(token)
            manual = simulation.parse_manual(
                self.manual_text.get("1.0", "end"))
            self._facts_cache = (flags, manual)
        return self._facts_cache

    def _on_conditions_changed(self) -> None:
        self._invalidate()
        self._context_changed()

    # ------------------------------------------------------------------
    # plans
    # ------------------------------------------------------------------
    def _dimension_of(self, biome: str) -> str:
        found = biome_customization.load_app_dimensions().get(biome)
        return found or "minecraft:overworld"   # custom biomes: assume overworld

    def _tag_dimensions(self, tag: str) -> Set[str]:
        """Every dimension the tag's biomes live in (see make_tag_state)."""
        members = biome_customization.tag_members(
            tag, self.app.biome_custom_tag_members)
        return {self._dimension_of(b) for b in members} or {"minecraft:overworld"}

    def _compiled_reachable_songs(self, biome: str, flags, manual) -> Optional[Set[str]]:
        """Which songs actually reach the mod for `biome`, per the file the
        songpack will be SAVED as -- or None when biome pooling is off.

        `_plan_for` below plans from the AUTHORED entries
        (`entry_pools.logical_view(self.app.pack.entries)`), because that is
        what keeps entry ids, "#n" numbers, case focus and double-click
        playback all pointing at real entries in the pack. But when two
        overlapping BIOMETAG=/BIOME= entries share a biome, App.output_pooler()
        (Settings: "pool the songs of entries that overlap on the same
        biomes") compiles them at save time into ONE shared per-biome entry
        (see biome_pooling.py) -- and the mod only ever reads that compiled
        file. Planning from the authored entries alone therefore
        under-reports reachability: whichever authored entry happens to be
        valid first "wins" and blocks the others, even though their songs
        would genuinely share one rotation once saved.

        This recomputes the same transform save uses (without touching
        App.last_pooling_report, which is save-time-only bookkeeping) and
        returns the set of songs that are reachable in ITS plan, so
        `_plan_for` can correct just the `reachable` flag of the authored
        plan's items -- their entry ids/positions/etc. stay the authored
        ones. Tag subjects never call this: a tag subject has no single
        biome for BIOME= entries to match, so pooling doesn't apply to it.
        """
        if not self.app.settings.get("pool_overlapping_biomes", True):
            return None
        fallback_ok = mod_versions.supports(
            self.app.effective_mod_version(), "allow_fallback")
        biomes = list(biome_customization.load_app_dimensions())
        result = biome_pooling.pool_overlapping_biomes(
            self.app.pack.entries, biomes=biomes, tags_of=simulation.biome_tags,
            residual_fallback=fallback_ok)
        compiled_view = entry_pools.logical_view(result.entries)
        state = simulation.make_state(
            biome, self._dimension_of(biome), flags, manual)
        compiled_plan = simulation.build_plan(
            compiled_view.entries, state, compiled_view.positions)
        return {item.song for item in compiled_plan.items if item.reachable}

    def _plan_for(self, subject: str) -> simulation.Plan:
        """The plan for a subject: a biome name, or "#tag" for a biome tag."""
        plan = self._plan_cache.get(subject)
        if plan is None:
            flags, manual = self._facts()
            if self._is_tag_subject(subject):
                tag = subject[len(_TAG_PREFIX):]
                state = simulation.make_tag_state(
                    tag, self._tag_dimensions(tag), flags, manual)
            else:
                state = simulation.make_state(
                    subject, self._dimension_of(subject), flags, manual)
            view = self._view()
            plan = simulation.build_plan(view.entries, state, view.positions)
            if not self._is_tag_subject(subject):
                compiled_reachable = self._compiled_reachable_songs(
                    subject, flags, manual)
                if compiled_reachable is not None:
                    for item in plan.items:
                        item.reachable = item.song in compiled_reachable
            self._plan_cache[subject] = plan
        return plan

    def _displayed_biome(self) -> Optional[str]:
        if self._pinned:
            return self._pinned
        if self._playlist_active and self._play_biome:
            return self._play_biome
        return self._preview

    # ------------------------------------------------------------------
    # chart callbacks
    # ------------------------------------------------------------------
    def _chart_biomes(self) -> dict:
        """Data source for the chart: biomes, or tags on the tags map. Both
        are {name: {temperature, humidity, erosion, weirdness}}.
        """
        attrs = biome_customization.all_attributes(
            self.app.biome_custom_attributes)
        tags_mode = self._map_mode == "tags"
        if tags_mode:
            # Averaged over each tag's biomes, see tag_attributes().
            attrs = biome_customization.tag_attributes(
                attrs, self.app.biome_custom_tag_members)
            attrs = {t: a for t, a in attrs.items()
                     if biome_tag_platforms.tag_available(
                     t, self.app.pack.platform, self.app.pack.minecraft_version)}
            if not self.app.settings.get("show_empty_biome_tags", False):
                attrs = {
                    t: a for t, a in attrs.items()
                    if biome_customization.tag_members(
                        t, self.app.biome_custom_tag_members)
                }
        wanted = self._DIMENSION_IDS.get(self.chart_dimension_var.get())
        if not wanted:
            return attrs
        dimension_of = biome_customization.load_app_dimensions()
        if tags_mode:
            # A tag belongs to a dimension when any of its biomes does; its
            # position is unaffected, so icons don't jump when filtering.
            return {t: a for t, a in attrs.items()
                    if any(dimension_of.get(b) == wanted
                           for b in biome_customization.tag_members(
                               t, self.app.biome_custom_tag_members))}
        return {n: a for n, a in attrs.items() if dimension_of.get(n) == wanted}

    def _chart_backdrop(self) -> dict:
        """Situation -> map background layers (see biome_chart.render_backdrop).
        Read from the same flags as the plans, so sliders, the extra
        checkboxes and the manual box all drive it, and it repaints through
        the existing _context_changed -> _redraw_chart path.
        """
        flags, _manual = self._facts()
        if "NIGHT" in flags:
            night = 1.0
        elif flags & {"SUNRISE", "SUNSET"}:
            night = 0.5
        else:
            night = 0.0
        weather = next(
            (w for w in ("STORM", "RAIN", "SNOW") if w in flags), None)
        return {"night": night, "underwater": "UNDERWATER" in flags,
                "weather": weather}

    def _chart_color(self, name: str) -> str:
        """Icon colour: the biome's colour, or a tag's (its songpack override,
        else the average of its biomes' colours -- see LibraryTab._biome_color).
        """
        return self.app.library_tab._biome_color(name, self._map_mode == "tags")

    def _active_keys(self) -> set:
        subject = self._pinned or (self._play_biome if self._playlist_active
                                   else None)
        # A subject picked on the other map has no icon here to highlight.
        if not subject or self._is_tag_subject(subject) != (self._map_mode == "tags"):
            return set()
        return {biome_chart.normalize_name(self._describe(subject)[1])}

    def _redraw_chart(self) -> None:
        try:
            if self.chart.winfo_exists():
                self.chart.redraw()
        except tk.TclError:
            pass

    def _tooltip_lines(self, name: str) -> List[str]:
        lines: List[str] = []
        if self._map_mode == "tags":
            count = len(biome_customization.tag_members(
                name, self.app.biome_custom_tag_members))
            lines.append(f"contains {count} biome{'' if count == 1 else 's'}")
        reachable = [i for i in self._plan_for(self._subject(name)).items
                     if i.reachable]
        if not reachable:
            return lines + ["no song for these conditions"]
        lines += [f"{n}. {it.song}   (#{it.entry_index})"
                  for n, it in enumerate(reachable[:6], start=1)]
        if len(reachable) > 6:
            lines.append(f"… +{len(reachable) - 6} more")
        return lines

    def _on_chart_hover(self, name: Optional[str]) -> None:
        if name is None:          # the preview is sticky on purpose
            return
        subject = self._subject(name)
        if subject == self._preview:
            return
        self._preview = subject
        if not self._pinned and not self._playlist_active:
            self._refresh_panel()

    def _on_chart_right_click(self, name: str) -> None:
        """Right-clicking a biome selects it just like a left-click.

        The editor is now permanently embedded in the third column, so there
        is no separate right-click-only window to open.
        """
        self._on_chart_click(name)

    def _on_chart_click(self, name: str) -> None:
        subject = self._subject(name)
        self._preview = subject
        if self._pinned == subject:
            self._pinned = None
        else:
            self._pinned = subject
            if self._playlist_active:
                self._play_biome = subject
        self._selected_case_id = None
        self._show_editor_for(self._pinned)
        self._context_changed()

    # ------------------------------------------------------------------
    # list panel
    # ------------------------------------------------------------------
    def _song_path(self, song: str) -> Optional[str]:
        if song not in self._path_cache:
            folder = getattr(self.app, "music_source_folder", None)
            self._path_cache[song] = (
                audio_io.resolve_song_path(folder, song,
                                           yaml_io.AUDIO_EXTENSIONS)
                if folder else None)
        return self._path_cache[song]

    def _now_text(self) -> str:
        if not self._playlist_active or not self._now_song:
            return "Not playing"
        plan = self._plan_for(self._play_biome) if self._play_biome else None
        idx = plan.find_song(self._now_song) if plan else None
        if idx is None:
            return f"Now playing: {self._now_song}  (not in the current list)"
        return (f"Now playing: {self._now_song}  "
                f"(entry #{plan.items[idx].entry_index})")

    def _update_transport(self) -> None:
        if not self._playlist_active:
            text = "▶ Play playlist"
        elif self.player.is_paused():
            text = "▶ Resume"
        else:
            text = "⏸ Pause"
        self.play_btn.configure(text=text)

    def _refresh_panel(self) -> None:
        tree = self.tree
        tree.delete(*tree.get_children())
        self._update_transport()
        self.now_label.configure(text=self._now_text())

        biome = self._displayed_biome()
        if biome is None:
            noun = "biome tag" if self._map_mode == "tags" else "biome"
            self.title_label.configure(text=f"{noun.capitalize()}: —")
            self.mode_label.configure(
                text=f"Hover a {noun} on the map to preview the songs that would "
                "play there; click it to pin the list.")
            self.legend_label.configure(text="")
            return

        kind, label = self._describe(biome)
        self.title_label.configure(text=f"{kind}: {label}")
        if self._pinned:
            mode = "Pinned — click it again to unpin."
        elif self._playlist_active:
            mode = "Following the playing list — click another icon to move there."
        else:
            mode = "Preview — click an icon to pin it; hovering others changes this list."
        self.mode_label.configure(text=mode)

        plan = self._plan_for(biome)
        # The editor selects REAL entries; the plan lists logical ones (a run
        # of identical neighbours is one song pool), so translate.
        selected_id = (self._view().rep_of.get(self._selected_case_id,
                                               self._selected_case_id)
                       if self._selected_case_id else None)
        shown = self._focus_positions(biome, plan)
        hidden = 0
        for i, item in enumerate(plan.items):
            # Focus only hides rows. The iid stays the index in the FULL plan,
            # which double-click, playback and the wave animation rely on.
            if (shown is not None and item.entry_index not in shown
                    and not shown.intersection(item.also_in)):
                hidden += 1
                continue
            playing = self._playlist_active and item.song == self._now_song
            wave = ""
            if playing:
                wave = "⏸" if self.player.is_paused() else \
                    self._WAVE_FRAMES[self._wave_step % len(self._WAVE_FRAMES)]
            notes = []
            if item.scope != "normal":
                notes.append(item.scope)
            if not item.reachable:
                notes.append("unreachable")
            elif item.allow_fallback:
                notes.append("→ fallback")
            else:
                notes.append("loops")
            if self.app.music_source_folder and not self._song_path(item.song):
                notes.append("no file")
            if item.also_in:
                notes.append("also " + ",".join(f"#{n}" for n in item.also_in))
            selected = (
                selected_id is not None
                and item.entry_id == selected_id
            )
            if playing and selected:
                tags = ("playing_selected",)
            elif selected:
                tags = ("selected_case",)
            elif playing:
                tags = ("playing",)
            else:
                tags = (("dim",) if not item.reachable else ())
            tree.insert("", "end", iid=str(i), tags=tags, values=(
                wave, item.song, f"#{item.entry_index}", " · ".join(notes)))

        reachable = sum(1 for it in plan.items if it.reachable)
        if not plan.items:
            parts = ["No entry matches these conditions in this biome."]
        else:
            parts = [f"{plan.valid_count} matching "
                     f"{'entry' if plan.valid_count == 1 else 'entries'} · "
                     f"{reachable} song(s) can play."]
            if reachable < len(plan.items):
                parts.append(
                    "Dimmed = unreachable: an entry above has no allowFallback, "
                    "so it repeats instead of falling through.")
        if shown is not None and plan.items:
            noun = kind.lower()
            if hidden == len(plan.items):
                parts.append(
                    f"Focus: no case of this {noun} matches these conditions; "
                    f"{hidden} song(s) from other entries are hidden.")
            elif hidden:
                parts.append(
                    f"Focus: showing the best-matching case; {hidden} song(s) from "
                    "other entries are hidden (playback still follows the full order).")
        if selected_id:
            selected = next(
                (it for it in plan.items if it.entry_id == selected_id),
                None,
            )
            if selected is None:
                parts.append(
                    "Selected case is not part of this situation's plan.")
            elif selected.reachable:
                parts.append(
                    "★ Selected case is reachable under the current conditions.")
            else:
                parts.append(
                    "★ Selected case matches, but is unreachable because an entry "
                    "above it does not allow fallback."
                )
        if self._is_tag_subject(biome):
            parts.append(
                "Tag view: entries that need one specific BIOME= are not listed.")
        if plan.pending:
            notes = sorted({n for _idx, ns in plan.pending for n in ns})
            parts.append(
                f"⚠ {len(plan.pending)} hidden "
                f"{'entry depends' if len(plan.pending) == 1 else 'entries depend'}"
                " on facts the simulator can't infer: "
                + "; ".join(notes)[:110]
                + ". List them under More conditions to test them.")
        self.legend_label.configure(text="  ".join(parts))

    # ------------------------------------------------------------------
    # focus: the case that matches the simulated conditions
    # ------------------------------------------------------------------
    def _focus_cases(self, subject: str) -> List[Entry]:
        """The subject's own real entries that are valid under the simulated
        conditions and the most specific of those (best_matching_cases): "the
        case for this set of conditions". Validity is read from the same plan
        the list shows, so the two cannot disagree.
        """
        _kind, name = self._describe(subject)
        view = self._view()
        valid_ids = self._plan_for(subject).valid_ids
        valid = [e for e in case_grouping.biome_cases(
            self.app.pack, name, self._is_tag_subject(subject))
            if view.rep_of.get(e.id) in valid_ids]
        return case_grouping.best_matching_cases(valid)

    def _focus_positions(self, subject: str,
                         plan: simulation.Plan) -> Optional[Set[int]]:
        """Priority numbers of the entries the list is limited to, or None
        when focus is off. The case open in the editor is included (when it is
        valid here) so picking another case tab shows its songs too.
        """
        if not self.focus_var.get():
            return None
        view = self._view()
        reps = {view.rep_of.get(e.id, e.id)
                for e in self._focus_cases(subject)}
        selected = (view.rep_of.get(self._selected_case_id)
                    if self._selected_case_id else None)
        if selected in plan.valid_ids:
            reps.add(selected)
        return {view.positions[r] for r in reps if r in view.positions}

    def _sync_editor_case(self) -> None:
        """Open the editor on the case matching the simulated conditions.
        Only when a subject is pinned (that is when the editor exists) and
        only on a change of conditions / subject, never on a plain pack edit,
        so the tab does not jump while the user is editing it.
        """
        panel = self.editor_panel
        subject = self._pinned
        if panel is None or not subject or not self.focus_var.get():
            return
        cases = self._focus_cases(subject)
        if cases:
            panel.show_case_for([c.id for c in cases])

    def _on_focus_toggled(self) -> None:
        self._sync_editor_case()
        self._refresh_panel()

    def _on_case_selected(self, entry_id: str) -> None:
        """Highlight the selected case in column 2 without changing the
        simulated conditions behind the user's back.
        """
        self._selected_case_id = entry_id
        self._refresh_panel()

    # ------------------------------------------------------------------
    # context changes (conditions or biome moved)
    # ------------------------------------------------------------------
    def _context_changed(self) -> None:
        self._sync_editor_case()
        if self._playlist_active and self._play_biome:
            view = self._view()
            plan = self._plan_for(self._play_biome)
            change = simulation.evaluate_transition(
                self._followed_valid, plan.valid_ids, view.entries)
            self._followed_valid = set(plan.valid_ids)
            # forceStartMusicOnValid waits until the music stops; an entry
            # that stopped being valid in the meantime can no longer fire.
            self._armed_start = ((self._armed_start & plan.valid_ids)
                                 | set(change.armed_start))
            culprit = change.stop_entry
            if culprit is not None:
                number = view.positions.get(culprit.id, "?")
                forced = simulation.choose_force_start(
                    self._armed_start, plan.valid_ids, view.entries)
                if forced is not None:
                    first = plan.first_item_of(forced.id)
                    self._armed_start.discard(forced.id)
                    note = (f"Entry #{number} has a forceStop rule for this change and "
                            f"entry #{view.positions.get(forced.id, '?')} has "
                            "forceStartMusicOnValid: starting it immediately.")
                else:
                    first = plan.first_playable()
                    note = (f"Entry #{number} has a forceStop rule for this change: "
                            "switching songs immediately.")
                if first is None:
                    self._stop_playlist(
                        f"Entry #{number} forced a stop and nothing else can play.")
                    return
                self.app.set_status(note)
                if not self._play_item(plan, first):
                    self._stop_playlist("No playable audio file was found.")
                    return
        self._refresh_panel()
        self._redraw_chart()

    # ------------------------------------------------------------------
    # playback
    # ------------------------------------------------------------------
    def _on_player_state(self, state, _path) -> None:
        # Fired by the shared player. A STOPPED notification we didn't cause
        # (Stop button of the song list, the audio editor...) ends our playlist.
        if self._playlist_active and not self._self_call \
                and state == audio_preview.STOPPED:
            self._external_stop = True

    def _volume(self) -> float:
        return float(self.app.settings.get("preview_volume", 1.0))

    def _play_item(self, plan: simulation.Plan, index: int,
                   skip_missing: bool = True) -> bool:
        """Play plan.items[index]; with skip_missing, move on to the next
        song when its audio file can't be found. False if nothing played.
        """
        tries = 0
        while tries < max(1, len(plan.items)):
            item = plan.items[index]
            path = self._song_path(item.song)
            if path:
                self._self_call = True
                try:
                    self.player.play(path, volume=self._volume())
                except audio_preview.PreviewError as exc:
                    messagebox.showerror("Preview failed", str(exc))
                    return False
                finally:
                    self._self_call = False
                self._now_song = item.song
                self._now_path = path
                self._external_stop = False
                self.app.set_status(
                    f"Simulator: playing {item.song} (entry #{item.entry_index})")
                return True
            if not skip_missing:
                self.app.set_status(
                    f"Audio file for '{item.song}' was not found in the loaded "
                    "music folder.")
                return False
            nxt = plan.next_playable(index)
            if nxt is None or nxt == index:
                break
            index = nxt
            tries += 1
        return False

    def _start_playlist(self, index: Optional[int] = None) -> None:
        biome = self._displayed_biome()
        if biome is None:
            messagebox.showinfo(
                "Biome Simulator", "Hover or click a biome on the map first.")
            return
        if not self.player.available():
            messagebox.showerror(
                "Preview unavailable",
                "Install the preview dependency with: pip install pygame")
            return
        if not getattr(self.app, "music_source_folder", None):
            messagebox.showinfo(
                "Biome Simulator",
                "Load your music folder first (Music & Conditions → Load Music "
                "Folder…) so the simulator can find the audio files.")
            return
        plan = self._plan_for(biome)
        if index is None:
            index = plan.first_playable()
        if index is None:
            self.app.set_status(
                "No song can play in this biome with these conditions.")
            return
        if not self._play_item(plan, index, skip_missing=(index == plan.first_playable())):
            self.app.set_status(
                "Could not start: no audio file found for this list.")
            return
        self._playlist_active = True
        self._play_biome = biome
        self._followed_valid = set(plan.valid_ids)
        self._armed_start = set()
        self._schedule_tick()
        self._refresh_panel()
        self._redraw_chart()

    def _stop_playlist(self, message: Optional[str] = None,
                       stop_audio: bool = True) -> None:
        self._playlist_active = False
        if self._tick_job is not None:
            try:
                self.after_cancel(self._tick_job)
            except tk.TclError:
                pass
            self._tick_job = None
        if stop_audio and self._now_path and self.player.is_current(self._now_path):
            self._self_call = True
            try:
                self.player.stop()
            finally:
                self._self_call = False
        self._now_song = None
        self._now_path = None
        self._play_biome = None
        self._followed_valid = set()
        self._armed_start = set()
        self._external_stop = False
        self._refresh_panel()
        self._redraw_chart()
        if message:
            self.app.set_status(message)

    def _advance(self) -> None:
        """Pick the next song, imitating the mod (see Plan.next_playable)."""
        plan = self._plan_for(self._play_biome) if self._play_biome else None
        if plan is None:
            self._stop_playlist()
            return
        current = plan.find_song(self._now_song)
        nxt = plan.next_playable(current)
        # The music stopped (naturally, or via Next): an armed
        # forceStartMusicOnValid entry that is still valid plays first.
        forced = simulation.choose_force_start(
            self._armed_start, plan.valid_ids, self._view().entries)
        if forced is not None:
            index = plan.first_item_of(forced.id)
            self._armed_start.discard(forced.id)
            if index is not None:
                nxt = index
                self.app.set_status(
                    f"Entry #{self._view().positions.get(forced.id, '?')} "
                    "(forceStartMusicOnValid) starts now that the music stopped.")
        if nxt is None:
            self._stop_playlist(
                "Playlist ended: no song can play for the current conditions.")
            return
        if not self._play_item(plan, nxt):
            self._stop_playlist(
                "Playlist stopped: no audio file could be played.")
            return
        self._followed_valid = set(plan.valid_ids)
        self._refresh_panel()

    def _schedule_tick(self) -> None:
        if self._tick_job is None:
            self._tick_job = self.after(self._POLL_MS, self._tick)

    def _tick(self) -> None:
        self._tick_job = None
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if not self._playlist_active:
            return
        if self._external_stop:
            self._stop_playlist("Playlist stopped.", stop_audio=False)
            return

        path = self._now_path
        playing = self.player.is_playing()      # also notices natural end
        paused = self.player.is_paused()
        current = bool(path) and self.player.is_current(path)
        if current and (playing or paused):
            self._animate(paused)
        elif self.player.path is not None and not current:
            self._stop_playlist(
                "Another preview took over the audio channel; playlist stopped.",
                stop_audio=False)
            return
        else:
            self._advance()
            if not self._playlist_active:
                return
        self._schedule_tick()

    def _animate(self, paused: bool) -> None:
        self._update_transport()
        if not self._play_biome:
            return
        idx = self._plan_for(self._play_biome).find_song(self._now_song)
        if idx is None or not self.tree.exists(str(idx)):
            return
        self._wave_step = (self._wave_step + 1) % len(self._WAVE_FRAMES)
        self.tree.set(str(idx), "wave",
                      "⏸" if paused else self._WAVE_FRAMES[self._wave_step])

    # ------------------------------------------------------------------
    # transport buttons / list interaction
    # ------------------------------------------------------------------
    def _on_play_clicked(self) -> None:
        if not self._playlist_active:
            self._start_playlist()
            return
        if self._now_path and self.player.is_current(self._now_path):
            if self.player.is_playing():
                self.player.pause()
            elif self.player.is_paused():
                self.player.resume()
        self._refresh_panel()

    def _on_next_clicked(self) -> None:
        if self._playlist_active:
            self._advance()
        else:
            self._start_playlist()

    def _on_tree_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        biome = self._displayed_biome()
        if not iid or biome is None:
            return
        plan = self._plan_for(biome)
        index = int(iid)
        item = plan.items[index]
        if (self._playlist_active and item.song == self._now_song
                and self._now_path and self.player.is_current(self._now_path)):
            self._on_play_clicked()          # double-click the playing song: pause/resume
            return
        if self._playlist_active:
            if self._play_item(plan, index, skip_missing=False):
                self._refresh_panel()
            return
        self._start_playlist(index)
