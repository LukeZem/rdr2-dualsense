"""Weapon Range: pick any weapon, shoot it, see and tune how it feels."""
from __future__ import annotations

import copy
import statistics
import tkinter as tk
from tkinter import ttk

from ds5.device import DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT, DPAD_UP, L3, OPTIONS, R3
from ds5.haptics import Cue
from sim.engine import Settings, WeaponEngine
from . import theme as T
from .widgets import AmmoPips, TravelPlot, TriggerChart, ZoneEditor

FIRE_TYPES = ("gun", "throw", "auto", "tension")


class RangePage(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master)
        self.app = app
        self.engine: WeaponEngine | None = None
        self.weapon: str | None = None
        self.work: dict | None = None             # working profile incl. unsaved tuning
        self.shot_rows: dict[int, str] = {}
        self.analyses: list[dict] = []
        self.prev_buttons = 0
        self._build()
        self._fill_tree()

    # ---------- layout ----------
    def _build(self) -> None:
        left = ttk.Frame(self, style="Panel.TFrame", padding=T.px(8))
        left.pack(side="left", fill="y")
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_tree())
        e = ttk.Entry(left, textvariable=self.search, width=24)
        e.pack(fill="x")
        ttk.Label(left, text="search weapons", style="PanelMuted.TLabel").pack(anchor="w", pady=(T.px(0), T.px(6)))
        self.tree = ttk.Treeview(left, show="tree", height=22, selectmode="browse")
        self.tree.column("#0", width=T.px(235))
        self.tree.pack(fill="y", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())
        ttk.Label(left, style="PanelMuted.TLabel", justify="left", text=(
            "controller:  ▲▼ weapon   ◄► category\n"
            "□ reload   L3+R3 Dead Eye   OPTIONS cocking\n"
            "✓ = internal name confirmed in game")).pack(anchor="w", pady=(T.px(6), T.px(0)))

        mid = ttk.Frame(self, padding=(T.px(14), T.px(6)))
        mid.pack(side="left", fill="both", expand=True)
        self.title = ttk.Label(mid, style="Title.TLabel")
        self.title.pack(anchor="w")
        self.sub = ttk.Label(mid, style="Muted.TLabel")
        self.sub.pack(anchor="w")
        self.notes = ttk.Label(mid, wraplength=T.px(640), justify="left")
        self.notes.pack(anchor="w", pady=(T.px(4), T.px(8)))
        self.chart = TriggerChart(mid, width=560, height=215)
        self.chart.pack(fill="x")
        row = ttk.Frame(mid)
        row.pack(fill="x", pady=8)
        self.badge = tk.Label(row, font=("Segoe UI Semibold", 12), fg="#111", padx=12, pady=4)
        self.badge.pack(side="left")
        self.hint = ttk.Label(row, font=("Segoe UI", 12))
        self.hint.pack(side="left", padx=12)
        self.pips = AmmoPips(mid, width=400)
        self.pips.pack(fill="x")
        self.plot = TravelPlot(mid, width=560)
        self.plot.pack(fill="x", pady=(T.px(6), T.px(6)))
        q = ttk.Frame(mid)
        q.pack(fill="x")
        self.verdict = tk.Label(q, font=T.BOLD, fg="#111", bg=T.PANEL2, padx=10, pady=3, text="shoot to measure timing")
        self.verdict.pack(side="left")
        ttk.Button(q, text="clear", command=self._clear_shots).pack(side="right")
        cols = ("n", "timing", "fired", "snap", "speed")
        self.shots = ttk.Treeview(mid, columns=cols, show="headings", height=5)
        for c, label, w in zip(cols, ("#", "shot vs snap", "fired at raw", "trigger snapped", "peak speed"),
                               (40, 140, 100, 130, 100)):
            self.shots.heading(c, text=label)
            self.shots.column(c, width=T.px(w), anchor="center")
        self.shots.pack(fill="x", pady=4)

        right = ttk.Frame(self, style="Panel.TFrame", padding=T.px(12), width=T.px(345))
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        ttk.Label(right, text="Simulation", style="H2.TLabel").pack(anchor="w")
        self.opt = {k: tk.BooleanVar(value=v) for k, v in
                    (("manual_action", True), ("fanning", True), ("dead_eye", False), ("infinite_ammo", False),
                     ("auto_align", True))}
        for key, text in (("manual_action", "Manual cocking (RDR2 default)"), ("fanning", "Fanning on hip-fire taps"),
                          ("dead_eye", "Dead Eye (slow motion)"), ("infinite_ammo", "Infinite ammo"),
                          ("auto_align", "Auto-align shot to the snap")):
            ttk.Checkbutton(right, text=text, variable=self.opt[key], command=self._rebuild).pack(anchor="w")
        r = ttk.Frame(right, style="Panel.TFrame")
        r.pack(fill="x", pady=4)
        ttk.Label(r, text="trigger engine", style="Panel.TLabel").pack(side="left")
        self.mode = tk.StringVar(value="profile")
        cb = ttk.Combobox(r, values=["profile", "feedback", "weapon", "hybrid", "simple_weapon"],
                          textvariable=self.mode, state="readonly", width=12)
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._rebuild())

        r = ttk.Frame(right, style="Panel.TFrame")
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

        ttk.Label(right, text="Tune this weapon", style="H2.TLabel").pack(anchor="w", pady=(T.px(14), T.px(2)))
        ttk.Label(right, text="pull curve: force per zone, rest → full", style="PanelMuted.TLabel").pack(anchor="w")
        self.zones = ZoneEditor(right, self._on_curve)
        self.zones.pack(anchor="w")
        self.break_zone = tk.IntVar(value=5)
        self.reset_zone = tk.IntVar(value=2)
        for text, var in (("break at zone", self.break_zone), ("re-arm below zone", self.reset_zone)):
            rr = ttk.Frame(right, style="Panel.TFrame")
            rr.pack(fill="x", pady=1)
            ttk.Label(rr, text=text, style="Panel.TLabel").pack(side="left")
            ttk.Spinbox(rr, from_=1, to=9, width=4, textvariable=var, command=self._on_tune).pack(side="right")
        self.kick = tk.IntVar(value=100)
        self.hgain = tk.IntVar(value=100)
        for text, var in (("trigger recoil %", self.kick), ("haptic strength %", self.hgain)):
            ttk.Label(right, text=text, style="Panel.TLabel").pack(anchor="w", pady=(T.px(4), T.px(0)))
            T.scale(right, from_=0, to=200, orient="horizontal", variable=var, length=310, resolution=5,
                    command=lambda _v: self._on_tune()).pack(anchor="w")
        b = ttk.Frame(right, style="Panel.TFrame")
        b.pack(fill="x", pady=8)
        ttk.Button(b, text="Save to weapons.json", style="Accent.TButton", command=self._save).pack(side="left")
        ttk.Button(b, text="Revert", command=self._revert).pack(side="left", padx=6)
        self.saved = ttk.Label(right, style="PanelMuted.TLabel")
        self.saved.pack(anchor="w")

        ttk.Label(right, text="Feel it", style="H2.TLabel").pack(anchor="w", pady=(T.px(10), T.px(2)))
        t = ttk.Frame(right, style="Panel.TFrame")
        t.pack(fill="x")
        ttk.Button(t, text="▶ shot", command=lambda: self._test("shot")).pack(side="left")
        ttk.Button(t, text="▶ action", command=lambda: self._test("action")).pack(side="left", padx=4)
        ttk.Button(t, text="▶ reload", command=lambda: self._test("reload")).pack(side="left")
        self.source = ttk.Label(right, style="PanelMuted.TLabel", wraplength=T.px(315), justify="left")
        self.source.pack(anchor="w", pady=6)

    def _sound(self) -> None:
        mode = {"PC speakers": "pc", "controller speaker": "controller"}.get(self.sound.get(), "off")
        self.app.rt.set_sound(mode, self.volume.get() / 100)
        rt = self.app.rt
        self.sound_status.config(text=rt.sound_error or (
            f"playing on {rt.speaker.device_name}" if rt.speaker else
            "playing on the controller's speaker" if rt.sound_mode == "controller" else "muted"))

    # ---------- weapon list ----------
    def _fill_tree(self) -> None:
        q = self.search.get().lower().strip() if hasattr(self, "search") else ""
        self.tree.delete(*self.tree.get_children())
        cat = self.app.catalog
        first = None
        for c in cat.categories():
            items = [w for w in cat.in_category(c)
                     if not q or q in w["label"].lower() or q in w["name"].lower()]
            if not items:
                continue
            node = self.tree.insert("", "end", iid=f"cat:{c}", text=f"{c}  ({len(items)})", open=True)
            for w in items:
                mark = "✓ " if w.get("verified") else "   "
                self.tree.insert(node, "end", iid=w["name"], text=f"{mark}{w['label']}")
                first = first or w["name"]
        target = self.weapon if self.weapon and self.tree.exists(self.weapon) else first
        if target:
            self.tree.selection_set(target)
            self.tree.see(target)

    def _visible_weapons(self) -> list[str]:
        return [i for c in self.tree.get_children() for i in self.tree.get_children(c)]

    def _on_select(self) -> None:
        sel = self.tree.selection()
        if not sel or sel[0].startswith("cat:"):
            if sel:
                kids = self.tree.get_children(sel[0])
                if kids:
                    self.tree.selection_set(kids[0])
            return
        if sel[0] != self.weapon:
            self.weapon = sel[0]
            self.work = self.app.catalog.resolve(self.weapon)
            self._load_tune_widgets()
            self._clear_shots()
            self._rebuild()

    def _step_weapon(self, step: int) -> None:
        ws = self._visible_weapons()
        if ws:
            i = ws.index(self.weapon) if self.weapon in ws else 0
            nxt = ws[(i + step) % len(ws)]
            self.tree.selection_set(nxt)
            self.tree.see(nxt)

    def _step_category(self, step: int) -> None:
        cats = list(self.tree.get_children())
        if not cats:
            return
        cur = self.tree.parent(self.weapon) if self.weapon and self.tree.exists(self.weapon) else cats[0]
        nxt = cats[(cats.index(cur) + step) % len(cats)]
        kids = self.tree.get_children(nxt)
        if kids:
            self.tree.selection_set(kids[0])
            self.tree.see(kids[0])

    # ---------- engine ----------
    def settings(self) -> Settings:
        return Settings(manual_action=self.opt["manual_action"].get(), fanning=self.opt["fanning"].get(),
                        dead_eye=self.opt["dead_eye"].get(), infinite_ammo=self.opt["infinite_ammo"].get(),
                        mode_override=None if self.mode.get() == "profile" else self.mode.get(),
                        audio_latency_ms=self.app.rt.kick_delay_ms)

    def _rebuild(self) -> None:
        if not self.work:
            return
        prof = copy.deepcopy(self.work)
        lib = self.app.rt.library
        name = lib.ensure_weapon(prof)
        if name:
            prof.setdefault("recoil", {})["haptic"] = name
            prof["recoil"]["kick_variants"] = lib.kicks.get(name, [])
        try:
            self.engine = WeaponEngine(prof, self.app.calib, self.settings())
        except Exception as e:
            self.app.log(f"profile error in {self.weapon}: {e}")
            return
        self.app.set_driver(self, self.engine)
        w = self.app.catalog.get(self.weapon)
        self.title.config(text=w["label"])
        self.sub.config(text=f"{w['name']}  ·  {prof['hash']}  ·  {prof.get('action_label', prof.get('type'))}"
                             + ("" if w.get("verified") else "  ·  name unverified"))
        self.notes.config(text=w.get("notes") or prof.get("notes", ""))
        shot = prof.get("recoil", {}).get("haptic")
        src = lib.source.get(shot, "synth") if shot else "-"
        self.source.config(text=f"shot haptic: {src}" + ("" if name or not prof.get("bank") else
                                                         f"\n(bank {prof['bank']} not found - synthesized)"))

    def on_show(self) -> None:
        if self.engine:
            self.app.set_driver(self, self.engine)
        else:
            self._on_select()

    # ---------- tuning ----------
    def _load_tune_widgets(self) -> None:
        f = self.work.get("fire", {})
        self.zones.set(f.get("curve", [0] * 10))
        self.break_zone.set(f.get("break_zone", 5))
        self.reset_zone.set(f.get("reset_zone", 2))
        self.kick.set(int(100 * self.work.get("kick_scale", 1.0)))
        self.hgain.set(int(100 * self.work.get("haptic_gain", 1.0)))
        self.zones.set(f.get("curve", [0] * 10), f.get("break_zone"))
        self.zones.set_enabled(self.work.get("type") in FIRE_TYPES)
        self.saved.config(text="")

    def _on_curve(self, zones: list[int]) -> None:
        self._on_tune()

    def _on_tune(self) -> None:
        if not self.work or self.work.get("type") not in FIRE_TYPES:
            return
        try:
            bz, rz = int(self.break_zone.get()), int(self.reset_zone.get())
        except (tk.TclError, ValueError):
            return
        zones = self.zones.get()
        zones = [z if i < bz else 0 for i, z in enumerate(zones)]     # nothing after the break
        fire = self.work.setdefault("fire", {})
        if fire.get("break_zone") != bz:
            fire.pop("break_raw", None)
            self.analyses.clear()
        fire.update(curve=zones, break_zone=bz, reset_zone=min(rz, bz - 1))
        self.zones.set(zones, bz)
        self.work["kick_scale"] = self.kick.get() / 100
        self.work["haptic_gain"] = self.hgain.get() / 100
        self.saved.config(text="unsaved changes")
        self._rebuild()

    def _save(self) -> None:
        if not self.work:
            return
        f = self.work.get("fire", {})
        tune = {"kick_scale": self.work.get("kick_scale", 1.0), "haptic_gain": self.work.get("haptic_gain", 1.0)}
        if self.work.get("type") in FIRE_TYPES:
            tune["fire"] = {"curve": f["curve"], "break_zone": f["break_zone"], "reset_zone": f["reset_zone"]}
            if "break_raw" in f:
                tune["fire"]["break_raw"] = f["break_raw"]
        self.app.catalog.save_tune(self.weapon, tune)
        self.saved.config(text="saved to weapons.json")
        self.app.log(f"saved tuning for {self.weapon}")

    def _revert(self) -> None:
        self.app.catalog.reload()
        self.work = self.app.catalog.resolve(self.weapon)
        self._load_tune_widgets()
        self._rebuild()

    def _test(self, what: str) -> None:
        if not self.engine:
            return
        e, p = self.engine, self.engine.p
        if what == "shot":
            self.app.rt.play(Cue(p.get("recoil", {}).get("haptic") or "shot_revolver", e.haptic_gain, None, e.speed))
        elif what == "action":
            a = p.get("action", {})
            self.app.rt.play(a.get("auto") or a.get("open") or (p.get("melee") or {}).get("impact"))
        else:
            r = p.get("reload", {})
            for name in (r.get("begin"), r.get("tick"), r.get("end")):
                self.app.rt.play(name)

    # ---------- live ----------
    def tick(self) -> None:
        rt, e = self.app.rt, self.engine
        s = rt.state
        pressed = s.buttons & ~self.prev_buttons
        self.prev_buttons = s.buttons
        if pressed & DPAD_DOWN:
            self._step_weapon(1)
        elif pressed & DPAD_UP:
            self._step_weapon(-1)
        elif pressed & DPAD_RIGHT:
            self._step_category(1)
        elif pressed & DPAD_LEFT:
            self._step_category(-1)
        if (pressed & (L3 | R3)) and (s.buttons & L3) and (s.buttons & R3):
            self.opt["dead_eye"].set(not self.opt["dead_eye"].get())
            rt.play("deadeye_in" if self.opt["dead_eye"].get() else "deadeye_out")
            self._rebuild()
        if pressed & OPTIONS:
            self.opt["manual_action"].set(not self.opt["manual_action"].get())
            self._rebuild()
        if not e:
            return
        frame = rt.frame
        out = frame.out if frame and rt.driver is e else None
        markers = []
        if e.kind in FIRE_TYPES:
            markers = [(e.break_raw, T.BAD, "break"), (e.reset_raw, T.GOOD, "re-arm")]
        cal = self.app.calib
        self.chart.draw(cal.r2, out.r2 if out else bytes(11), s.r2, out.l2 if out else bytes(11), s.l2, cal.l2,
                        markers, self._labels(), frame.game_rt if frame else 0)
        state = "empty" if e.state == "ready" and e.clip == 0 and not e.set.infinite_ammo else e.state
        self.badge.config(text=state.upper(), bg=T.STATE_COLORS.get(state, T.MUTED))
        self.hint.config(text=e.hint() + ("   ·   DEAD EYE" if e.set.dead_eye else ""))
        self.pips.draw(e.clip, e.clip_size, e.set.infinite_ammo)
        self.plot.draw(list(rt.history), list(rt.shot_marks), markers)

    def _labels(self) -> list[tuple[int, int, str]]:
        e = self.engine
        if not e or e.kind != "gun" or e.mode != "feedback" or e.state != "ready":
            return []
        c = e.curve
        bz = int(e.p.get("fire", {}).get("break_zone", 6))
        peak = max(c[:bz] or [0])
        if not peak:
            return []
        ws = next(i for i in range(bz) if c[i] >= max(2, peak * 0.6))
        out = []
        if ws > 0:
            out.append((0, ws, "take-up"))
        out.append((ws, bz, "wall" if bz - ws <= 2 else "stacking"))
        end = e.stop_zone or 10
        if end > bz:
            out.append((bz, end, "overtravel"))
        if e.stop_zone:
            out.append((e.stop_zone, 10, "stop"))
        return out

    # ---------- shots ----------
    def on_event(self, ev: dict) -> None:
        if ev["type"] == "strike":
            colors = {"hit": T.GOOD, "finisher": T.ACCENT, "blocked": T.MUTED, "miss": T.BAD}
            combo = f"  ·  combo {ev['combo']}" if ev["result"] == "hit" and ev["combo"] > 1 else ""
            self.verdict.config(text=f"{ev['result'].upper()}  ·  {ev['hand']} hand{combo}",
                                bg=colors.get(ev["result"], T.PANEL2), fg="#111")
            return
        if ev["type"] == "shot" and "break_raw" in ev:
            tag = " (fanned)" if ev.get("fanned") else ""
            iid = self.shots.insert("", 0, values=(ev["n"], "measuring..." if not ev.get("fanned") else "fanned",
                                                   ev["raw"], "", ""))
            self.shot_rows[ev["n"]] = iid
            if tag:
                self.app.log(f"shot {ev['n']}{tag}")
        elif ev["type"] == "analysis":
            iid = self.shot_rows.get(ev["n"])
            if ev["snap"]:
                dt = ev["dt_ms"]
                timing = "on the snap" if abs(dt) <= 4 else (f"{-dt:.0f} ms early" if dt < 0 else f"{dt:.0f} ms late")
                snap = f"{ev['snap_from']} → {ev['snap_to']}"
                self.analyses.append(ev)
                self._align()
                self._verdict()
            else:
                timing, snap = "no snap felt", "-"
            if iid and self.shots.exists(iid):
                self.shots.item(iid, values=(ev["n"], timing, ev["fire_raw"], snap, ev["peak_vel"]))

    def _align(self) -> None:
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

    def _verdict(self) -> None:
        a = self.analyses[-12:]
        dts = [x["dt_ms"] for x in a]
        med = statistics.median(dts)
        early = sum(d < -6 for d in dts)
        if abs(med) <= 4 and not early:
            self.verdict.config(text=f"✓ shots land on the snap  (median {med:+.0f} ms, {len(a)} shots)", bg=T.GOOD, fg="#111")
        elif early:
            self.verdict.config(text=f"⚠ {early} of {len(a)} fired before the snap - calibrate R2", bg=T.WARN, fg="#111")
        else:
            self.verdict.config(text=f"⚠ shots land {med:+.0f} ms after the snap", bg=T.WARN, fg="#111")

    def _clear_shots(self) -> None:
        self.shots.delete(*self.shots.get_children())
        self.shot_rows.clear()
        self.analyses.clear()
        self.verdict.config(text="shoot to measure timing", bg=T.PANEL2, fg=T.MUTED)
