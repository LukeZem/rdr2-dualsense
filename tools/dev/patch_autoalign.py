from pathlib import Path
ROOT = Path(__file__).resolve().parents[1] / "trigger_lab"

def edit(rel, pairs):
    p = ROOT / rel; s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{rel}: not found: {a[:80]!r}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")

edit("ui/range_page.py", [
    ('''        self.opt = {k: tk.BooleanVar(value=v) for k, v in
                    (("manual_action", True), ("fanning", True), ("dead_eye", False), ("infinite_ammo", False))}''',
     '''        self.opt = {k: tk.BooleanVar(value=v) for k, v in
                    (("manual_action", True), ("fanning", True), ("dead_eye", False), ("infinite_ammo", False),
                     ("auto_align", True))}'''),
    ('''                          ("dead_eye", "Dead Eye (slow motion)"), ("infinite_ammo", "Infinite ammo")):''',
     '''                          ("dead_eye", "Dead Eye (slow motion)"), ("infinite_ammo", "Infinite ammo"),
                          ("auto_align", "Auto-align shot to the snap")):'''),
    ('''                self.analyses.append(ev)
                self._verdict()''',
     '''                self.analyses.append(ev)
                self._align()
                self._verdict()'''),
    ('''    def _verdict(self) -> None:''',
     '''    def _align(self) -> None:
        """Learn where this trigger really breaks: under a firm squeeze the wall gives way later
        than the gentle calibration press suggests. After 3 measured snaps the shot threshold
        moves to just before the median snap point (last 5 shots)."""
        e = self.engine
        if not self.opt["auto_align"].get() or not e or e.kind != "gun" or len(self.analyses) < 3:
            return
        snaps = sorted(a["snap_from"] for a in self.analyses[-5:])
        target = snaps[len(snaps) // 2] + 2
        if abs(target - e.break_raw) < 3:
            return
        old = e.break_raw
        e.break_raw = target
        e.reset_raw = min(e.reset_raw, target - 25)
        self.work.setdefault("fire", {})["break_raw"] = target
        self.saved.config(text="shot point auto-aligned - Save to keep it")
        self.app.log(f"{self.weapon}: shot threshold {old} -> {target} (trigger snaps at ~{target - 2})")

    def _verdict(self) -> None:'''),
    ('''        if self.work.get("type") in FIRE_TYPES:
            tune["fire"] = {"curve": f["curve"], "break_zone": f["break_zone"], "reset_zone": f["reset_zone"]}''',
     '''        if self.work.get("type") in FIRE_TYPES:
            tune["fire"] = {"curve": f["curve"], "break_zone": f["break_zone"], "reset_zone": f["reset_zone"]}
            if "break_raw" in f:
                tune["fire"]["break_raw"] = f["break_raw"]'''),
    # editing the curve/break zone invalidates a learned point
    ('''        self.work.setdefault("fire", {}).update(curve=zones, break_zone=bz, reset_zone=min(rz, bz - 1))''',
     '''        fire = self.work.setdefault("fire", {})
        if fire.get("break_zone") != bz:
            fire.pop("break_raw", None)
            self.analyses.clear()
        fire.update(curve=zones, break_zone=bz, reset_zone=min(rz, bz - 1))'''),
])
print("auto-align patch applied")
