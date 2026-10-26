"""Zone calibration: where does each of the 10 effect zones start on this controller?

For zone k a full-strength wall is placed from zone k on. The user pulls gently
until the wall stops the trigger and holds still; the resting raw value is the
start of zone k. On capture the wall disappears - the user feels it give way,
releases, and the next zone follows. The table makes the shot threshold exact
instead of assuming the zones are spread linearly over 0-255.
"""
from __future__ import annotations

from collections import deque
from statistics import median

from ds5 import effects
from ds5.device import InputState, OutputState
from .engine import Frame, ZONES

STABLE_SECONDS = 0.3
STABLE_RANGE = 3
PRESS_RAW = 4


class Calibrator:
    def __init__(self, trigger: str = "r2") -> None:
        self.trigger = trigger
        self.zone = 1
        self.table = [0] * ZONES
        self.phase = "release"
        self.window: deque = deque()
        self.done = False
        self.message = "Release the trigger completely."

    def _out(self, block: bytes) -> OutputState:
        return OutputState(r2=block) if self.trigger == "r2" else OutputState(l2=block)

    def update(self, s: InputState) -> Frame:
        raw = s.r2 if self.trigger == "r2" else s.l2
        name = self.trigger.upper()
        wall = effects.feedback(self.zone, 8) if not self.done else effects.off()
        events = []

        if self.done:
            return Frame(out=self._out(effects.off()), state="calibrated")

        if self.phase == "release":
            if raw < PRESS_RAW:
                self.phase = "press"
                self.message = f"Zone {self.zone}/9: pull {name} GENTLY until it stops at the wall, then hold still."
        elif self.phase == "press":
            if raw >= PRESS_RAW:
                self.phase, self.window = "hold", deque()
        elif self.phase == "hold":
            self.window.append((s.t, raw))
            while self.window and s.t - self.window[0][0] > STABLE_SECONDS:
                self.window.popleft()
            values = [r for _, r in self.window]
            if raw < PRESS_RAW:
                self.phase = "press"
            elif (self.window and s.t - self.window[0][0] >= STABLE_SECONDS * 0.95
                  and max(values) - min(values) <= STABLE_RANGE):
                self.table[self.zone] = int(median(values))
                events.append({"type": "calibrated_zone", "trigger": self.trigger, "zone": self.zone,
                               "raw": self.table[self.zone]})
                self.phase = "captured"
                self.message = f"Zone {self.zone} = {self.table[self.zone]}. The wall is gone - release {name}."
        if self.phase == "captured":
            wall = effects.off()
            if raw < PRESS_RAW:
                self.zone += 1
                if self.zone >= ZONES:
                    self.done = True
                    self._finish(events)
                    return Frame(out=self._out(effects.off()), events=events, state="calibrated")
                self.phase = "press"
                self.message = f"Zone {self.zone}/9: pull {name} GENTLY until it stops at the wall, then hold still."
        return Frame(out=self._out(wall), events=events, state=f"calibrating {self.zone}")

    def _finish(self, events: list) -> None:
        bad = [i for i in range(1, ZONES) if self.table[i] <= self.table[i - 1]]
        if bad:
            self.message = (f"Done, but zones {bad} are not increasing - you probably pushed through a wall. "
                            "Run it again with lighter pressure.")
        else:
            self.message = "Done. Calibration saved."
        events.append({"type": "calibration_done", "trigger": self.trigger, "table": list(self.table),
                       "ok": not bad})
