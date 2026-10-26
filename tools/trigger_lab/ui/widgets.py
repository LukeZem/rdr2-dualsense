"""Custom widgets: status chips, trigger chart, travel plot, waveform, ammo pips, zone editor."""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

import numpy as np

from ds5 import effects
from . import theme as T

KIND_COLOR = {"resist": T.ACCENT, "snap": T.BAD, "vibrate": T.BLUE, "other": T.MUTED}


def _shade(color: str, level: int, bg: str = T.PANEL2) -> str:
    if level <= 0:
        return bg
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    br, bgc, bb = (int(bg[i:i + 2], 16) for i in (1, 3, 5))
    k = 0.3 + 0.7 * level / 8
    return "#%02x%02x%02x" % (int(br + (r - br) * k), int(bgc + (g - bgc) * k), int(bb + (b - bb) * k))


class Chip(tk.Label):
    def __init__(self, master, text: str = "", color: str = T.MUTED) -> None:
        super().__init__(master, text=text, bg=T.PANEL2, fg=T.FG, font=T.SMALL, padx=T.px(10), pady=T.px(3))
        self.set(text, color)

    def set(self, text: str, color: str = T.MUTED) -> None:
        self.config(text=f"● {text}" if text else "", fg=color if color else T.FG)


class TriggerChart(tk.Canvas):
    """R2 force curve over the calibrated travel, the finger, the break and reset points."""

    def __init__(self, master, width: int = 660, height: int = 210) -> None:
        super().__init__(master, width=T.px(width), height=T.px(height), bg=T.PANEL, highlightthickness=0)
        self.w, self.h = width, height
        self.x0, self.x1 = 46, width - 54

    def _x(self, raw: float) -> float:
        return self.x0 + (self.x1 - self.x0) * raw / 255

    def draw(self, table: list[int], r2_block: bytes, r2: int, l2_block: bytes, l2: int, l2_table: list[int],
             markers: list[tuple[int, str, str]], labels: list[tuple[int, int, str]], game_rt: int) -> None:
        self.delete("all")
        real = self.winfo_width() / T.S
        if real > 300:
            self.w, self.x1 = real, real - 54
        top, bot = 26, 150
        kind, zones = effects.zone_view(r2_block)
        color = KIND_COLOR[kind]
        self.create_text(self.x0 - 8, top, text="force", fill=T.MUTED, font=T.SMALL, anchor="e")
        for i in range(0, 9, 2):
            y = bot - (bot - top) * i / 8
            self.create_line(self.x0, y, self.x1, y, fill=T.PANEL2)
        for z in range(10):
            xa, xb = self._x(table[z]), self._x(table[z + 1] if z < 9 else 255)
            hgt = (bot - top) * zones[z] / 8
            if zones[z]:
                self.create_rectangle(xa + 1, bot - hgt, xb - 1, bot, fill=_shade(color, zones[z], T.PANEL), outline="")
                self.create_text((xa + xb) / 2, bot - hgt - 8, text=str(zones[z]), fill=T.FG, font=T.SMALL)
            self.create_text((xa + xb) / 2, bot + 10, text=f"z{z}", fill=T.MUTED, font=("Segoe UI", 7))
        for z0, z1, text in labels:                     # take-up / wall / break annotations
            xa, xb = self._x(table[z0]), self._x(table[z1] if z1 < 10 else 255)
            self.create_line(xa + 2, top - 10, xb - 2, top - 10, fill=T.LINE, width=2)
            self.create_text((xa + xb) / 2, top - 18, text=text, fill=T.MUTED, font=("Segoe UI", 8))
        for raw, col, text in markers:
            x = self._x(raw)
            self.create_line(x, top - 4, x, bot, fill=col, dash=(4, 3), width=2)
            self.create_text(x + 3, bot - 6, text=text, fill=col, anchor="w", font=("Segoe UI", 8, "bold"))
        x = self._x(r2)
        self.create_line(x, top - 6, x, bot + 2, fill="white", width=3)
        self.create_polygon(x - 6, bot + 18, x + 6, bot + 18, x, bot + 8, fill="white")
        self.create_text(self.x1 + 8, (top + bot) / 2 - 10, text="R2", fill=T.FG, font=T.BOLD, anchor="w")
        self.create_text(self.x1 + 8, (top + bot) / 2 + 8, text=str(r2), fill=T.FG, font=T.MONO, anchor="w")
        # L2 strip
        y0, y1 = bot + 26, bot + 42
        lk, lz = effects.zone_view(l2_block)
        for z in range(10):
            xa, xb = self._x(l2_table[z]), self._x(l2_table[z + 1] if z < 9 else 255)
            self.create_rectangle(xa, y0, xb, y1, fill=_shade(KIND_COLOR[lk], lz[z], T.PANEL2), outline=T.PANEL)
        lx = self._x(l2)
        self.create_line(lx, y0 - 3, lx, y1 + 3, fill="white", width=2)
        self.create_text(self.x0 - 8, (y0 + y1) / 2, text="L2", fill=T.MUTED, font=T.SMALL, anchor="e")
        # what the game sees
        self.create_text(self.x1 + 8, y0 - 2, text="game", fill=T.MUTED, font=("Segoe UI", 8), anchor="w")
        self.create_rectangle(self.x1 + 8, y0 + 10, self.x1 + 48, y1 + 10, fill=T.BAD if game_rt else T.PANEL2,
                              outline="")
        self.create_text(self.x1 + 28, (y0 + y1) / 2 + 10, text=str(game_rt), fill="white", font=("Consolas", 8))
        self.scale("all", 0, 0, T.S, T.S)


class TravelPlot(tk.Canvas):
    def __init__(self, master, width: int = 660, height: int = 110, seconds: float = 3.0) -> None:
        super().__init__(master, width=T.px(width), height=T.px(height), bg=T.PANEL, highlightthickness=0)
        self.w, self.h, self.seconds = width, height, seconds

    def draw(self, history: list, shots: list[float], markers: list[tuple[int, str, str]]) -> None:
        self.delete("all")
        real = self.winfo_width() / T.S
        if real > 300:
            self.w = real
        x0, x1, top, bot = 46, self.w - 54, 8, self.h - 18
        self.create_rectangle(x0, top, x1, bot, outline=T.PANEL2)
        if not history:
            return
        t_end = history[-1][0]
        t0 = t_end - self.seconds

        def px(t):
            return x0 + (x1 - x0) * (t - t0) / self.seconds

        def py(v):
            return bot - (bot - top) * v / 255

        for raw, col, _ in markers:
            self.create_line(x0, py(raw), x1, py(raw), fill=col, dash=(4, 3))
        pts = [p for p in history if p[0] >= t0][::2]
        for idx, col, width in ((2, T.BLUE, 1), (3, T.LINE, 1), (1, T.ACCENT, 2)):
            coords = [c for p in pts for c in (px(p[0]), py(p[idx]))]
            if len(coords) >= 4:
                self.create_line(*coords, fill=col, width=width)
        for t in shots:
            if t >= t0:
                self.create_line(px(t), top, px(t), bot, fill=T.BAD, width=2)
        self.create_text(x0, bot + 9, anchor="w", fill=T.MUTED, font=("Segoe UI", 8),
                         text="last 3 s   amber R2 · blue L2 · grey = RT the game sees · red = shot")
        self.scale("all", 0, 0, T.S, T.S)


class Waveform(tk.Canvas):
    def __init__(self, master, width: int = 560, height: int = 140) -> None:
        super().__init__(master, width=T.px(width), height=T.px(height), bg=T.PANEL, highlightthickness=0)
        self.w, self.h = width, height

    def draw(self, audio: Optional[np.ndarray], rate: int, haptic: Optional[np.ndarray] = None,
             title: str = "") -> None:
        self.delete("all")
        mid = self.h / 2
        self.create_line(0, mid, self.w, mid, fill=T.PANEL2)
        if audio is not None and len(audio):
            mono = audio.mean(axis=1) if audio.ndim == 2 else audio
            self._env(mono, rate, T.BLUE, 0.48)
        if haptic is not None and len(haptic):
            self._env(haptic.max(axis=1), 48000, T.ACCENT, 0.3, dur_ref=len(audio) / rate if audio is not None else None)
        self.create_text(8, 10, text=title, fill=T.MUTED, anchor="w", font=T.SMALL)
        self.create_text(self.w - 8, 10, text="blue = game sound · amber = haptic", fill=T.MUTED, anchor="e",
                         font=("Segoe UI", 8))
        self.scale("all", 0, 0, T.S, T.S)

    def _env(self, x: np.ndarray, rate: int, color: str, scale: float, dur_ref: Optional[float] = None) -> None:
        dur = len(x) / rate
        span = max(dur, dur_ref or 0)
        cols = max(1, int(self.w * dur / span))
        hop = max(1, len(x) // cols)
        n = len(x) // hop
        if n == 0:
            return
        env = np.abs(x[: n * hop]).reshape(n, hop).max(axis=1)
        env = env / max(1e-6, env.max())
        mid = self.h / 2
        for i, v in enumerate(env):
            xx = i * self.w * (dur / span) / n
            self.create_line(xx, mid - v * self.h * scale, xx, mid + v * self.h * scale, fill=color)


class AmmoPips(tk.Canvas):
    def __init__(self, master, width: int = 300, height: int = 22) -> None:
        super().__init__(master, width=T.px(width), height=T.px(height), bg=T.BG, highlightthickness=0)
        self.w = width

    def draw(self, clip: Optional[int], size: Optional[int], infinite: bool) -> None:
        self.delete("all")
        real = self.winfo_width() / T.S
        if real > 100:
            self.w = real
        if size is None or infinite:
            self.create_text(2, 11, text="∞ ammo", fill=T.MUTED, anchor="w", font=T.SMALL)
            self.scale("all", 0, 0, T.S, T.S)
            return
        r = 6 if size <= 16 else 4
        gap = min(18, (self.w - 10) / max(1, size))
        for i in range(size):
            x = 8 + i * gap
            fill = T.ACCENT if clip is not None and i < clip else ""
            self.create_oval(x - r, 11 - r, x + r, 11 + r, outline=T.ACCENT, fill=fill)
        self.scale("all", 0, 0, T.S, T.S)


class Slider(tk.Canvas):
    """Themed horizontal slider: click or drag; shows its value. Mirrors tk.Scale's basics."""

    def __init__(self, master, from_: float = 0, to: float = 100, variable: tk.Variable | None = None,
                 command: Optional[Callable] = None, length: int = 240, resolution: float = 1,
                 bg: str = T.PANEL, showvalue: bool = True, **_ignored) -> None:
        self.lw, self.lh = length, 26
        super().__init__(master, width=T.px(length), height=T.px(self.lh), bg=bg, highlightthickness=0,
                         cursor="hand2")
        self.lo, self.hi, self.res = from_, to, resolution or 1
        self.var = variable or tk.DoubleVar(value=from_)
        self.command, self.showvalue = command, showvalue
        self.var.trace_add("write", lambda *_: self.redraw())
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.redraw()

    def _track(self) -> tuple[float, float]:
        return 10, self.lw - (46 if self.showvalue else 10)

    def _drag(self, ev) -> None:
        x0, x1 = self._track()
        f = min(1.0, max(0.0, (ev.x / T.S - x0) / (x1 - x0)))
        v = round((self.lo + f * (self.hi - self.lo)) / self.res) * self.res
        if isinstance(self.var, tk.IntVar):
            v = int(v)
        if v != self.var.get():
            self.var.set(v)
            if self.command:
                self.command(v)

    def redraw(self) -> None:
        self.delete("all")
        try:
            v = float(self.var.get())
        except (tk.TclError, ValueError):
            return
        x0, x1 = self._track()
        x = x0 + (v - self.lo) / max(1e-9, self.hi - self.lo) * (x1 - x0)
        y = self.lh / 2
        self.create_line(x0, y, x1, y, fill=T.PANEL2, width=T.px(6), capstyle="round")
        self.create_line(x0, y, x, y, fill=T.ACCENT, width=T.px(6), capstyle="round")
        self.create_oval(x - 7, y - 7, x + 7, y + 7, fill=T.FG, outline=T.ACCENT, width=T.px(2))
        if self.showvalue:
            self.create_text(self.lw - 4, y, text=f"{v:g}", fill=T.FG, anchor="e", font=T.MONO)
        self.scale("all", 0, 0, T.S, T.S)


class ZoneEditor(tk.Canvas):
    """Pull curve editor: 10 bars (force 0-8 per zone). Click or drag a bar to set it."""

    def __init__(self, master, on_change: Callable[[list[int]], None], bg: str = T.PANEL,
                 width: int = 300, height: int = 140) -> None:
        self.lw, self.lh = width, height
        super().__init__(master, width=T.px(width), height=T.px(height), bg=bg, highlightthickness=0,
                         cursor="hand2")
        self.values = [0] * 10
        self.marker: Optional[int] = None       # zone where the break is
        self._on_change = on_change
        self.enabled = True
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        self.redraw()

    def _geom(self):
        return 6, self.lw - 6, 12, self.lh - 20          # x0, x1, top, bottom

    def _drag(self, ev) -> None:
        if not self.enabled:
            return
        x0, x1, top, bot = self._geom()
        x, y = ev.x / T.S, ev.y / T.S
        z = int((x - x0) / ((x1 - x0) / 10))
        if not 0 <= z < 10:
            return
        v = max(0, min(8, int(round(8 * (bot - y) / (bot - top)))))
        if self.values[z] != v:
            self.values[z] = v
            self.redraw()
            self._on_change(self.get())

    def redraw(self) -> None:
        self.delete("all")
        x0, x1, top, bot = self._geom()
        w = (x1 - x0) / 10
        for i in range(0, 9, 2):
            y = bot - (bot - top) * i / 8
            self.create_line(x0, y, x1, y, fill=T.PANEL2)
        for z, v in enumerate(self.values):
            xa, xb = x0 + z * w + 2, x0 + (z + 1) * w - 2
            if v:
                y = bot - (bot - top) * v / 8
                self.create_rectangle(xa, y, xb, bot, fill=T.ACCENT if self.enabled else T.LINE, outline="")
                self.create_text((xa + xb) / 2, y - 7, text=str(v), fill=T.FG, font=("Segoe UI", 7))
            else:
                self.create_rectangle(xa, bot - 2, xb, bot, fill=T.PANEL2, outline="")
            self.create_text((xa + xb) / 2, bot + 9, text=f"z{z}", fill=T.BAD if z == self.marker else T.MUTED,
                             font=("Segoe UI", 7))
        if self.marker is not None:
            x = x0 + self.marker * w
            self.create_line(x, top, x, bot, fill=T.BAD, dash=(3, 2), width=T.px(2))
            self.create_text(x + 3, top, text="break", fill=T.BAD, anchor="w", font=("Segoe UI", 7))
        self.scale("all", 0, 0, T.S, T.S)

    def get(self) -> list[int]:
        return list(self.values)

    def set(self, zones: list[int], marker: Optional[int] = None) -> None:
        self.values = list(zones)
        self.marker = marker
        self.redraw()

    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self.redraw()
