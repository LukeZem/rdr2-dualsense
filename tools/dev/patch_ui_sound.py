"""One-off patch: game sound controls on the Range, strike results, PC speakers on by default."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "trigger_lab"


def edit(rel, pairs):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{rel}: not found: {a[:80]!r}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


edit("ui/range_page.py", [
    ('''        ttk.Label(right, text="Tune this weapon", style="H2.TLabel").pack(anchor="w", pady=(T.px(14), T.px(2)))''',
     '''        r = ttk.Frame(right, style="Panel.TFrame")
        r.pack(fill="x", pady=(T.px(8), 0))
        ttk.Label(r, text="game sound", style="Panel.TLabel").pack(side="left")
        self.sound = tk.StringVar(value={"pc": "PC speakers", "controller": "controller speaker"}.get(
            self.app.rt.sound_mode, "off"))
        sc = ttk.Combobox(r, values=["PC speakers", "controller speaker", "off"], textvariable=self.sound,
                          state="readonly", width=16)
        sc.pack(side="right")
        sc.bind("<<ComboboxSelected>>", lambda _e: self._sound())
        self.volume = tk.IntVar(value=int(self.app.rt.sound_gain * 100))
        ttk.Label(right, text="game sound volume %", style="Panel.TLabel").pack(anchor="w", pady=(T.px(4), 0))
        T.scale(right, from_=0, to=100, orient="horizontal", variable=self.volume, length=310, resolution=5,
                command=lambda _v: self._sound()).pack(anchor="w")
        self.sound_status = ttk.Label(right, style="PanelMuted.TLabel", wraplength=T.px(315))
        self.sound_status.pack(anchor="w")

        ttk.Label(right, text="Tune this weapon", style="H2.TLabel").pack(anchor="w", pady=(T.px(14), T.px(2)))'''),
    ('''    # ---------- weapon list ----------''',
     '''    def _sound(self) -> None:
        mode = {"PC speakers": "pc", "controller speaker": "controller"}.get(self.sound.get(), "off")
        self.app.rt.set_sound(mode, self.volume.get() / 100)
        rt = self.app.rt
        self.sound_status.config(text=rt.sound_error or (
            f"playing on {rt.speaker.device_name}" if rt.speaker else
            "playing on the controller's speaker" if rt.sound_mode == "controller" else "muted"))

    # ---------- weapon list ----------'''),
    ('''    def on_event(self, ev: dict) -> None:
        if ev["type"] == "shot" and "break_raw" in ev:''',
     '''    def on_event(self, ev: dict) -> None:
        if ev["type"] == "strike":
            colors = {"hit": T.GOOD, "finisher": T.ACCENT, "blocked": T.MUTED, "miss": T.BAD}
            combo = f"  ·  combo {ev['combo']}" if ev["result"] == "hit" and ev["combo"] > 1 else ""
            self.verdict.config(text=f"{ev['result'].upper()}  ·  {ev['hand']} hand{combo}",
                                bg=colors.get(ev["result"], T.PANEL2), fg="#111")
            return
        if ev["type"] == "shot" and "break_raw" in ev:'''),
])

edit("lab.py", [
    ('''            self.rt.set_haptics("audio" if self.rt.ds.transport == "USB" else "rumble")''',
     '''            self.rt.set_haptics("audio" if self.rt.ds.transport == "USB" else "rumble")
            self.rt.set_sound("pc", 0.5)'''),
])
print("ui sound patch applied")
