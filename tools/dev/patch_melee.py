"""One-off patch: punches/strikes that hit, miss or get blocked; alternating fists; combos; sound controls."""
import json
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


# ---------------- engine ----------------
edit("sim/engine.py", [
    ('''        self.noise_phase = random.random() * 100''',
     '''        self.noise_phase = random.random() * 100
        self.hand = -1                          # last fist used (-1 left, +1 right); first strike is right
        self.combo = 0
        self.last_strike = ""'''),
    ('''        if self.kind == "melee":
            return "Press R1 to strike."''',
     '''        if self.kind == "melee":
            last = f"   ·   last: {self.last_strike.upper()}" if self.last_strike else ""
            target = "locked on - strikes land" if self.l2 >= AIM_RAW else "no target - you swing at air"
            return f"R1 strike · hold L2 to lock on ({target}){last}"'''),
    ('''    # ---------- melee: R1 strikes, triggers stay free ----------
    def _update_melee(self, pressed: int, now: float, frame: Frame) -> bytes:
        m = self.melee
        if pressed & R1 and now - self.shot_t > 0.35 / self.speed:
            self.shot_t = now
            self.shots += 1
            self._play(frame, m.get("swing", "melee_swing"))
            self._schedule(now + float(m.get("impact_ms", 140)) / 1000 / self.speed, m.get("impact", "impact_blade"))
            frame.events.append({"type": "strike", "t": now, "n": self.shots})
        return effects.off()''',
     '''    # ---------- melee: R1 strikes; locked on (L2) = a target in reach ----------
    def _update_melee(self, pressed: int, now: float, frame: Frame) -> bytes:
        """A strike is felt in three beats: the swing (whoosh on the striking hand's side), then
        either the impact (hit), a dull stopped impact (blocked) or - on a miss - nothing hits:
        the arm snaps to full extension a moment later than an impact would have landed.
        Fists alternate left/right like RDR2's jab-cross; the third hit in a row is a heavy finisher."""
        m = self.melee
        slow = 1.0 / self.speed
        if not (pressed & R1) or now - self.shot_t <= float(m.get("recover_ms", 330)) / 1000 * slow:
            return effects.off()
        in_combo = self.last_strike == "hit" and now - self.shot_t < float(m.get("combo_ms", 1100)) / 1000 * slow
        self.combo = self.combo + 1 if in_combo else 1
        self.shot_t = now
        self.shots += 1
        if m.get("alternate", False):
            self.hand = -self.hand
        else:
            self.hand = 1
        pan = 0.65 * self.hand
        if self.l2 < AIM_RAW:
            result = "miss"
        elif random.random() < float(m.get("block_chance", 0.15)):
            result = "blocked"
        else:
            result = "hit"
        finisher = result == "hit" and self.combo >= int(m.get("finisher_at", 3)) and bool(m.get("finisher"))
        impact_t = now + float(m.get("impact_ms", 140)) / 1000 * slow
        frame.haptics.append(Cue(m.get("swing", "melee_swing"), 1.0, None, self.speed, pan))
        if result == "hit":
            impacts = m.get("impact", "impact_blade")
            name = m["finisher"] if finisher else random.choice(impacts if isinstance(impacts, list) else [impacts])
            self.timers.append((impact_t, Cue(name, 1.0, None, self.speed, pan)))
        elif result == "blocked":
            self.timers.append((impact_t, Cue(m.get("blocked", "melee_blocked"), 1.0, None, self.speed, pan)))
        else:
            self.timers.append((impact_t + 0.04 * slow, Cue(m.get("miss", "melee_miss"), 1.0, None, self.speed, pan)))
        if finisher:
            self.combo = 0
        self.last_strike = "finisher" if finisher else result
        frame.events.append({"type": "strike", "t": now, "n": self.shots, "result": self.last_strike,
                             "hand": "left" if self.hand < 0 else "right", "combo": self.combo})
        return effects.off()'''),
    ('''        flash = 0 <= now - self.shot_t < 0.06 and self.kind not in ("melee", "tool")''',
     '''        flash = 0 <= now - self.shot_t < 0.06 and self.kind not in ("melee", "tool")
        if self.kind == "melee" and 0 <= now - self.shot_t < 0.15:
            frame.out.lightbar = {"hit": (255, 120, 0), "finisher": (255, 30, 0), "blocked": (90, 90, 90)}.get(
                self.last_strike, (20, 20, 60))'''),
    ('''        frame.out.lightbar = self.LIGHT.get(key, (0, 0, 0))''',
     '''        if frame.out.lightbar is None:
            frame.out.lightbar = self.LIGHT.get(key, (0, 0, 0))'''),
])

# ---------------- catalog ----------------
edit("data/weapons.json", [
    ('''      "type": "melee", "action_label": "R1 to strike (triggers stay free)",
      "melee": {"swing": "melee_swing", "impact": "impact_blade", "impact_ms": 140},''',
     '''      "type": "melee", "action_label": "R1 to strike, L2 to lock on (triggers stay free)",
      "melee": {"swing": "melee_swing", "impact": ["impact_blade", "impact_blade_deep"], "impact_ms": 140,
                "miss": "melee_miss", "blocked": "melee_blocked", "block_chance": 0.15, "recover_ms": 380,
                "combo_ms": 1100, "alternate": false},'''),
    ('''     "tune": {"melee": {"swing": "punch_swing", "impact": "punch_impact", "impact_ms": 110}}},''',
     '''     "notes": "Jab-cross: fists alternate, felt on the left or right side. Locked on (L2) your punches land - body or face; without a target you swing at air and the arm snaps out. Some get blocked (dull, stopped). Third hit in a row is a heavy finisher.",
     "tune": {"melee": {"swing": "punch_swing", "impact": ["punch_impact", "punch_impact_face"], "impact_ms": 110,
                        "miss": "punch_miss", "blocked": "punch_blocked", "finisher": "punch_finisher",
                        "finisher_at": 3, "recover_ms": 300, "combo_ms": 1100, "alternate": true}}},'''),
    ('''     "tune": {"melee": {"swing": "melee_swing_heavy", "impact": "impact_blunt", "impact_ms": 170}}},''',
     '''     "tune": {"melee": {"swing": "melee_swing_heavy", "impact": "impact_blunt", "impact_ms": 170, "miss": "melee_miss_heavy"}}},'''),
])
w = (ROOT / "data/weapons.json").read_text(encoding="utf-8")
w = w.replace('''"impact": "impact_chop", "impact_ms": 170}}}''',
              '''"impact": "impact_chop", "impact_ms": 170, "miss": "melee_miss_heavy"}}}''')
(ROOT / "data/weapons.json").write_text(w, encoding="utf-8")
json.loads(w)

# ---------------- haptic recipes ----------------
edit("data/haptics.json", [
    ('''  "punch_swing": {"gain": 1.0, "layers": [
    {"type": "noise", "lo": 80, "hi": 220, "attack_ms": 40, "decay_ms": 25, "amp": 0.2, "pan": 0.5}
  ]},
  "punch_impact": {"gain": 1.0, "layers": [
    {"type": "tone", "hz": 68, "to_hz": 48, "decay_ms": 35, "amp": 1.0, "pan": 0.5},
    {"type": "noise", "lo": 60, "hi": 200, "decay_ms": 25, "amp": 0.5, "pan": 0.5}
  ]},''',
     '''  "punch_swing": {"gain": 1.0, "layers": [
    {"type": "noise", "lo": 80, "hi": 220, "attack_ms": 35, "decay_ms": 22, "amp": 0.22}
  ]},
  "punch_impact": {"_doc": "body shot: deep, soft, the fist sinks in", "gain": 1.0, "layers": [
    {"type": "click", "hz": 170, "cycles": 1, "amp": 0.55},
    {"type": "tone", "hz": 64, "to_hz": 44, "attack_ms": 2, "decay_ms": 38, "amp": 1.0},
    {"type": "noise", "lo": 50, "hi": 180, "decay_ms": 28, "amp": 0.5}
  ]},
  "punch_impact_face": {"_doc": "face shot: harder, sharper, bone", "gain": 1.0, "layers": [
    {"type": "click", "hz": 230, "cycles": 1, "amp": 0.85},
    {"type": "tone", "hz": 82, "to_hz": 56, "attack_ms": 1, "decay_ms": 26, "amp": 0.85},
    {"type": "noise", "lo": 120, "hi": 320, "decay_ms": 14, "amp": 0.35}
  ]},
  "punch_finisher": {"_doc": "haymaker: the whole body behind it", "gain": 1.0, "layers": [
    {"type": "click", "hz": 150, "cycles": 2, "amp": 1.0},
    {"type": "tone", "hz": 56, "to_hz": 34, "attack_ms": 3, "decay_ms": 75, "amp": 1.0},
    {"type": "noise", "lo": 40, "hi": 170, "decay_ms": 55, "amp": 0.6},
    {"type": "tone", "hz": 40, "delay_ms": 60, "attack_ms": 15, "decay_ms": 60, "amp": 0.35}
  ]},
  "punch_blocked": {"_doc": "stopped by an arm: dull, no snap, short", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 52, "to_hz": 44, "attack_ms": 4, "decay_ms": 30, "amp": 0.6},
    {"type": "noise", "lo": 40, "hi": 110, "decay_ms": 25, "amp": 0.3}
  ]},
  "punch_miss": {"_doc": "nothing to hit: the arm snaps to full extension - a light jolt, no impact", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 46, "to_hz": 38, "attack_ms": 12, "decay_ms": 30, "amp": 0.28},
    {"type": "noise", "lo": 60, "hi": 140, "delay_ms": 10, "attack_ms": 20, "decay_ms": 40, "amp": 0.1}
  ]},
  "melee_miss": {"gain": 1.0, "layers": [
    {"type": "tone", "hz": 50, "to_hz": 40, "attack_ms": 10, "decay_ms": 28, "amp": 0.25}
  ]},
  "melee_miss_heavy": {"_doc": "heavy blade carries through: momentum pulls the arm", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 42, "to_hz": 34, "attack_ms": 25, "decay_ms": 60, "amp": 0.35},
    {"type": "noise", "lo": 50, "hi": 130, "attack_ms": 30, "decay_ms": 50, "amp": 0.12}
  ]},
  "melee_blocked": {"gain": 1.0, "layers": [
    {"type": "click", "hz": 260, "cycles": 1, "amp": 0.5},
    {"type": "tone", "hz": 58, "to_hz": 48, "decay_ms": 30, "amp": 0.55}
  ]},
  "impact_blade_deep": {"gain": 1.0, "layers": [
    {"type": "click", "hz": 160, "cycles": 1, "amp": 0.6},
    {"type": "noise", "lo": 60, "hi": 200, "attack_ms": 5, "decay_ms": 45, "amp": 0.6},
    {"type": "tone", "hz": 60, "to_hz": 46, "decay_ms": 40, "amp": 0.5}
  ]},'''),
])
print("melee patch applied")
