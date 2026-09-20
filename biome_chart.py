"""
biome_chart.py
---------------
The "Biome Map" widget shown at the top of the condition editor: a chart
of every known biome placed at its normalized temperature (x) / humidity
(y) coordinate, where each biome can be switched on or off with a click.

WHAT YOU SEE
------------
* Every biome is a solid-colour icon (the same colour its name gets in the
  biome lists -- see biome_customization.default_color / app.biome_custom_*).
* Hovering an icon shows the biome's name and coordinates.
* Clicking an icon toggles it. An enabled biome is drawn as a check mark
  (✔) in its own colour instead of its shape.
* A small grip in the bottom-right corner lets you drag the chart taller
  or shorter. The chosen height is remembered for the rest of the session
  (the chart is rebuilt each time you switch entries).

BACKGROUND
----------
The plot area is painted with a bilinear gradient between four corner colours
(BACKDROP_CORNERS, keyed by (temperature, humidity) in [0, 1]) so the chart
reads as "cold/dry -> hot/wet" even before any icon is looked at. When the
owner passes `backdrop()` -> {"night": 0..1, "underwater": bool,
"weather": "RAIN"|"STORM"|"SNOW"|None} the simulated situation is layered on
top: a dark-blue night tint, a wavy water tint over the lower half, and a
large colourless weather emoji at low opacity.

tk.Canvas has neither gradients nor alpha, so the backdrop is rendered to an
image (numpy + Pillow) by render_backdrop() and cached by chart size and
state; hovering never re-renders it. Without Pillow the chart silently falls
back to the flat plot colour.

ICON SHAPE
----------
Each icon is a closed curve in polar form:

        r(θ) = k · (1 + E · sin(f · θ))

  E = -0.45 · erosion + 0.55                       (lobe depth)
  f = round(4 · clamp(weirdness, -1, 1) + 4)       (lobe count, 0..8)

k is the base radius (16 px at the reference chart size, scaled down for
smaller charts). The curve never goes negative because erosion is clamped
to [-1, 1], which keeps E in [0.1, 1.0].

DATA
----
The widget knows nothing about files. It is handed callables:

  biomes()    -> {name: {"temperature", "humidity", "erosion", "weirdness"}}
                 (values in [-1, 1]; stored next to the biome colours, see
                 biome_customization.all_attributes)
  color_of(n) -> "#rrggbb"
  active()    -> set of *normalized* names (see normalize_name) that are on
  on_toggle(n)

so the condition editor stays the single owner of the entry's state.

OVERLAPPING BIOMES
------------------
Several vanilla biomes share exactly the same coordinates (e.g. eleven of
them sit at 0.50 / 0.50). Drawn literally they would be stacked on one
pixel and all but one would be unclickable, so biomes with identical
coordinates are fanned out on a small spiral around the true point.
Biomes that merely lie close together are left where they are; the hit
test always picks the icon whose centre is nearest to the mouse.
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set

import customtkinter as ctk

try:  # Pillow ships with customtkinter; guard anyway so the chart never dies
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageTk
except Exception:  # noqa: BLE001
    np = Image = ImageDraw = ImageFont = ImageTk = None  # type: ignore[assignment]

#: Base radius of an icon at the reference plot size (dataset default).
BASE_ICON_RADIUS = 16.0
#: Plot side length (px) at which k reaches BASE_ICON_RADIUS.
REFERENCE_PLOT = 600.0

_SHAPE_STEPS = 144
_GOLDEN_ANGLE = 2.399963229728653
_GRID_STEPS = (0.0, 0.25, 0.5, 0.75, 1.0)

_PAD_LEFT = 58
_PAD_RIGHT = 14
_PAD_TOP = 12
_PAD_BOTTOM = 46

#: Default canvas height (px), used when the user hasn't resized yet.
_DEFAULT_HEIGHT = 460
#: Height the user last dragged the chart to, remembered at module level
#: so that switching entries (which rebuilds the chart) doesn't reset it.
_RESIZED_HEIGHT: Optional[int] = None
#: Size (px) of the square bottom-right resize grip.
_GRIP_SIZE = 18
#: Smallest canvas height the grip will let the user shrink to.
_MIN_HEIGHT = 160

#: Gradient corners, keyed (temperature, humidity), each 0 = low, 1 = high.
BACKDROP_CORNERS = {
    (0, 0): "#565d5e",
    (0, 1): "#3c4f52",
    (1, 0): "#52433c",
    (1, 1): "#4f4633",
}
#: Grid lines on top of the gradient (the theme's own grid colour is tuned
#: for the flat plot colour and would be too harsh/dark here).
_BACKDROP_GRID = "#6a7274"

_NIGHT_TINT, _NIGHT_ALPHA = (10, 24, 70), 0.32     # sunrise/sunset use half
_WATER_TINT, _WATER_ALPHA = (47, 111, 208), 0.22
_WATER_FEATHER = 0.012                              # soft edge, fraction of height
_WEATHER_EMOJI = {"RAIN": "\U0001F327", "STORM": "\u26C8", "SNOW": "\u2744"}
_WEATHER_ALPHA = 0.16
_WEATHER_POS = (0.5, 0.2)      # centre, as fractions of the plot (y from top)
_WEATHER_SIZE = 0.42           # fraction of the plot's shorter side
_EMOJI_FONTS = ("seguiemj.ttf", "NotoColorEmoji.ttf", "NotoEmoji-Regular.ttf",
                "/System/Library/Fonts/Apple Color Emoji.ttc", "DejaVuSans.ttf")


# ---------------------------------------------------------------------------
# Pure helpers (no tkinter -- easy to test)
# ---------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_name(name: str) -> str:
    """Canonical form used to compare a condition value with a chart biome
    ('Minecraft:Plains ' and 'plains' are the same biome).
    """
    text = str(name).strip().lower()
    if text.startswith("minecraft:"):
        text = text[len("minecraft:"):]
    return text


def erosion_to_e(erosion: float) -> float:
    """E = -0.45 * erosion + 0.55"""
    return -0.45 * _clamp(float(erosion), -1.0, 1.0) + 0.55


def weirdness_to_freq(weirdness: float) -> int:
    """f = round(4 * clamp(weirdness, -1, 1) + 4), rounding half up."""
    return int(math.floor(4.0 * _clamp(float(weirdness), -1.0, 1.0) + 4.0 + 0.5))


def radius_at(theta: float, e: float, freq: int) -> float:
    """r/k for the icon curve at angle `theta`."""
    return 1.0 + e * math.sin(freq * theta)


_shape_cache: Dict[tuple, List[float]] = {}


def unit_shape(e: float, freq: int) -> List[float]:
    """Flat [x0, y0, x1, y1, ...] outline for k = 1, centred on the origin,
    already in canvas orientation (y grows downwards).
    """
    key = (round(e, 4), freq)
    cached = _shape_cache.get(key)
    if cached is not None:
        return cached
    points: List[float] = []
    for i in range(_SHAPE_STEPS):
        theta = 2.0 * math.pi * i / _SHAPE_STEPS
        r = radius_at(theta, e, freq)
        points.append(r * math.cos(theta))
        points.append(-r * math.sin(theta))
    _shape_cache[key] = points
    return points


def to_norm(value: float) -> float:
    """Map a [-1, 1] dataset value to the chart's [0, 1] axis."""
    return (_clamp(float(value), -1.0, 1.0) + 1.0) / 2.0


def _hex_rgb(color: str) -> tuple:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _emoji_mask(char: str, target: int):
    """The glyph as an 'L' mask (shape only, so it comes out colourless), or
    None if no installed font can draw it. Bitmap emoji fonts only exist at
    one size, so 109 px is tried too and the result scaled down.
    """
    for name in _EMOJI_FONTS:
        for px in (target, 109):
            try:
                font = ImageFont.truetype(name, px)
                left, top, right, bottom = font.getbbox(char)
                w, h = right - left, bottom - top
                if w <= 0 or h <= 0:
                    continue
                mask = Image.new("L", (w, h), 0)
                ImageDraw.Draw(mask).text((-left, -top), char, font=font, fill=255)
            except Exception:  # noqa: BLE001 - missing font / unsupported glyph
                continue
            if mask.getbbox() is None:
                continue
            scale = target / max(w, h)
            return mask.resize((max(1, round(w * scale)), max(1, round(h * scale))),
                               Image.LANCZOS)
    return None


def render_backdrop(width: int, height: int, inner: tuple, night: float = 0.0,
                    underwater: bool = False, weather: Optional[str] = None):
    """Render the plot background. `inner` = (x, y, w, h) of the data area in
    plot-local pixels, so the gradient corners line up with the 0/1 grid
    lines. Returns (RGB image, text_fallback) where text_fallback is None or
    (char, cx, cy, size_px, colour) for the caller to draw as canvas text when
    no font could render the emoji as a mask.
    """
    ix, iy, iw, ih = inner
    xs = np.arange(width, dtype="float32")
    ys = np.arange(height, dtype="float32")
    u = np.clip((xs - ix) / max(iw, 1.0), 0.0, 1.0)[None, :]         # temperature
    v = np.clip(1.0 - (ys - iy) / max(ih, 1.0), 0.0, 1.0)[:, None]   # humidity
    c = {k: np.array(_hex_rgb(col), dtype="float32")
         for k, col in BACKDROP_CORNERS.items()}
    img = (((1 - u) * (1 - v))[..., None] * c[(0, 0)]
           + ((1 - u) * v)[..., None] * c[(0, 1)]
           + (u * (1 - v))[..., None] * c[(1, 0)]
           + (u * v)[..., None] * c[(1, 1)])

    if night > 0:
        a = _NIGHT_ALPHA * night
        img = img * (1 - a) + np.array(_NIGHT_TINT, dtype="float32") * a

    if underwater:
        # Water surface: y = 0.5 + 0.16 sin(2 pi x), y measured from the top.
        surface = 0.5 + 0.16 * np.sin(2 * np.pi * xs / max(width - 1, 1))
        depth = (ys + 0.5)[:, None] / height - surface[None, :]
        cover = (np.clip(depth / _WATER_FEATHER + 0.5, 0.0, 1.0)
                 * _WATER_ALPHA)[..., None]
        img = img * (1 - cover) + np.array(_WATER_TINT, dtype="float32") * cover

    base = Image.fromarray(np.clip(img, 0, 255).astype("uint8"), "RGB")

    fallback = None
    char = _WEATHER_EMOJI.get(weather or "")
    if char:
        size = max(24, int(_WEATHER_SIZE * min(width, height)))
        cx, cy = int(_WEATHER_POS[0] * width), int(_WEATHER_POS[1] * height)
        mask = _emoji_mask(char, size)
        if mask is not None:
            layer = Image.new("L", (width, height), 0)
            layer.paste(mask, (cx - mask.width // 2, cy - mask.height // 2))
            layer = layer.point(lambda p: int(p * _WEATHER_ALPHA))
            base.paste((255, 255, 255), (0, 0, width, height), layer)
        else:
            r, g, b = base.getpixel((min(cx, width - 1), min(cy, height - 1)))
            mix = lambda ch: int(ch + (255 - ch) * _WEATHER_ALPHA)  # noqa: E731
            fallback = (char, cx, cy, size, "#%02x%02x%02x" % (mix(r), mix(g), mix(b)))
    return base, fallback


def _palette(dark: bool) -> dict:
    if dark:
        return {
            "canvas": "#1C1C1C", "plot": "#232323", "frame": "#3A3A3A",
            "grid": "#2E2E2E", "text": "#9AA0A6", "outline": "#1C1C1C",
            "hover": "#F2F2F2", "tip_bg": "#0F0F0F", "tip_fg": "#F2F2F2",
            "tip_sub": "#B0B6BC", "tip_border": "#5A5A5A",
        }
    return {
        "canvas": "#FAFAFA", "plot": "#FFFFFF", "frame": "#CCCCCC",
        "grid": "#E6E6E6", "text": "#666666", "outline": "#FAFAFA",
        "hover": "#1A1A1A", "tip_bg": "#2B2B2B", "tip_fg": "#FFFFFF",
        "tip_sub": "#C8C8C8", "tip_border": "#1A1A1A",
    }


@dataclass
class _Icon:
    name: str
    key: str
    color: str
    cx: float
    cy: float
    e: float
    freq: int
    temperature: float
    humidity: float
    active: bool


# ---------------------------------------------------------------------------
# The widget
# ---------------------------------------------------------------------------
class BiomeChart(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        *,
        biomes: Callable[[], Dict[str, dict]],
        color_of: Callable[[str], str],
        active: Callable[[], Set[str]],
        on_toggle: Callable[[str], None],
        dark: bool = True,
        height: int = _DEFAULT_HEIGHT,
        on_hover: Optional[Callable[[Optional[str]], None]] = None,
        tooltip_lines: Optional[Callable[[str], List[str]]] = None,
        action_labels: tuple = ("click to enable", "click to disable"),
        on_right_click: Optional[Callable[[str], None]] = None,
        backdrop: Optional[Callable[[], dict]] = None,
    ):
        super().__init__(parent, fg_color="transparent")
        self._biomes = biomes
        self._color_of = color_of
        self._active = active
        self._on_toggle = on_toggle
        # Optional hooks used by the Biome Simulator tab:
        #   on_hover(name | None)   -- fired when the biome under the pointer changes
        #   tooltip_lines(name)     -- extra tooltip lines shown under the coordinates
        #   action_labels           -- (text when off, text when on) for the last line
        #   on_right_click(name)    -- fired on a right-click over a biome icon;
        #                              used by the Biome Simulator to open the
        #                              per-biome song/case editor without
        #                              disturbing the left-click pin behaviour
        self._on_hover = on_hover
        self._tooltip_lines = tooltip_lines
        self._action_labels = action_labels
        self._on_right_click = on_right_click
        self._reported_hover: Optional[str] = None
        self.pal = _palette(dark)

        self._icons: List[_Icon] = []
        self._k = BASE_ICON_RADIUS
        self._mouse: Optional[tuple] = None
        self._hover_key: Optional[str] = None
        self._last_size = (0, 0)
        # backdrop() -> {"night", "underwater", "weather"}; see module docstring.
        self._backdrop_state = backdrop
        self._backdrop_photo = None   # keep a reference or Tk drops the image
        self._backdrop_key = None
        self._backdrop_fallback = None

        # Resize-grip state.
        self._resizing = False
        self._resize_start_y_root = 0
        self._resize_start_height = 0

        # Reuse the height the user last dragged to, if any -- the chart is
        # rebuilt every time the selected entry changes, so without this a
        # resize would be lost on every selection.
        init_height = _RESIZED_HEIGHT if _RESIZED_HEIGHT is not None else height

        self.canvas = tk.Canvas(
            self, height=init_height, bg=self.pal["canvas"],
            highlightthickness=0, bd=0, cursor="arrow")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-3>", self._on_right_click_event)

    # -- public helpers ---------------------------------------------------
    def set_dark(self, dark: bool) -> None:
        """Switch palette (the chart is long-lived in the simulator tab)."""
        self.pal = _palette(dark)
        self.canvas.configure(bg=self.pal["canvas"])
        self.redraw()

    def _report_hover(self, name: Optional[str]) -> None:
        if name == self._reported_hover:
            return
        self._reported_hover = name
        if self._on_hover is not None:
            self._on_hover(name)

    # -- geometry ---------------------------------------------------------
    def _plot_rect(self):
        width = int(self.canvas.winfo_width())
        height = int(self.canvas.winfo_height())
        left, top = _PAD_LEFT, _PAD_TOP
        right, bottom = width - _PAD_RIGHT, height - _PAD_BOTTOM
        if right - left < 80 or bottom - top < 80:
            return None
        return left, top, right, bottom

    def _in_grip(self, x: int, y: int) -> bool:
        """Is (x, y) inside the bottom-right resize grip?"""
        try:
            cw = int(self.canvas.winfo_width())
            ch = int(self.canvas.winfo_height())
        except tk.TclError:
            return False
        if cw < 2 * _GRIP_SIZE or ch < 2 * _GRIP_SIZE:
            return False
        return (cw - x) <= _GRIP_SIZE and (ch - y) <= _GRIP_SIZE

    def _build_layout(self, rect) -> None:
        left, top, right, bottom = rect
        pw, ph = right - left, bottom - top
        k = _clamp(BASE_ICON_RADIUS * min(pw, ph) / REFERENCE_PLOT, 6.0,
                   BASE_ICON_RADIUS)
        self._k = k
        margin = 2.0 * k
        inner_w, inner_h = pw - 2 * margin, ph - 2 * margin
        active = self._active()

        data = self._biomes()

        # Base position of every biome, straight from its coordinates.
        base: Dict[str, tuple] = {}
        groups: Dict[tuple, List[str]] = {}
        for name, attrs in data.items():
            t_norm = to_norm(attrs["temperature"])
            h_norm = to_norm(attrs["humidity"])
            base[name] = (left + margin + t_norm * inner_w,
                          top + margin + (1.0 - h_norm) * inner_h)
            groups.setdefault((round(t_norm, 4), round(h_norm, 4)),
                              []).append(name)

        # Fan out biomes that share identical coordinates on a spiral, then
        # slide the whole fan back inside the plot if it ran over an edge.
        positions: Dict[str, tuple] = {}
        edge = 1.5 * k
        for names in groups.values():
            names.sort()
            pts = []
            for index, name in enumerate(names):
                bx, by = base[name]
                angle = index * _GOLDEN_ANGLE
                radius = 1.5 * k * math.sqrt(index)
                pts.append([bx + radius * math.cos(angle),
                            by + radius * math.sin(angle)])
            if len(pts) > 1:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                shift_x = max(0.0, left + edge - min(xs)
                              ) or min(0.0, right - edge - max(xs))
                shift_y = max(0.0, top + edge - min(ys)
                              ) or min(0.0, bottom - edge - max(ys))
                for p in pts:
                    p[0] += shift_x
                    p[1] += shift_y
            for name, p in zip(names, pts):
                positions[name] = (p[0], p[1])

        icons: List[_Icon] = []
        for name, attrs in data.items():
            key = normalize_name(name)
            cx, cy = positions[name]
            icons.append(_Icon(
                name=name, key=key, color=self._color_of(name),
                cx=cx, cy=cy,
                e=erosion_to_e(attrs["erosion"]),
                freq=weirdness_to_freq(attrs["weirdness"]),
                temperature=to_norm(attrs["temperature"]),
                humidity=to_norm(attrs["humidity"]),
                active=key in active,
            ))
        # Deeper lobes (bigger icons) first so small ones stay visible on top.
        icons.sort(key=lambda i: (-i.e, i.name))
        self._icons = icons
        self._margin = margin
        self._inner = (left + margin, top + margin, inner_w, inner_h)

    # -- drawing ----------------------------------------------------------
    def redraw(self) -> None:
        """Re-read biome data / colours / enabled state and repaint."""
        canvas = self.canvas
        rect = self._plot_rect()
        canvas.delete("all")
        if rect is None:
            return
        self._build_layout(rect)
        self._draw_frame(rect)
        # Enabled/selected icons last, so their check mark is never buried
        # under a neighbour (tags cluster tightly). sorted() is stable, so the
        # deeper-lobes-first order among the rest is kept.
        for icon in sorted(self._icons, key=lambda i: i.active):
            self._draw_icon(icon)
        self._draw_overlay()
        self._draw_grip()

    def _draw_frame(self, rect) -> None:
        canvas, pal = self.canvas, self.pal
        left, top, right, bottom = rect
        ix, iy, iw, ih = self._inner
        painted = self._draw_backdrop(rect)
        canvas.create_rectangle(left, top, right, bottom,
                                fill="" if painted else pal["plot"],
                                outline=pal["frame"])
        grid = _BACKDROP_GRID if painted else pal["grid"]
        small = ("", 10)
        for step in _GRID_STEPS:
            x = ix + step * iw
            y = iy + (1.0 - step) * ih
            canvas.create_line(x, top, x, bottom, fill=grid)
            canvas.create_line(left, y, right, y, fill=grid)
            canvas.create_text(x, bottom + 4, text=f"{step:.2f}", anchor="n",
                               fill=pal["text"], font=small)
            canvas.create_text(left - 6, y, text=f"{step:.2f}", anchor="e",
                               fill=pal["text"], font=small)
        canvas.create_text((left + right) / 2, bottom + 24,
                           text="Temperature  (cold → hot)", anchor="n",
                           fill=pal["text"], font=("", 11))
        canvas.create_text(14, (top + bottom) / 2,
                           text="Humidity  (dry → wet)", anchor="center",
                           angle=90, fill=pal["text"], font=("", 11))

    def _draw_backdrop(self, rect) -> bool:
        """Paint the gradient + situation tints. Returns False (flat plot
        colour used instead) when Pillow is missing or rendering fails.
        """
        if Image is None:
            return False
        left, top, right, bottom = rect
        width, height = int(right - left), int(bottom - top)
        state = self._backdrop_state() if self._backdrop_state else {}
        night = round(float(state.get("night", 0.0)), 3)
        underwater = bool(state.get("underwater", False))
        weather = state.get("weather")
        ix, iy, iw, ih = self._inner
        inner = (ix - left, iy - top, iw, ih)
        key = (width, height, tuple(round(n) for n in inner),
               night, underwater, weather)
        try:
            if key != self._backdrop_key:
                image, fallback = render_backdrop(
                    width, height, inner, night, underwater, weather)
                self._backdrop_photo = ImageTk.PhotoImage(image)
                self._backdrop_fallback = fallback
                self._backdrop_key = key
            self.canvas.create_image(left, top, image=self._backdrop_photo,
                                     anchor="nw")
        except Exception:  # noqa: BLE001 - a cosmetic layer must never break the map
            self._backdrop_key = None
            return False
        if self._backdrop_fallback:
            char, cx, cy, size, color = self._backdrop_fallback
            self.canvas.create_text(left + cx, top + cy, text=char, fill=color,
                                    font=("", -size))
        return True

    def _draw_icon(self, icon: _Icon) -> None:
        canvas, k = self.canvas, self._k
        if icon.active:
            s = k * 1.15
            points = [icon.cx - 0.80 * s, icon.cy + 0.05 * s,
                      icon.cx - 0.25 * s, icon.cy + 0.60 * s,
                      icon.cx + 0.85 * s, icon.cy - 0.65 * s]
            width = max(3.0, 0.45 * k)
            # A halo in the plot colour keeps the tick readable over neighbours.
            canvas.create_line(*points, fill=self.pal["plot"], width=width + 4,
                               capstyle="round", joinstyle="round")
            canvas.create_line(*points, fill=icon.color, width=width,
                               capstyle="round", joinstyle="round")
            return
        coords = [
            (icon.cx + k * v) if i % 2 == 0 else (icon.cy + k * v)
            for i, v in enumerate(unit_shape(icon.e, icon.freq))
        ]
        canvas.create_polygon(coords, fill=icon.color,
                              outline=self.pal["plot"], width=1)

    def _draw_overlay(self) -> None:
        """Hover ring + tooltip. Cheap enough to redo on every mouse move."""
        canvas = self.canvas
        canvas.delete("hover")
        canvas.delete("tip")
        if self._mouse is None:
            return
        icon = self._hit(*self._mouse)
        self._hover_key = icon.key if icon else None
        self._report_hover(icon.name if icon else None)
        try:
            canvas.configure(cursor="hand2" if icon else "arrow")
        except tk.TclError:
            pass
        if icon is None:
            return
        k = self._k
        if icon.active:
            canvas.create_oval(icon.cx - 1.15 * k, icon.cy - 1.15 * k,
                               icon.cx + 1.15 * k, icon.cy + 1.15 * k,
                               outline=icon.color, width=2, dash=(3, 3),
                               tags="hover")
        else:
            coords = [
                (icon.cx + k * v) if i % 2 == 0 else (icon.cy + k * v)
                for i, v in enumerate(unit_shape(icon.e, icon.freq))
            ]
            canvas.create_polygon(coords, fill="", outline=self.pal["hover"],
                                  width=2, tags="hover")
        self._draw_tip(icon, *self._mouse)

    def _draw_tip(self, icon: _Icon, x: float, y: float) -> None:
        canvas, pal = self.canvas, self.pal
        sub = (f"temperature {icon.temperature:.2f}  ·  "
               f"humidity {icon.humidity:.2f}")
        extra = list(self._tooltip_lines(icon.name)
                     ) if self._tooltip_lines else []
        action = self._action_labels[1 if icon.active else 0]
        t1 = canvas.create_text(0, 0, text=icon.name, anchor="nw",
                                fill=pal["tip_fg"], font=("", 11, "bold"),
                                tags="tip")
        t2 = canvas.create_text(0, 0, text="\n".join([sub, *extra, action]), anchor="nw",
                                fill=pal["tip_sub"], font=("", 10), tags="tip")
        b1, b2 = canvas.bbox(t1), canvas.bbox(t2)
        w = max(b1[2] - b1[0], b2[2] - b2[0]) + 16
        h1, h2 = b1[3] - b1[1], b2[3] - b2[1]
        h = h1 + h2 + 12
        cw, ch = int(canvas.winfo_width()), int(canvas.winfo_height())
        px, py = x + 14, y + 16
        if px + w > cw - 4:
            px = x - w - 10
        if py + h > ch - 4:
            py = y - h - 10
        px, py = max(4, px), max(4, py)
        canvas.coords(t1, px + 8, py + 5)
        canvas.coords(t2, px + 8, py + 5 + h1)
        box = canvas.create_rectangle(px, py, px + w, py + h, fill=pal["tip_bg"],
                                      outline=pal["tip_border"], tags="tip")
        canvas.tag_lower(box, t1)

    def _draw_grip(self) -> None:
        """Draw the bottom-right resize grip (three short diagonals).

        Drawn on every redraw so it survives theme toggles and resizes.
        Uses its own tag ('grip') so the hover/tooltip redraws -- which
        only delete 'hover' and 'tip' -- never wipe it.
        """
        canvas = self.canvas
        canvas.delete("grip")
        try:
            cw = int(canvas.winfo_width())
            ch = int(canvas.winfo_height())
        except tk.TclError:
            return
        if cw < 2 * _GRIP_SIZE or ch < 2 * _GRIP_SIZE:
            return
        color = self.pal["text"]
        for offset in (6, 11, 16):
            canvas.create_line(
                cw - offset, ch - 4, cw - 4, ch - offset,
                fill=color, width=1, tags="grip")

    # -- hit testing ------------------------------------------------------
    def _hit(self, x: float, y: float) -> Optional[_Icon]:
        """Icon under the pointer, nearest centre wins. The test uses the
        icon's own polar curve, so it matches what is drawn exactly.
        """
        k = self._k
        best, best_d = None, float("inf")
        for icon in self._icons:
            dx, dy = x - icon.cx, y - icon.cy
            d = math.hypot(dx, dy)
            if icon.active:
                inside = d <= 0.95 * k
            else:
                if d > k * (1.0 + icon.e):
                    continue
                reach = k * radius_at(math.atan2(-dy, dx), icon.e, icon.freq)
                inside = d <= max(reach, 0.55 * k)
            if inside and d < best_d:
                best, best_d = icon, d
        return best

    # -- events -----------------------------------------------------------
    def _on_configure(self, _event=None) -> None:
        size = (self.canvas.winfo_width(), self.canvas.winfo_height())
        if size == self._last_size:
            return
        self._last_size = size
        self.redraw()

    def _on_motion(self, event) -> None:
        # While a resize drag is in progress the <B1-Motion> handler owns
        # the pointer; ignore plain motion so we don't redraw the tooltip.
        if self._resizing:
            return
        if self._in_grip(event.x, event.y):
            # Hovering the grip: no tooltip, show the resize cursor.
            self._mouse = None
            self._hover_key = None
            self._report_hover(None)
            self.canvas.delete("hover")
            self.canvas.delete("tip")
            try:
                self.canvas.configure(cursor="sizing")
            except tk.TclError:
                pass
            return
        self._mouse = (event.x, event.y)
        self._draw_overlay()

    def _on_leave(self, _event=None) -> None:
        if self._resizing:
            return
        self._mouse = None
        self._hover_key = None
        self._report_hover(None)
        self.canvas.delete("hover")
        self.canvas.delete("tip")
        try:
            self.canvas.configure(cursor="arrow")
        except tk.TclError:
            pass

    def _on_click(self, event) -> None:
        if self._in_grip(event.x, event.y):
            # Begin a resize drag. event.y_root is the pointer's absolute
            # screen y, so the delta we compute below is independent of
            # any repacking the canvas causes as its height changes.
            self._resizing = True
            self._resize_start_y_root = event.y_root
            try:
                self._resize_start_height = int(self.canvas.winfo_height())
            except tk.TclError:
                self._resize_start_height = _DEFAULT_HEIGHT
            # Clear any lingering tooltip / hover ring.
            self._mouse = None
            self._hover_key = None
            self.canvas.delete("hover")
            self.canvas.delete("tip")
            return

        icon = self._hit(event.x, event.y)
        if icon is None:
            return
        self._mouse = (event.x, event.y)
        self._on_toggle(icon.name)
        self.redraw()

    def _on_right_click_event(self, event) -> None:
        """Right-click a biome icon: hand off to on_right_click(name)
        instead of toggling it. Ignored entirely when the chart wasn't
        given a handler, and never fires from the resize grip.
        """
        if self._on_right_click is None or self._in_grip(event.x, event.y):
            return
        icon = self._hit(event.x, event.y)
        if icon is None:
            return
        self._on_right_click(icon.name)

    def _on_drag(self, event) -> None:
        if not self._resizing:
            return
        dy = event.y_root - self._resize_start_y_root
        new_height = max(_MIN_HEIGHT, self._resize_start_height + dy)
        try:
            self.canvas.configure(height=new_height)
        except tk.TclError:
            pass

    def _on_release(self, event) -> None:
        if not self._resizing:
            return
        self._resizing = False
        # Remember the chosen height for the rest of the session.
        global _RESIZED_HEIGHT
        try:
            _RESIZED_HEIGHT = int(self.canvas.winfo_height())
        except tk.TclError:
            pass
        # Keep the resize cursor if the pointer is still over the grip
        # (the release doesn't necessarily move the mouse off it).
        try:
            still_on_grip = self._in_grip(event.x, event.y)
            self.canvas.configure(
                cursor="sizing" if still_on_grip else "arrow")
        except tk.TclError:
            pass
