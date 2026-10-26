"""Weapon trigger simulation - the logic the RDR2 mod will run in-game.

Fed with every controller input sample (~250 Hz). For each sample it decides
the R2/L2 effect blocks, whether a shot happens (and what RT value the game
would be given), which haptic cues to play, and a debug lightbar colour.

Core rule for a consistent shot moment: the shot is decided here, from the
trigger *position*, at the exact zone where the resistance ends (the break).
The game only ever sees RT = 0 before the break and RT = 255 after it, so its
own threshold no longer matters.

RDR2 behaviour modelled: single-action hammers, levers, bolts and pumps are
cycled with an R2 tap between shots; pulling an empty gun starts a reload;
single-action revolvers can be fanned when hip-firing rapidly; Dead Eye slows
everything down.
"""
from __future__ import annotations

import json
import math
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ds5 import effects
from ds5.device import CIRCLE, InputState, OutputState, R1, SQUARE
from ds5.haptics import Cue

ZONES = effects.ZONES
# Raw trigger value where each zone starts, until the controller is calibrated.
DEFAULT_ZONE_RAW = [0, 26, 51, 77, 102, 128, 153, 179, 204, 230]
AIM_RAW = 40                     # L2 above this = aiming (no fanning while aiming)


@dataclass
class Calibration:
    r2: list[int] = field(default_factory=lambda: list(DEFAULT_ZONE_RAW))
    l2: list[int] = field(default_factory=lambda: list(DEFAULT_ZONE_RAW))
    calibrated: bool = False

    def table(self, trigger: str) -> list[int]:
        return self.r2 if trigger == "r2" else self.l2

    def raw_at(self, zone: int, trigger: str = "r2") -> int:
        """Raw value where `zone` starts; zone 10 = fully pressed."""
        return 255 if zone >= ZONES else self.table(trigger)[max(0, zone)]

    def zone_of(self, raw: int, trigger: str = "r2") -> int:
        t = self.table(trigger)
        z = 0
        for i in range(ZONES):
            if raw >= t[i]:
                z = i
        return z

    @classmethod
    def load(cls, path: Path) -> "Calibration":
        if not path.exists():
            return cls()
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(r2=d["r2"], l2=d["l2"], calibrated=True)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"r2": self.r2, "l2": self.l2}, indent=2), encoding="utf-8")


@dataclass
class Settings:
    manual_action: bool = True          # RDR2 default; False = like the "Automatic Cocking" mod
    fanning: bool = True                # hip-fire rapid taps fan a single-action hammer
    dead_eye: bool = False
    infinite_ammo: bool = False
    auto_reload: bool = True            # RDR2 reloads when you pull an empty gun
    mode_override: Optional[str] = None  # feedback | weapon | hybrid | simple_weapon
    fire_margin: int = 4                 # raw units past the break zone start before firing
    audio_latency_ms: float = 0.0        # recoil on the trigger waits for the haptic audio
    kick_scale: float = 1.0              # trigger recoil strength multiplier


@dataclass
class Frame:
    out: OutputState
    haptics: list[Cue] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    game_rt: int = 0
    state: str = ""


def _curve(values, name: str) -> list[int]:
    v = [int(x) for x in values]
    if len(v) != ZONES or not all(0 <= x <= 8 for x in v):
        raise ValueError(f"{name}: need {ZONES} zone strengths 0-8, got {values}")
    return v


class StaticDriver:
    """Effect Lab: whatever the UI set, no logic."""

    def __init__(self) -> None:
        self.out = OutputState()

    def update(self, s: InputState) -> Frame:
        return Frame(out=self.out, state="lab")


class Kick:
    """Recoil on the trigger: a decaying vibration envelope."""

    def __init__(self, spec: Optional[dict], scale: float = 1.0, stretch: float = 1.0) -> None:
        spec = spec or {}
        self.freq = int(spec.get("freq", 40))
        self.base = [int(a) for a in spec.get("steps", [])]
        self.scale = scale
        self.step_s = float(spec.get("step_ms", 16)) / 1000 * stretch
        self.steps = self._scaled(self.base)

    def _scaled(self, steps: list[int]) -> list[int]:
        return [max(1, min(8, round(a * self.scale))) for a in steps if a > 0]

    def shaped(self, audio_steps: Optional[list[int]]) -> None:
        """Use the recording's decay inside the class envelope (never stronger or longer)."""
        if audio_steps:
            self.steps = self._scaled([min(a, b) for a, b in zip(self.base, audio_steps + [1] * len(self.base))])
        else:
            self.steps = self._scaled(self.base)

    @property
    def duration(self) -> float:
        return len(self.steps) * self.step_s

    def block(self, dt: float) -> Optional[bytes]:
        i = int(dt / self.step_s) if self.step_s > 0 else len(self.steps)
        if dt < 0 or i >= len(self.steps):
            return None
        return effects.vibration(0, self.steps[i], self.freq)


class WeaponEngine:
    LIGHT = {"ready": (0, 40, 0), "empty": (60, 0, 0), "flash": (255, 120, 0), "held": (40, 25, 0),
             "action": (0, 0, 70), "cycling": (0, 30, 80), "reloading": (40, 0, 40),
             "draw": (60, 50, 0), "firing": (255, 60, 0), "flying": (30, 30, 30), "tethered": (70, 35, 0)}

    def __init__(self, profile: dict, calib: Calibration, settings: Settings) -> None:
        self.p = profile
        self.cal = calib
        self.set = settings
        self.kind = profile.get("type", "gun")
        slow = 1.7 if settings.dead_eye else 1.0
        self.speed = 0.6 if settings.dead_eye else 1.0
        f = profile.get("fire", {})
        self.mode = settings.mode_override or f.get("engine", "feedback")
        self.curve = _curve(f.get("curve", [0] * ZONES), "fire.curve")
        if settings.dead_eye:                              # time thickens: everything a bit heavier
            self.curve = [min(8, c + 1) if c else 0 for c in self.curve]
        self.weapon_fx = f.get("weapon_effect", [4, 6, 6])
        self.simple_fx = f.get("simple_weapon", [100, 160, 200])
        self.break_raw = self._break_raw(f)
        self.reset_raw = calib.raw_at(int(f.get("reset_zone", 2)))
        self.stop_zone = int(f.get("stop_zone", 0))
        self.stop_strength = int(f.get("stop_strength", 8))
        self.empty_feel = f.get("empty", "click")
        self.after_curve = _curve(profile.get("after_shot", [1] * ZONES), "after_shot")
        self.grit = float(f.get("grit", 0.0))
        self.ticks = {int(t["zone"]): t for t in f.get("ticks", [])}
        rec = profile.get("recoil", {})
        self.kick = Kick(rec.get("trigger"), settings.kick_scale * float(profile.get("kick_scale", 1.0)), slow)
        self.haptic_gain = float(profile.get("haptic_gain", 1.0))
        self.kick_variants: list[list[int]] = rec.get("kick_variants", [])
        self.lock_s = float(rec.get("lock_ms", 5)) / 1000 * slow
        self.shot_haptic = rec.get("haptic")
        self.rate_s = float(profile.get("rate_ms", 400)) / 1000 * slow
        self.action = profile.get("action", {"type": "none"})
        self.action_curve = _curve(self.action.get("curve", [0] * ZONES), "action.curve")
        self.action_break_raw = calib.raw_at(int(self.action.get("break_zone", 7))) + settings.fire_margin
        self.action_ticks = {int(t["zone"]): t for t in self.action.get("ticks", [])}
        self.clip_size = int(profile.get("clip", 0) or 0) or None
        self.clip = self.clip_size
        self.reload = profile.get("reload", {})
        self.aim_block = effects.multi_feedback(_curve(profile.get("aim_curve", [0] * ZONES), "aim_curve"))
        self.bow = profile.get("draw", {})
        self.melee = profile.get("melee", {})
        self.tension = profile.get("tension", {})
        # runtime state
        self.state = "ready"
        self.game_rt = 0
        self.shot_t = -10.0
        self.kick_t = -10.0
        self.action_t = -10.0
        self.reload_t = -10.0
        self.reload_ticks_done = 0
        self.reload_rounds = 0
        self.draw_t = -10.0
        self.last_dry = False
        self.fanned = False
        self.prev_raw = 0
        self.prev_t = 0.0
        self.prev_buttons = 0
        self.vel = 0.0
        self.l2 = 0
        self.timers: list[tuple[float, Cue]] = []
        self.bumps: dict[int, float] = {}
        self.grit_until = 0.0
        self.grit_zone = (-1, 0)
        self.history: deque = deque(maxlen=200)
        self.pending: list[dict] = []
        self.shots = 0
        self.next_heartbeat = 0.0
        self.tether_t = -10.0
        self.next_jerk = 0.0
        self.jerk_until = 0.0
        self.noise_phase = random.random() * 100
        self.hand = -1                          # last fist used (-1 left, +1 right); first strike is right
        self.combo = 0
        self.last_strike = ""

    # ---------- helpers ----------
    def _break_raw(self, f: dict) -> int:
        if "break_raw" in f:
            return int(f["break_raw"])
        if self.mode in ("weapon", "hybrid"):
            zone = int(self.weapon_fx[1])
        elif self.mode == "simple_weapon":
            return int(self.simple_fx[1])
        else:
            zone = int(f.get("break_zone", 6))
        return self.cal.raw_at(zone) + self.set.fire_margin

    def _zone(self, raw: int) -> int:
        return self.cal.zone_of(raw, "r2")

    def cue(self, name: Optional[str], gain: float = 1.0, variant: Optional[int] = None) -> Optional[Cue]:
        return Cue(name, gain, variant, self.speed) if name else None

    def _play(self, frame: Frame, name: Optional[str], gain: float = 1.0, variant: Optional[int] = None) -> None:
        c = self.cue(name, gain, variant)
        if c:
            frame.haptics.append(c)

    def _schedule(self, at: float, name: Optional[str], gain: float = 1.0, variant: Optional[int] = None) -> None:
        c = self.cue(name, gain, variant)
        if c:
            self.timers.append((at, c))

    def _fire_block(self, raw: int, now: float) -> bytes:
        if self.clip == 0 and self.empty_feel == "dead" and not self.set.infinite_ammo:
            return effects.multi_feedback([0, 1, 1, 1, 1, 1, 1, 1, 1, 1])     # disconnected: mush, no wall
        if self.mode == "weapon":
            return effects.weapon(*self.weapon_fx)
        if self.mode == "simple_weapon":
            return effects.simple_weapon(*self.simple_fx)
        if self.mode == "hybrid" and raw >= self.cal.raw_at(int(self.weapon_fx[0])) - 6:
            return effects.weapon(*self.weapon_fx)
        zones = list(self.curve)
        if self.mode == "hybrid":
            zones = [z if i < int(self.weapon_fx[0]) else 0 for i, z in enumerate(zones)]
        return effects.multi_feedback(self._texture(zones, raw, now))

    def _texture(self, zones: list[int], raw: int, now: float) -> list[int]:
        """Grit while the trigger moves and strength bumps (e.g. cylinder lock-up)."""
        z = self._zone(raw)
        for bz, until in list(self.bumps.items()):
            if now < until and zones[bz] > 0:
                zones[bz] = min(8, zones[bz] + 2)
            elif now >= until:
                del self.bumps[bz]
        if self.grit > 0 and zones[z] > 0 and abs(self.vel) > 120:
            if now >= self.grit_until:
                step = max(1, round(self.grit * 2))
                self.grit_zone = (z, random.choice((-step, 0, step)))
                self.grit_until = now + random.uniform(0.006, 0.014)
            gz, delta = self.grit_zone
            if gz == z:
                zones[z] = max(1, min(8, zones[z] + delta))
        return zones

    def _stop_block(self, base: Optional[list[int]] = None) -> bytes:
        zones = list(base) if base else [0] * ZONES
        if self.stop_zone:
            for i in range(self.stop_zone, ZONES):
                zones[i] = max(zones[i], self.stop_strength)
        return effects.multi_feedback(zones)

    def _crossed(self, table: dict, raw: int, frame: Frame, now: float) -> None:
        z_prev, z_now = self._zone(self.prev_raw), self._zone(raw)
        for z in range(z_prev + 1, z_now + 1):
            tick = table.get(z)
            if tick:
                self._play(frame, tick.get("haptic"), float(tick.get("gain", 1.0)))
                if tick.get("bump", True):
                    self.bumps[z] = now + 0.015

    def hint(self) -> str:
        st, a = self.state, self.action.get("type", "none")
        if self.kind == "tool":
            return "No trigger effects for this item."
        if self.kind == "melee":
            last = f"   ·   last: {self.last_strike.upper()}" if self.last_strike else ""
            target = "locked on - strikes land" if self.l2 >= AIM_RAW else "no target - you swing at air"
            return f"R1 strike · hold L2 to lock on ({target}){last}"
        if st == "reloading":
            return f"Reloading... {self.reload_ticks_done}/{self.reload_rounds}"
        if st == "action":
            return {"hammer": "Tap R2 to cock the hammer" + (" (or keep tapping to fan)" if self.action.get("fan") else ""),
                    "lever": "Tap R2 to work the lever", "bolt": "Tap R2 to work the bolt",
                    "pump": "Tap R2 to rack the pump"}.get(a, "Tap R2 to cycle")
        if st == "cycling":
            return "Release R2 to close the action"
        if st == "held":
            return "Release R2 to reset the trigger"
        if st == "draw":
            return f"Drawing {min(1.0, (self.prev_t - self.draw_t) / (float(self.bow.get('draw_ms', 900)) / 1000)):.0%} - release R2 to loose"
        if st == "flying":
            return "Throwing..."
        if st == "tethered":
            return "Caught! Hold R2 to pull, ○ to let go"
        if st == "firing":
            return "Firing - release to stop"
        if self.clip == 0 and not self.set.infinite_ammo:
            return "Empty - pull R2 or press □ to reload"
        if self.kind == "bow":
            return "Hold R2 to draw"
        if self.kind in ("throw", "tension"):
            return "Pull R2 to throw"
        return "Squeeze R2 to fire"

    # ---------- main ----------
    def update(self, s: InputState) -> Frame:
        now, raw = s.t, s.r2
        self.l2 = s.l2
        dt = now - self.prev_t
        if 0 < dt < 0.1:
            self.vel = 0.5 * self.vel + 0.5 * (raw - self.prev_raw) / dt
        self.history.append((now, raw))
        frame = Frame(out=OutputState(l2=self.aim_block))
        pressed = s.buttons & ~self.prev_buttons
        if pressed & SQUARE and self.clip_size and (self.clip or 0) < self.clip_size \
                and self.state in ("ready", "held"):
            self._start_reload(now)

        if self.kind == "bow":
            block = self._update_bow(raw, now, frame)
        elif self.kind == "auto":
            block = self._update_auto(raw, now, frame)
        elif self.kind == "melee":
            block = self._update_melee(pressed, now, frame)
        elif self.kind == "tension":
            block = self._update_tension(raw, pressed, now, frame)
        elif self.kind == "tool":
            block = effects.off()
        else:
            block = self._update_gun(raw, now, frame)
        frame.out.r2 = block

        if self.set.dead_eye and now >= self.next_heartbeat:
            self.next_heartbeat = now + 0.85
            frame.haptics.append(Cue("heartbeat", 0.8))
        for t in [t for t in self.timers if t[0] <= now]:
            frame.haptics.append(t[1])
            self.timers.remove(t)
        self._analyse(now, frame)
        flash = 0 <= now - self.shot_t < 0.06 and self.kind not in ("melee", "tool")
        if self.kind == "melee" and 0 <= now - self.shot_t < 0.15:
            frame.out.lightbar = {"hit": (255, 120, 0), "finisher": (255, 30, 0), "blocked": (90, 90, 90)}.get(
                self.last_strike, (20, 20, 60))
        key = "flash" if flash else ("empty" if self.state == "ready" and self.clip == 0 else self.state)
        if frame.out.lightbar is None:
            frame.out.lightbar = self.LIGHT.get(key, (0, 0, 0))
        frame.game_rt = self.game_rt
        frame.state = self.state
        self.prev_raw, self.prev_t, self.prev_buttons = raw, now, s.buttons
        return frame

    # ---------- guns & throwables ----------
    def _update_gun(self, raw: int, now: float, frame: Frame) -> bytes:
        st = self.state
        if st == "ready":
            self._crossed(self.ticks, raw, frame, now)
            if self.p.get("pre") and self._zone(self.prev_raw) < 2 <= self._zone(raw):
                self._play(frame, self.p["pre"])
            if raw >= self.break_raw:
                return self._shoot(raw, now, frame)
            return self._fire_block(raw, now)

        if st == "held":
            if raw <= self.reset_raw:
                self.game_rt = 0
            kick_dt = now - self.kick_t
            if not self.last_dry and kick_dt < self.kick.duration:
                # before the kick starts (lock time) the trigger rests on its overtravel stop
                return self.kick.block(kick_dt) or self._stop_block()
            if now - self.shot_t >= self.rate_s and raw <= self.reset_raw:
                if self.last_dry and self.set.auto_reload and self.clip_size and not self.set.infinite_ammo:
                    self._start_reload(now)
                    return effects.off()
                if self.action.get("type", "none") not in ("none", "semi") and self.set.manual_action \
                        and self.clip != 0:
                    self.state = "action"
                    return effects.multi_feedback(self.action_curve)
                self.state = "ready"
                if self.p.get("fire", {}).get("reset_click", True) and not self.last_dry:
                    self._play(frame, "reset_click")
                return self._fire_block(raw, now)
            return self._stop_block(self.after_curve)

        if st == "action":                         # manual cocking / cycling press
            self._crossed(self.action_ticks, raw, frame, now)
            if raw >= self.action_break_raw:
                fan = (self.action.get("fan") and self.set.fanning and self.l2 < AIM_RAW
                       and now - self.shot_t < 0.9 * (1.7 if self.set.dead_eye else 1.0))
                if fan:                            # palm slaps the hammer: cock and fire in one stroke
                    self.fanned = True
                    self._play(frame, "hammer_cock_auto", 0.7)
                    return self._shoot(raw, now, frame, fanned=True)
                self._schedule(now, self.action.get("open"))
                frame.events.append({"type": "action", "t": now})
                self.state, self.action_t, self.game_rt = "cycling", now, 255
                return effects.off()
            return effects.multi_feedback(self.action_curve)

        if st == "cycling":
            if raw <= self.reset_raw and now - self.action_t >= float(self.action.get("min_ms", 120)) / 1000:
                self._schedule(now, self.action.get("close"))
                self.state, self.game_rt = "ready", 0
                return self._fire_block(raw, now)
            return effects.off()

        if st == "reloading":
            return self._update_reload(now, frame)
        return effects.off()

    def _shoot(self, raw: int, now: float, frame: Frame, fanned: bool = False) -> bytes:
        empty = self.clip == 0 and not self.set.infinite_ammo
        self.state, self.shot_t, self.game_rt = "held", now, 255
        self.kick_t = now + max(self.lock_s, self.set.audio_latency_ms / 1000)
        self.last_dry = empty
        if empty:
            if self.empty_feel == "click":
                self._play(frame, self.p.get("dry", "dry_fire"))
            frame.events.append({"type": "dry", "t": now, "raw": raw})
            return self._stop_block()
        if self.clip is not None and not self.set.infinite_ammo:
            self.clip -= 1
        self.shots += 1
        variant = None
        if self.kick_variants:
            variant = random.randrange(len(self.kick_variants))
            self.kick.shaped(self.kick_variants[variant])
        self._schedule(now + self.lock_s, self.shot_haptic, self.haptic_gain, variant)
        if not self.set.manual_action or self.action.get("type") == "semi":
            self._schedule(now + float(self.action.get("auto_ms", 200)) / 1000, self.action.get("auto"))
        if self.kind == "throw" and self.p.get("explode"):
            ex = self.p["explode"]
            self._schedule(now + float(ex.get("after_ms", 2500)) / 1000 * (1.7 if self.set.dead_eye else 1),
                           ex.get("haptic", "explosion_far"), float(ex.get("gain", 1.0)))
        ev = {"type": "shot", "t": now, "raw": raw, "break_raw": self.break_raw, "n": self.shots,
              "vel": round(self.vel), "fanned": fanned}
        frame.events.append(ev)
        if not fanned:
            self.pending.append(ev)
        return self._stop_block()

    def _start_reload(self, now: float) -> None:
        if not self.clip_size or self.set.infinite_ammo:
            return
        self.state, self.reload_t, self.game_rt = "reloading", now, 0
        self.reload_ticks_done = 0
        per_round = self.reload.get("per_round", False)
        self.reload_rounds = (self.clip_size - (self.clip or 0)) if per_round else 1
        self.last_dry = False
        self._schedule(now, self.reload.get("begin"))

    def _update_reload(self, now: float, frame: Frame) -> bytes:
        r = self.reload
        slow = 1.7 if self.set.dead_eye else 1.0
        tick_s = float(r.get("tick_ms", 400)) / 1000 * slow
        start_s = float(r.get("start_ms", 300)) / 1000 * slow
        el = now - self.reload_t
        due = 0 if el < start_s else min(self.reload_rounds, int((el - start_s) / tick_s) + 1)
        while self.reload_ticks_done < due:
            self.reload_ticks_done += 1
            self._play(frame, r.get("tick", "reload_round"))
        done_at = start_s + self.reload_rounds * tick_s + float(r.get("end_ms", 250)) / 1000 * slow
        if el >= done_at:
            self.clip = self.clip_size
            self._play(frame, r.get("end"))
            self.state = "ready"
        return effects.off()

    # ---------- automatic (mounted Gatling / Maxim) ----------
    def _update_auto(self, raw: int, now: float, frame: Frame) -> bytes:
        interval = 60.0 / float(self.p.get("rpm", 400)) / self.speed
        if self.state == "ready":
            if raw >= self.break_raw:
                self.state, self.shot_t, self.game_rt = "firing", now - interval, 255
            else:
                return self._fire_block(raw, now)
        if self.state == "firing":
            if raw <= self.reset_raw:
                self.state, self.game_rt = "ready", 0
                return self._fire_block(raw, now)
            if now - self.shot_t >= interval:
                self.shot_t = now
                self.shots += 1
                self._schedule(now, self.shot_haptic)
                frame.events.append({"type": "shot", "t": now, "raw": raw, "n": self.shots})
            amp = self.kick.steps[0] if self.kick.steps else 6
            return effects.vibration(0, amp, max(1, round(1 / interval)))
        return effects.off()

    # ---------- bow: tension builds over time, release fires ----------
    def _update_bow(self, raw: int, now: float, frame: Frame) -> bytes:
        b = self.bow
        start_raw = self.cal.raw_at(int(b.get("start_zone", 2)))
        pos = int(b.get("position", 1))
        draw_s = float(b.get("draw_ms", 900)) / 1000 / self.speed
        if self.state == "ready":
            if raw >= start_raw:
                self.state, self.draw_t, self.game_rt = "draw", now, 255
                self._play(frame, b.get("creak"))
            else:
                return effects.feedback(pos, int(b.get("rest_strength", 1)))
        if self.state == "draw":
            p = min(1.0, (now - self.draw_t) / draw_s)
            if raw < start_raw - 8:                      # released
                self.game_rt = 0
                self.state, self.shot_t = "held", now
                self.last_dry = False
                if p >= float(b.get("min_draw", 0.35)):
                    self.shots += 1
                    self._play(frame, self.shot_haptic or "bow_release", 0.35 + 0.65 * p)
                    frame.events.append({"type": "shot", "t": now, "raw": raw, "n": self.shots,
                                         "draw": round(p, 2)})
                    self.kick_t = now + self.set.audio_latency_ms / 1000
                    self._schedule(now + self.rate_s * 0.7, b.get("nock", "bow_nock"))
                else:
                    self._play(frame, "bow_letdown")
                    self.kick_t = -10
                return effects.off()
            eased = 1 - (1 - p) ** 2                     # draw weight builds fast, then stacks
            lo, hi = int(b.get("strength_from", 2)), int(b.get("strength_to", 7))
            strength = lo + (hi - lo) * eased
            hold = now - self.draw_t - draw_s - float(b.get("tremor_after_ms", 2500)) / 1000
            if hold > 0:                                 # fatigue: tension wavers, growing over 2 s
                depth = float(b.get("tremor_depth", 2)) * min(1.0, hold / 2.0)
                hz = float(b.get("tremor_hz", 9))
                strength += depth * math.sin(2 * math.pi * hz * now) + random.uniform(-0.4, 0.4) * depth
            return effects.feedback(pos, max(1, min(8, round(strength))))
        if self.state == "held":
            if now - self.kick_t < self.kick.duration:
                return self.kick.block(now - self.kick_t) or effects.off()
            if now - self.shot_t >= self.rate_s and raw < start_raw:
                self.state = "ready"
            return effects.off()
        return effects.off()

    # ---------- melee: R1 strikes; locked on (L2) = a target in reach ----------
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
        return effects.off()

    # ---------- lasso / fishing: a live pull on the line ----------
    def _update_tension(self, raw: int, pressed: int, now: float, frame: Frame) -> bytes:
        tn = self.tension
        if self.state == "ready":
            if raw >= self.break_raw:
                self.state, self.shot_t, self.game_rt = "flying", now, 255
                self.shots += 1
                self._play(frame, self.shot_haptic)
                frame.events.append({"type": "throw", "t": now, "n": self.shots})
                return effects.off()
            return self._fire_block(raw, now)
        if self.state == "flying":
            if raw <= self.reset_raw:
                self.game_rt = 0
            if now - self.shot_t >= float(tn.get("catch_ms", 500)) / 1000 / self.speed:
                self.state, self.tether_t = "tethered", now
                self._play(frame, tn.get("catch"))
                lo, hi = tn.get("jerk_every_ms", [600, 1800])
                self.next_jerk = now + random.uniform(lo, hi) / 1000
            return effects.off()
        if self.state == "tethered":
            self.game_rt = 255 if raw >= self.break_raw else 0
            if pressed & CIRCLE or now - self.tether_t > float(tn.get("hold_s", 12)):
                self.state, self.game_rt = "ready", 0
                return effects.off()
            # the catch struggles: smooth random pull plus sudden jerks
            t = now * 1.3 + self.noise_phase
            pull = 0.5 + 0.25 * math.sin(t) + 0.15 * math.sin(2.7 * t + 1) + 0.1 * math.sin(6.1 * t + 2)
            strength = float(tn.get("base", 3)) + float(tn.get("range", 4)) * pull
            if raw >= self.break_raw:
                strength += 1                            # you pull back: the rope fights harder
            if now >= self.next_jerk:
                lo, hi = tn.get("jerk_every_ms", [600, 1800])
                self.next_jerk = now + random.uniform(lo, hi) / 1000
                self.jerk_until = now + 0.07
                self._play(frame, tn.get("jerk"))
            if now < self.jerk_until:
                strength = 8
            return effects.feedback(1, max(1, min(8, round(strength))))
        return effects.off()

    # ---------- snap analysis: did we fire where the trigger physically broke? ----------
    def _analyse(self, now: float, frame: Frame) -> None:
        for ev in list(self.pending):
            if now - ev["t"] < 0.06:
                continue
            self.pending.remove(ev)
            pts = [(t, r) for t, r in self.history if ev["t"] - 0.05 <= t <= ev["t"] + 0.06]
            if len(pts) < 3:
                continue
            # The physical break shows up as the fastest jump in position - but only
            # if it clearly stands out from the rest of the pull (a real snap, not a fast squeeze).
            best_v, jump, speeds = 0.0, None, []
            for (t0, r0), (t1, r1) in zip(pts, pts[1:]):
                v = (r1 - r0) / max(1e-4, t1 - t0)
                speeds.append(abs(v))
                if v > best_v:
                    best_v, jump = v, (t1, r0, r1)
            speeds.sort()
            typical = speeds[len(speeds) // 2]
            if jump is None or best_v < 1500 or best_v < 3 * typical:
                frame.events.append({"type": "analysis", "n": ev["n"], "fire_raw": ev["raw"],
                                     "threshold": ev["break_raw"], "snap": False, "peak_vel": round(best_v)})
                continue
            t1, r0, r1 = jump
            # dt_ms: when we fired relative to the sample where the trigger jumped.
            # ~0 = shot on the snap; strongly negative = fired inside the wall (threshold too low).
            frame.events.append({"type": "analysis", "n": ev["n"], "fire_raw": ev["raw"],
                                 "threshold": ev["break_raw"], "snap": True, "snap_from": r0, "snap_to": r1,
                                 "dt_ms": round((ev["t"] - t1) * 1000, 1), "peak_vel": round(best_v)})
