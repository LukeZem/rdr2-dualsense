from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "trigger_lab"

def edit(rel, pairs):
    p = ROOT / rel; s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{rel}: not found: {a[:80]!r}")
        s = s.replace(a, b)
    p.write_text(s, encoding="utf-8")

edit("ui/widgets.py", [
    # TriggerChart: follow the real width
    ('''    def draw(self, table: list[int], r2_block: bytes, r2: int, l2_block: bytes, l2: int, l2_table: list[int],
             markers: list[tuple[int, str, str]], labels: list[tuple[int, int, str]], game_rt: int) -> None:
        self.delete("all")''',
     '''    def draw(self, table: list[int], r2_block: bytes, r2: int, l2_block: bytes, l2: int, l2_table: list[int],
             markers: list[tuple[int, str, str]], labels: list[tuple[int, int, str]], game_rt: int) -> None:
        self.delete("all")
        real = self.winfo_width() / T.S
        if real > 300:
            self.w, self.x1 = real, real - 54'''),
    # TravelPlot
    ('''    def draw(self, history: list, shots: list[float], markers: list[tuple[int, str, str]]) -> None:
        self.delete("all")''',
     '''    def draw(self, history: list, shots: list[float], markers: list[tuple[int, str, str]]) -> None:
        self.delete("all")
        real = self.winfo_width() / T.S
        if real > 300:
            self.w = real'''),
    # AmmoPips
    ('''    def draw(self, clip: Optional[int], size: Optional[int], infinite: bool) -> None:
        self.delete("all")''',
     '''    def draw(self, clip: Optional[int], size: Optional[int], infinite: bool) -> None:
        self.delete("all")
        real = self.winfo_width() / T.S
        if real > 100:
            self.w = real'''),
])
edit("ui/range_page.py", [
    ("self.chart = TriggerChart(mid, width=760, height=215)", "self.chart = TriggerChart(mid, width=560, height=215)"),
    ("        self.chart.pack(anchor=\"w\")", "        self.chart.pack(fill=\"x\")"),
    ("self.plot = TravelPlot(mid, width=760)", "self.plot = TravelPlot(mid, width=560)"),
    ("        self.plot.pack(anchor=\"w\", pady=(T.px(6), T.px(6)))", "        self.plot.pack(fill=\"x\", pady=(T.px(6), T.px(6)))"),
    ("self.pips = AmmoPips(mid, width=760)", "self.pips = AmmoPips(mid, width=400)"),
    ("        self.pips.pack(anchor=\"w\")", "        self.pips.pack(fill=\"x\")"),
    ("self.notes = ttk.Label(mid, wraplength=T.px(760)", "self.notes = ttk.Label(mid, wraplength=T.px(640)"),
    ('''        for c, label, w in zip(cols, ("#", "shot vs snap", "fired at raw", "trigger snapped", "peak speed"),
                               (40, 150, 110, 150, 110)):''',
     '''        for c, label, w in zip(cols, ("#", "shot vs snap", "fired at raw", "trigger snapped", "peak speed"),
                               (40, 140, 100, 130, 100)):'''),
    ("        self.shots.pack(anchor=\"w\", pady=4)", "        self.shots.pack(fill=\"x\", pady=4)"),
    ('self.tree.column("#0", width=T.px(250))', 'self.tree.column("#0", width=T.px(235))'),
    ("e = ttk.Entry(left, textvariable=self.search, width=30)", "e = ttk.Entry(left, textvariable=self.search, width=24)"),
])
edit("lab.py", [("nav = tk.Frame(body, bg=T.PANEL, width=T.px(215))", "nav = tk.Frame(body, bg=T.PANEL, width=T.px(200))")])
print("patched")
