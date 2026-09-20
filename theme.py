"""
theme.py
---------
The editor's visual identity, taken from the app logo (assets/SoundpackMaker512.png).

WHERE THE COLOURS COME FROM
---------------------------
The logo is a diagonal gradient from a bright blue (top-left) to a hot pink
(bottom-right) behind white "sound wave" bars and a pixel-art scroll drawn in a
very dark plum. Those are the only colours the UI needs:

  * BLUE  -> primary actions (buttons, slider progress). "Do something."
  * PINK  -> anything selected / active / checked (tabs, checkboxes, switches,
             slider knob, selected rows). "This is the current one."
  * PLUM  -> the darkest surfaces in dark mode and the text colour in light mode,
             so both modes read as the same brand. Every dark surface is a tint
             of the raven's plum instead of a neutral grey.

Blending BLUE -> PINK linearly in RGB lands on the logo's own mid-tone
(#855AAB), which is why gradient_image() needs no extra stops.

WHO USES WHAT
-------------
This module is the ONE place colours live; nothing here creates a widget except
build_header(). Different parts of the app consume it differently because
Tk is not one toolkit:

  * CustomTkinter widgets   -> install_ctk_theme() patches ctk.ThemeManager once,
                               before the first widget exists. Widgets that pass
                               no colour (most of them) follow it automatically.
  * Explicit CTk colours    -> the (light, dark) tuples and *_BUTTON dicts below.
  * ttk.Treeview            -> tree_colors(dark)  (ttk ignores CTk's theme).
  * raw tk.Listbox/Toplevel -> listbox_colors(dark), toplevel_bg(dark).
  * tk.Canvas widgets       -> chart_palette(dark), waveform_palette(dark).

Colour pairs are ``(light_mode, dark_mode)`` tuples, the same shape CustomTkinter
uses, so they can be passed straight to ``fg_color=`` / ``text_color=``.

This module imports no GUI library at import time (customtkinter / tkinter / PIL
are imported inside the functions that need them), so the palette can be unit
tested headless -- see test_theme.py.
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Brand colours (sampled from the logo)
# ---------------------------------------------------------------------------
BLUE = "#2196F3"    # logo gradient, top-left
PINK = "#E91E63"    # logo gradient, bottom-right
PLUM = "#260D34"    # the raven / scroll outline
SOFT_PINK = "#FF6B9D"   # the pink trim on the scroll; readable pink on dark surfaces

LOGO_FILENAME = "SoundpackMaker512.png"

# ---------------------------------------------------------------------------
# Surfaces (light, dark). CTkFrame nests automatically: a frame inside a frame
# of the default colour uses SURFACE_RAISED, so cards sit one step above their
# parent without any per-widget colour.
# ---------------------------------------------------------------------------
WINDOW = ("#E9E1F1", "#1A0E26")
SURFACE = ("#F7F3FB", "#251636")
SURFACE_RAISED = ("#ECE4F4", "#31204A")
FIELD = ("#FFFFFF", "#1D1029")          # entries, text boxes, combo boxes
BORDER = ("#C9B8DC", "#4A3266")

TEXT = (PLUM, "#F4ECFA")
MUTED = ("#6F5C87", "#B4A3C9")
ON_COLOR = "#FFFFFF"                   # text drawn on BLUE / PINK / danger fills

# ---------------------------------------------------------------------------
# Interactive colours (light, dark)
# ---------------------------------------------------------------------------
PRIMARY = ("#1976D2", "#1976D2")        # white text needs >= 4.5:1, so one blue for both modes
PRIMARY_HOVER = ("#1565C0", "#1565C0")

ACCENT = ("#D81B60", PINK)
ACCENT_HOVER = ("#B0134D", "#C2185B")
ACCENT_TEXT = ("#C2185B", SOFT_PINK)   # accent used as *text* colour

NEUTRAL = ("#DCCFEA", "#3D2A57")
NEUTRAL_HOVER = ("#CBB9DE", "#503775")

DANGER = ("#C62828", "#B3261E")
DANGER_HOVER = ("#A61E1E", "#8E1C16")

WARNING_TEXT = ("#b45309", "#E0A030")  # amber, kept apart from pink on purpose

TRACK = ("#CDBFE0", "#3D2A57")         # slider / progress / switch-off tracks
CONTROL_TRACK = ("#836E9F", "#3A2853")  # segmented-button track (white text on it)
CONTROL_TRACK_HOVER = ("#7A6499", "#4A3568")

# Ready-made button styles, so call sites say what a button *is*:
#     ctk.CTkButton(..., **theme.NEUTRAL_BUTTON, command=...)
# Neutral buttons carry their own text colour because CTk's default is white,
# which is unreadable on a pale light-mode fill.
NEUTRAL_BUTTON = {"fg_color": NEUTRAL, "hover_color": NEUTRAL_HOVER,
                  "text_color": TEXT}
DANGER_BUTTON = {"fg_color": DANGER, "hover_color": DANGER_HOVER}

# Case tabs / toggles: (fg, hover, text) triples, as biome_case_editor and
# LibraryTab already expect.
TAB_ON = (ACCENT, ACCENT_HOVER, ON_COLOR)
TAB_OFF = (NEUTRAL, NEUTRAL_HOVER, TEXT)
# The "some selected" state of a multi-edit toggle (amber = "mixed").
TAB_MIXED = (("#C08A2A", "#B47A20"), ("#9C6F1F", "#8A5C10"), ON_COLOR)
# Outline-only button ("+ Add case").
OUTLINE_TEXT = TEXT
OUTLINE_HOVER = NEUTRAL

# ttk.Treeview row-tag colours (simulator playlist). ttk tags take one string,
# not a pair, so the owner picks the right half with pick() and re-applies it
# when the theme flips (SimulatorTab._style_tree_tags).
TREE_PLAYING = ("#1565C0", "#42A5F5")
TREE_SELECTED_CASE = ACCENT_TEXT


# ---------------------------------------------------------------------------
# CustomTkinter theme
# ---------------------------------------------------------------------------
def install_ctk_theme() -> None:
    """Load CTk's built-in "blue" theme, then overwrite it with ours.

    Starting from a complete built-in theme (rather than building a dict from
    scratch) means a widget key we forgot still has a valid value. Must run
    before the first CTk widget -- including the root window -- is created,
    because widgets read ThemeManager.theme in their constructors.
    """
    import customtkinter as ctk

    ctk.set_default_color_theme("blue")
    theme = ctk.ThemeManager.theme

    def patch(widget: str, **values) -> None:
        theme[widget].update(values)

    patch("CTk", fg_color=WINDOW)
    patch("CTkToplevel", fg_color=WINDOW)
    patch("CTkFrame", corner_radius=10, fg_color=SURFACE,
          top_fg_color=SURFACE_RAISED, border_color=BORDER)
    patch("CTkScrollableFrame", label_fg_color=SURFACE_RAISED)
    patch("CTkLabel", text_color=TEXT)
    patch("CTkButton", corner_radius=8, fg_color=PRIMARY,
          hover_color=PRIMARY_HOVER, border_color=BORDER, text_color=ON_COLOR,
          text_color_disabled=("#E3D8EE", "#8E7BA6"))
    patch("CTkEntry", corner_radius=8, fg_color=FIELD, border_color=BORDER,
          text_color=TEXT, placeholder_text_color=MUTED)
    patch("CTkTextbox", corner_radius=8, fg_color=FIELD, border_color=BORDER,
          text_color=TEXT, scrollbar_button_color=CONTROL_TRACK,
          scrollbar_button_hover_color=CONTROL_TRACK_HOVER)
    patch("CTkCheckBox", fg_color=ACCENT, hover_color=ACCENT_HOVER,
          border_color=("#7B6893", "#8E7BA6"), checkmark_color=ON_COLOR,
          text_color=TEXT)
    patch("CTkRadioButton", fg_color=ACCENT, hover_color=ACCENT_HOVER,
          border_color=("#7B6893", "#8E7BA6"), text_color=TEXT)
    patch("CTkSwitch", fg_color=("#BBA9D1", "#4A3566"), progress_color=ACCENT,
          button_color=("#5A4574", "#F4ECFA"),
          button_hover_color=("#3E2C55", "#FFFFFF"), text_color=TEXT)
    patch("CTkSlider", fg_color=TRACK, progress_color=PRIMARY,
          button_color=ACCENT, button_hover_color=ACCENT_HOVER)
    patch("CTkProgressBar", fg_color=TRACK, progress_color=PRIMARY)
    patch("CTkComboBox", corner_radius=8, fg_color=FIELD, border_color=BORDER,
          button_color=("#BBA9D1", "#4A3566"),
          button_hover_color=("#A48CC0", "#5F4585"), text_color=TEXT)
    patch("CTkOptionMenu", fg_color=PRIMARY, button_color=PRIMARY_HOVER,
          button_hover_color=("#0D47A1", "#1565C0"))
    patch("CTkScrollbar", button_color=("#B6A5CC", "#4E3870"),
          button_hover_color=("#9A86B5", "#6A4C94"))
    patch("CTkSegmentedButton", corner_radius=8, fg_color=CONTROL_TRACK,
          selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
          unselected_color=CONTROL_TRACK,
          unselected_hover_color=CONTROL_TRACK_HOVER, text_color=ON_COLOR)
    patch("DropdownMenu", fg_color=SURFACE_RAISED, hover_color=NEUTRAL,
          text_color=TEXT)


# ---------------------------------------------------------------------------
# Colours for widgets CustomTkinter does not manage (single mode at a time)
# ---------------------------------------------------------------------------
def pick(pair, dark: bool) -> str:
    """The light or dark half of a (light, dark) colour pair."""
    return pair[1 if dark else 0]


def tree_colors(dark: bool) -> dict:
    """ttk.Treeview colours. ttk ignores CTk's theme, so the tree is painted
    from the same tokens instead."""
    return {
        "background": pick(SURFACE, dark),
        "field": pick(SURFACE, dark),
        "foreground": pick(TEXT, dark),
        "selected_bg": pick(ACCENT, dark),
        "selected_fg": ON_COLOR,
        "heading_bg": pick(SURFACE_RAISED, dark),
        "heading_fg": pick(TEXT, dark),
    }


def listbox_colors(dark: bool) -> dict:
    """Keyword arguments for a raw tk.Listbox."""
    return {
        "bg": pick(FIELD, dark),
        "fg": pick(TEXT, dark),
        "selectbackground": pick(ACCENT, dark),
        "selectforeground": ON_COLOR,
    }


def toplevel_bg(dark: bool) -> str:
    """Background for a plain tk.Toplevel (the small dialogs), so it matches the
    CTk frame that fills it."""
    return pick(WINDOW, dark)


def chart_palette(dark: bool) -> dict:
    """Colours for biome_chart's canvas. The plot area keeps the neutral
    "well" look; only its surroundings pick up the plum tint."""
    if dark:
        return {
            "canvas": "#1B0F28", "plot": "#221433", "frame": "#4A3266",
            "grid": "#2E1F44", "text": "#B4A3C9", "outline": "#1B0F28",
            "hover": "#F4ECFA", "tip_bg": "#12081B", "tip_fg": "#F4ECFA",
            "tip_sub": "#C7B8DA", "tip_border": "#6B4E8E",
        }
    return {
        "canvas": "#F7F3FB", "plot": "#FFFFFF", "frame": "#C9B8DC",
        "grid": "#E6DDF0", "text": "#6F5C87", "outline": "#F7F3FB",
        "hover": PLUM, "tip_bg": PLUM, "tip_fg": "#FFFFFF",
        "tip_sub": "#D6C9E6", "tip_border": PLUM,
    }


def waveform_palette(dark: bool) -> dict:
    """Colours for the audio editor's waveform canvas: blue signal, pink trim
    handles -- the same two ends of the logo gradient."""
    if dark:
        return {
            "canvas": "#1B0F28", "wave": "#42A5F5", "wave_edge": "#1E6FB8",
            "grid": "#2E1F44", "axis": "#4A3266", "dim": "#0E0616",
            "handle": SOFT_PINK, "playhead": "#F4ECFA", "text": "#B4A3C9",
        }
    return {
        "canvas": "#F7F3FB", "wave": "#1E88E5", "wave_edge": "#1565C0",
        "grid": "#E6DDF0", "axis": "#C9B8DC", "dim": "#FFFFFF",
        "handle": "#C2185B", "playhead": PLUM, "text": "#6F5C87",
    }


# ---------------------------------------------------------------------------
# Brand header: the logo's gradient, its icon and its sound-wave bars
# ---------------------------------------------------------------------------
# The large-window backdrop is a softened version of the logo gradient.  It is
# intentionally much closer to WINDOW than the header so the branding stays subtle.
BACKGROUND_START_LIGHT = "#DCEEFF"
BACKGROUND_END_LIGHT = "#F7DCE8"
BACKGROUND_START_DARK = "#241A32"
BACKGROUND_END_DARK = "#321A2B"
BACKGROUND_MIX = 0.72

HEADER_HEIGHT = 40
#: Heights (px) of the decorative "sound wave" bars at the header's right edge.
_WAVE_BARS = (10, 18, 28, 16, 24, 12, 20, 10)


def _hex_to_rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def mix(a: str, b: str, t: float) -> str:
    """Linear RGB blend of two "#rrggbb" colours (t=0 -> a, t=1 -> b)."""
    t = max(0.0, min(1.0, float(t)))
    return "#%02x%02x%02x" % tuple(
        round(x + (y - x) * t) for x, y in zip(_hex_to_rgb(a), _hex_to_rgb(b)))


def asset_path(name: str) -> str:
    """Path of a bundled asset, in a source checkout and a PyInstaller build
    (same lookup main.py uses for the window icon)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "assets", name)


def gradient_image(width: int, height: int, start: str = BLUE, end: str = PINK,
                   *, diagonal: bool = False):
    """Render a horizontal or upper-left -> lower-right gradient image."""
    from PIL import Image

    width, height = max(1, int(width)), max(1, int(height))
    if diagonal:
        vertical = Image.linear_gradient("L").resize((width, height))
        horizontal = Image.linear_gradient("L").rotate(90).resize((width, height))
        # Averaging the two ramps makes equal x/y movement follow the same colour
        # progression, giving a clean diagonal rather than a corner-to-edge fade.
        mask = Image.blend(vertical, horizontal, 0.5)
    else:
        mask = Image.linear_gradient("L").rotate(90).resize((width, height))
    return Image.composite(Image.new("RGB", (width, height), end),
                           Image.new("RGB", (width, height), start), mask)


def background_gradient_image(width: int, height: int, dark: bool):
    """Create the deliberately subtle diagonal backdrop for the main window."""
    window = pick(WINDOW, dark)
    blue = mix(BACKGROUND_START_DARK if dark else BACKGROUND_START_LIGHT,
               window, BACKGROUND_MIX)
    pink = mix(BACKGROUND_END_DARK if dark else BACKGROUND_END_LIGHT,
               window, BACKGROUND_MIX)
    return gradient_image(width, height, blue, pink, diagonal=True)


def build_background(parent, dark: bool = True):
    """Create the full-window gradient canvas used behind the CTk widgets."""
    import tkinter as tk

    canvas = tk.Canvas(parent, highlightthickness=0, bd=0,
                       bg=pick(WINDOW, dark))
    keep = {"bg": None}

    def redraw(_event=None) -> None:
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 2 or height < 2:
            return
        try:
            from PIL import ImageTk
            keep["bg"] = ImageTk.PhotoImage(
                background_gradient_image(width, height, dark))
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=keep["bg"])
        except Exception:  # noqa: BLE001 - branding must never stop startup
            canvas.configure(bg=pick(WINDOW, dark))

    canvas.bind("<Configure>", redraw)
    return canvas


def _logo_icon(size: int):
    """The logo, scaled to ``size`` px with rounded corners; None if the asset
    or Pillow is missing (the header then simply has no icon)."""
    path = asset_path(LOGO_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        from PIL import Image, ImageDraw, ImageTk

        icon = Image.open(path).convert("RGBA").resize((size, size), Image.LANCZOS)
        scale = 4   # draw the corner mask 4x larger, then shrink it: smooth edges
        mask = Image.new("L", (size * scale, size * scale), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, size * scale - 1, size * scale - 1),
            radius=int(size * scale * 0.22), fill=255)
        icon.putalpha(mask.resize((size, size), Image.LANCZOS))
        return ImageTk.PhotoImage(icon)
    except Exception:  # noqa: BLE001 - branding must never stop the app starting
        return None


def build_header(parent):
    """The slim gradient banner at the top of the window.

    A tk.Canvas redrawn on <Configure>: a gradient can't be a CTk fill colour,
    so it is rendered to an image at the current width (cheap: a resize of a
    256x256 ramp). Falls back to a solid BLUE bar if Pillow is unavailable.
    The caller packs it.
    """
    import tkinter as tk

    canvas = tk.Canvas(parent, height=HEADER_HEIGHT, highlightthickness=0,
                       bd=0, bg=BLUE)
    icon_size = HEADER_HEIGHT - 12
    keep = {"logo": _logo_icon(icon_size), "bg": None}

    def redraw(_event=None) -> None:
        width = int(canvas.winfo_width())
        if width < 2:
            return
        canvas.delete("all")
        try:
            from PIL import ImageTk
            keep["bg"] = ImageTk.PhotoImage(gradient_image(width, HEADER_HEIGHT))
            canvas.create_image(0, 0, anchor="nw", image=keep["bg"])
        except Exception:  # noqa: BLE001 - solid bar instead of a broken banner
            pass

        # Sound-wave bars: white pills tinted by the gradient underneath, like
        # the bars behind the logo's scroll.
        x = width - 18
        for height in _WAVE_BARS:
            tint = mix(mix(BLUE, PINK, x / width), "#FFFFFF", 0.72)
            canvas.create_line(x, (HEADER_HEIGHT - height) / 2,
                               x, (HEADER_HEIGHT + height) / 2,
                               width=5, fill=tint, capstyle="round")
            x -= 13

        left = 10
        if keep["logo"] is not None:
            canvas.create_image(left, (HEADER_HEIGHT - icon_size) // 2,
                                anchor="nw", image=keep["logo"])
            left += icon_size + 10
        # A 1px plum shadow keeps white text legible over the bright blue end.
        for dx, colour in ((1, PLUM), (0, "#FFFFFF")):
            title = canvas.create_text(
                left + dx, HEADER_HEIGHT / 2 + dx, anchor="w", fill=colour,
                text="Songpack Maker", font=("", 14, "bold"))
        box = canvas.bbox(title)
        canvas.create_text(
            box[2] + 10, HEADER_HEIGHT / 2 + 1, anchor="w", fill="#F6E3F0",
            text="for ReactiveMusic", font=("", 11))

    canvas.bind("<Configure>", redraw)
    return canvas