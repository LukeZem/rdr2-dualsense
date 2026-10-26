"""DualSense adaptive trigger effect encoders.

Every function returns the 11-byte trigger block of the output report
(mode byte + 10 parameter bytes).

Zone-based modes split the trigger travel into 10 zones (0 = at rest,
9 = fully pressed). Zone strengths/amplitudes are 1-8 (0 = no force in
that zone). Byte layouts follow Nielk1's TriggerEffectGenerator, which
documents Sony's factory effects.

This module is intentionally dependency free: it is the reference the
C++ mod's encoder is ported from and tested against.
"""
from __future__ import annotations

from enum import IntEnum
from typing import Sequence

BLOCK_SIZE = 11
ZONES = 10


class Mode(IntEnum):
    OFF = 0x05
    FEEDBACK = 0x21
    BOW = 0x22
    GALLOPING = 0x23
    WEAPON = 0x25
    VIBRATION = 0x26
    MACHINE = 0x27
    # Older firmware effects with raw 0-255 positions. Still accepted by
    # current firmware but undocumented by Sony - the lab treats them as
    # experimental.
    SIMPLE_FEEDBACK = 0x01
    SIMPLE_WEAPON = 0x02
    SIMPLE_VIBRATION = 0x06
    LIMITED_FEEDBACK = 0x11
    LIMITED_WEAPON = 0x12


def _block(mode: int, *params: int) -> bytes:
    b = bytearray(BLOCK_SIZE)
    b[0] = mode
    for i, p in enumerate(params):
        b[1 + i] = p & 0xFF
    return bytes(b)


def _check(name: str, value: int, lo: int, hi: int) -> None:
    if not lo <= value <= hi:
        raise ValueError(f"{name}={value} out of range {lo}..{hi}")


def _zone_pack(values: Sequence[int]) -> tuple[int, int]:
    """Pack 10 per-zone values (0-8) into (active zone mask, 3-bit value field)."""
    if len(values) != ZONES:
        raise ValueError(f"need {ZONES} zone values, got {len(values)}")
    active = 0
    packed = 0
    for i, v in enumerate(values):
        _check(f"zone[{i}]", v, 0, 8)
        if v > 0:
            active |= 1 << i
            packed |= ((v - 1) & 0x07) << (3 * i)
    return active, packed


def off() -> bytes:
    return _block(Mode.OFF)


def multi_feedback(strengths: Sequence[int]) -> bytes:
    """Resistance per zone (0-8). The building block for custom pull curves."""
    active, packed = _zone_pack(strengths)
    if not active:
        return off()
    return _block(Mode.FEEDBACK, active, active >> 8, *packed.to_bytes(4, "little"))


def feedback(position: int, strength: int) -> bytes:
    """Constant resistance from zone `position` (0-9) to the end, strength 1-8."""
    _check("position", position, 0, 9)
    _check("strength", strength, 0, 8)
    return multi_feedback([0] * position + [strength] * (ZONES - position))


def slope_feedback(start: int, end: int, start_strength: int, end_strength: int) -> bytes:
    """Resistance ramping linearly from start to end zone, then held to zone 9."""
    _check("start", start, 0, 8)
    _check("end", end, start + 1, 9)
    _check("start_strength", start_strength, 1, 8)
    _check("end_strength", end_strength, 1, 8)
    slope = (end_strength - start_strength) / (end - start)
    zones = [0] * ZONES
    for i in range(start, ZONES):
        zones[i] = round(start_strength + slope * (i - start)) if i <= end else end_strength
    return multi_feedback(zones)


def weapon(start: int, end: int, strength: int) -> bytes:
    """Sony's gun trigger: resistance between start and end zone, then a snap."""
    _check("start", start, 2, 7)
    _check("end", end, start + 1, 8)
    _check("strength", strength, 0, 8)
    if strength == 0:
        return off()
    zones = (1 << start) | (1 << end)
    return _block(Mode.WEAPON, zones, zones >> 8, strength - 1)


def bow(start: int, end: int, strength: int, snap_force: int) -> bytes:
    """Resistance between start and end, then the trigger is pushed back (snap)."""
    _check("start", start, 0, 8)
    _check("end", end, start + 1, 8)
    _check("strength", strength, 0, 8)
    _check("snap_force", snap_force, 0, 8)
    if strength == 0 or snap_force == 0:
        return off()
    zones = (1 << start) | (1 << end)
    forces = ((strength - 1) & 0x07) | (((snap_force - 1) & 0x07) << 3)
    return _block(Mode.BOW, zones, zones >> 8, forces, forces >> 8)


def galloping(start: int, end: int, first_foot: int, second_foot: int, frequency: int) -> bytes:
    """Two-beat 'hoof' pulse between start and end zone. frequency in Hz."""
    _check("start", start, 0, 8)
    _check("end", end, start + 1, 9)
    _check("first_foot", first_foot, 0, 6)
    _check("second_foot", second_foot, first_foot + 1, 7)
    _check("frequency", frequency, 0, 255)
    if frequency == 0:
        return off()
    zones = (1 << start) | (1 << end)
    ratio = (second_foot & 0x07) | ((first_foot & 0x07) << 3)
    return _block(Mode.GALLOPING, zones, zones >> 8, ratio, frequency)


def multi_vibration(frequency: int, amplitudes: Sequence[int]) -> bytes:
    """Vibration per zone (amplitude 0-8) at `frequency` Hz."""
    _check("frequency", frequency, 0, 255)
    active, packed = _zone_pack(amplitudes)
    if not active or frequency == 0:
        return off()
    return _block(Mode.VIBRATION, active, active >> 8, *packed.to_bytes(4, "little"), 0, 0, frequency)


def vibration(position: int, amplitude: int, frequency: int) -> bytes:
    """Vibration from zone `position` to the end."""
    _check("position", position, 0, 9)
    _check("amplitude", amplitude, 0, 8)
    return multi_vibration(frequency, [0] * position + [amplitude] * (ZONES - position))


def machine(start: int, end: int, amp_a: int, amp_b: int, frequency: int, period: int) -> bytes:
    """Vibration alternating between amplitude A and B every `period` (x0.1 s)."""
    _check("start", start, 0, 8)
    _check("end", end, start + 1, 9)
    _check("amp_a", amp_a, 0, 7)
    _check("amp_b", amp_b, 0, 7)
    _check("frequency", frequency, 0, 255)
    _check("period", period, 0, 255)
    if frequency == 0:
        return off()
    zones = (1 << start) | (1 << end)
    amps = (amp_a & 0x07) | ((amp_b & 0x07) << 3)
    return _block(Mode.MACHINE, zones, zones >> 8, amps, frequency, period)


# --- Experimental raw-position effects (0-255 resolution instead of 10 zones) ---

def simple_feedback(position: int, strength: int) -> bytes:
    _check("position", position, 0, 255)
    _check("strength", strength, 0, 255)
    return _block(Mode.SIMPLE_FEEDBACK, position, strength)


def simple_weapon(start: int, end: int, strength: int) -> bytes:
    _check("start", start, 0, 255)
    _check("end", end, 0, 255)
    _check("strength", strength, 0, 255)
    return _block(Mode.SIMPLE_WEAPON, start, end, strength)


def simple_vibration(frequency: int, amplitude: int, position: int) -> bytes:
    _check("frequency", frequency, 0, 255)
    _check("amplitude", amplitude, 0, 255)
    _check("position", position, 0, 255)
    return _block(Mode.SIMPLE_VIBRATION, frequency, amplitude, position)


def limited_feedback(position: int, strength: int) -> bytes:
    _check("position", position, 0, 255)
    _check("strength", strength, 0, 10)
    return _block(Mode.LIMITED_FEEDBACK, position, strength)


def limited_weapon(start: int, end: int, strength: int) -> bytes:
    _check("start", start, 0x10, 255)
    _check("end", end, start, min(255, start + 100))
    _check("strength", strength, 0, 10)
    return _block(Mode.LIMITED_WEAPON, start, end, strength)


def raw(block: Sequence[int]) -> bytes:
    """Send an arbitrary 11-byte block (for reverse-engineering)."""
    if len(block) != BLOCK_SIZE:
        raise ValueError(f"raw block needs {BLOCK_SIZE} bytes")
    return bytes(b & 0xFF for b in block)


# Parameter specs used by the lab UI to build sliders: (name, lo, hi, default).
PARAMS: dict[str, tuple[callable, list[tuple[str, int, int, int]]]] = {
    "Off": (off, []),
    "Feedback": (feedback, [("position", 0, 9, 3), ("strength", 0, 8, 5)]),
    "Slope Feedback": (slope_feedback, [("start", 0, 8, 1), ("end", 1, 9, 8),
                                        ("start_strength", 1, 8, 1), ("end_strength", 1, 8, 8)]),
    "Weapon": (weapon, [("start", 2, 7, 4), ("end", 3, 8, 6), ("strength", 0, 8, 6)]),
    "Bow": (bow, [("start", 0, 8, 1), ("end", 1, 8, 7), ("strength", 0, 8, 6), ("snap_force", 0, 8, 6)]),
    "Galloping": (galloping, [("start", 0, 8, 0), ("end", 1, 9, 9), ("first_foot", 0, 6, 4),
                              ("second_foot", 1, 7, 7), ("frequency", 0, 255, 3)]),
    "Vibration": (vibration, [("position", 0, 9, 0), ("amplitude", 0, 8, 6), ("frequency", 0, 255, 40)]),
    "Machine": (machine, [("start", 0, 8, 1), ("end", 1, 9, 9), ("amp_a", 0, 7, 2), ("amp_b", 0, 7, 7),
                          ("frequency", 0, 255, 10), ("period", 0, 255, 2)]),
    "Simple Feedback (exp)": (simple_feedback, [("position", 0, 255, 80), ("strength", 0, 255, 160)]),
    "Simple Weapon (exp)": (simple_weapon, [("start", 0, 255, 100), ("end", 0, 255, 160), ("strength", 0, 255, 200)]),
    "Simple Vibration (exp)": (simple_vibration, [("frequency", 0, 255, 40), ("amplitude", 0, 255, 200),
                                                  ("position", 0, 255, 0)]),
    "Limited Feedback (exp)": (limited_feedback, [("position", 0, 255, 80), ("strength", 0, 10, 6)]),
    "Limited Weapon (exp)": (limited_weapon, [("start", 16, 255, 100), ("end", 16, 255, 160), ("strength", 0, 10, 8)]),
}

# Modes edited with the 10-zone editor instead of sliders: name -> (fn, extra params).
ZONE_MODES: dict[str, tuple[callable, list[tuple[str, int, int, int]]]] = {
    "Zone Feedback (custom curve)": (lambda zones: multi_feedback(zones), []),
    "Zone Vibration (custom curve)": (lambda zones, frequency: multi_vibration(frequency, zones),
                                      [("frequency", 1, 255, 40)]),
}


def zone_view(block: bytes) -> tuple[str, list[int]]:
    """Decode a block into (kind, per-zone strength 0-8) for display.
    kind: 'resist', 'snap' (weapon/bow region), 'vibrate', or 'other'."""
    mode = block[0]
    zones = [0] * ZONES
    if mode in (Mode.FEEDBACK, Mode.VIBRATION):
        active = block[1] | (block[2] << 8)
        packed = int.from_bytes(block[3:7], "little")
        for i in range(ZONES):
            if active & (1 << i):
                zones[i] = ((packed >> (3 * i)) & 0x07) + 1
        return ("resist" if mode == Mode.FEEDBACK else "vibrate"), zones
    if mode in (Mode.WEAPON, Mode.BOW, Mode.GALLOPING, Mode.MACHINE):
        mask = block[1] | (block[2] << 8)
        bits = [i for i in range(ZONES) if mask & (1 << i)]
        if len(bits) == 2:
            level = (block[3] & 0x07) + 1 if mode in (Mode.WEAPON, Mode.BOW) else 4
            for i in range(bits[0], bits[1]):
                zones[i] = level
        return ("snap" if mode in (Mode.WEAPON, Mode.BOW) else "vibrate"), zones
    return "other", zones


def describe(block: bytes) -> str:
    try:
        name = Mode(block[0]).name
    except ValueError:
        name = f"0x{block[0]:02X}"
    return f"{name:<16} " + " ".join(f"{b:02X}" for b in block)
