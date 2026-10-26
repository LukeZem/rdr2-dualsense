"""One-off patch: canvas Slider + bar ZoneEditor, wider tune panel."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "trigger_lab"

NEW_WIDGETS = r'''class Slider(tk.Canvas):
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
'''


def edit(rel: str, pairs: list[tuple[str, str]]) -> None:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{rel}: not found: {a[:80]!r}")
        s = s.replace(a, b)
    p.write_text(s, encoding="utf-8")


w = ROOT / "ui" / "widgets.py"
s = w.read_text(encoding="utf-8")
s = s[: s.index("class ZoneEditor(tk.Frame):")] + NEW_WIDGETS
w.write_text(s, encoding="utf-8")

t = ROOT / "ui" / "theme.py"
s = t.read_text(encoding="utf-8")
s = s[: s.index("def scale(master, **kw)")] + '''def scale(master, **kw):
    """Themed slider (ui.widgets.Slider) taking tk.Scale-like arguments."""
    from .widgets import Slider
    kw.pop("orient", None)
    return Slider(master, **kw)
'''
t.write_text(s, encoding="utf-8")

edit("ui/range_page.py", [
    ('''        right = ttk.Frame(self, style="Panel.TFrame", padding=T.px(10))
        right.pack(side="left", fill="y")''',
     '''        right = ttk.Frame(self, style="Panel.TFrame", padding=T.px(12), width=T.px(345))
        right.pack(side="right", fill="y")
        right.pack_propagate(False)'''),
    ('''        state = "normal" if self.work.get("type") in FIRE_TYPES else "disabled"
        for child in self.zones.winfo_children():
            for s in child.winfo_children():
                try:
                    s.config(state=state)
                except tk.TclError:
                    pass
        self.saved.config(text="")''',
     '''        self.zones.set(f.get("curve", [0] * 10), f.get("break_zone"))
        self.zones.set_enabled(self.work.get("type") in FIRE_TYPES)
        self.saved.config(text="")'''),
    ('''        self.work.setdefault("fire", {}).update(curve=zones, break_zone=bz, reset_zone=min(rz, bz - 1))''',
     '''        self.work.setdefault("fire", {}).update(curve=zones, break_zone=bz, reset_zone=min(rz, bz - 1))
        self.zones.set(zones, bz)'''),
    ("self.chart = TriggerChart(mid, width=800, height=215)", "self.chart = TriggerChart(mid, width=760, height=215)"),
    ("self.plot = TravelPlot(mid, width=800)", "self.plot = TravelPlot(mid, width=760)"),
    ("self.pips = AmmoPips(mid, width=800)", "self.pips = AmmoPips(mid, width=760)"),
    ("self.notes = ttk.Label(mid, wraplength=T.px(800)", "self.notes = ttk.Label(mid, wraplength=T.px(760)"),
    ('variable=var, length=250, resolution=5,', 'variable=var, length=310, resolution=5,'),
    ('style="PanelMuted.TLabel", wraplength=T.px(260), justify="left")',
     'style="PanelMuted.TLabel", wraplength=T.px(315), justify="left")'),
])
edit("ui/other_pages.py", [
    ("self.zones = ZoneEditor(row, lambda _z: self.apply())",
     "self.zones = ZoneEditor(row, lambda _z: self.apply(), width=420, height=160)"),
])
print("patched")
