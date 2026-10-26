"""Adds footstep / landing / climbing / door recipes and the hoof surfaces the world module reports."""
import json
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "trigger_lab" / "data" / "haptics.json"
s = p.read_text(encoding="utf-8").rstrip()
assert s.endswith("}")

new = '''
  "step_ground": {"_doc": "boot heel on packed earth: short soft thud", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 62, "to_hz": 48, "attack_ms": 2, "decay_ms": 16, "amp": 0.8},
    {"type": "noise", "lo": 60, "hi": 170, "decay_ms": 12, "amp": 0.25}
  ]},
  "step_grass": {"_doc": "grass: softer, a brush of blades", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 56, "to_hz": 44, "attack_ms": 4, "decay_ms": 15, "amp": 0.6},
    {"type": "noise", "lo": 110, "hi": 280, "attack_ms": 8, "decay_ms": 22, "amp": 0.22}
  ]},
  "step_mud": {"_doc": "mud: the boot sinks, no heel click, a slow suck", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 46, "to_hz": 36, "attack_ms": 10, "decay_ms": 30, "amp": 0.7},
    {"type": "noise", "lo": 40, "hi": 120, "delay_ms": 25, "attack_ms": 20, "decay_ms": 40, "amp": 0.22}
  ]},
  "step_stone": {"_doc": "rock / cobbles: hard heel click", "gain": 1.0, "layers": [
    {"type": "click", "hz": 260, "cycles": 1, "amp": 0.75},
    {"type": "tone", "hz": 75, "to_hz": 58, "decay_ms": 10, "amp": 0.5}
  ]},
  "step_gravel": {"_doc": "gravel: crunch with a little rattle", "gain": 1.0, "layers": [
    {"type": "click", "hz": 220, "cycles": 1, "amp": 0.4},
    {"type": "noise", "lo": 140, "hi": 380, "attack_ms": 3, "decay_ms": 26, "amp": 0.45},
    {"type": "tone", "hz": 60, "decay_ms": 12, "amp": 0.4}
  ]},
  "step_wood": {"_doc": "floorboards / boardwalk: hollow knock that rings a moment", "gain": 1.0, "layers": [
    {"type": "click", "hz": 190, "cycles": 1, "amp": 0.65},
    {"type": "tone", "hz": 98, "to_hz": 90, "decay_ms": 32, "amp": 0.5}
  ]},
  "step_snow": {"_doc": "snow: muffled crunch, packing down", "gain": 1.0, "layers": [
    {"type": "noise", "lo": 90, "hi": 260, "attack_ms": 12, "decay_ms": 28, "amp": 0.45},
    {"type": "tone", "hz": 52, "attack_ms": 6, "decay_ms": 18, "amp": 0.4}
  ]},
  "step_sand": {"gain": 1.0, "layers": [
    {"type": "noise", "lo": 60, "hi": 170, "attack_ms": 6, "decay_ms": 24, "amp": 0.4},
    {"type": "tone", "hz": 54, "decay_ms": 14, "amp": 0.45}
  ]},
  "step_water": {"_doc": "wading: a slow push and splash", "gain": 1.0, "layers": [
    {"type": "noise", "lo": 50, "hi": 200, "attack_ms": 18, "decay_ms": 55, "amp": 0.45},
    {"type": "tone", "hz": 44, "attack_ms": 12, "decay_ms": 40, "amp": 0.4}
  ]},
  "hoof_ground": {"gain": 1.0, "layers": [{"type": "ref", "name": "hoof_dirt"}]},
  "hoof_grass": {"gain": 0.85, "layers": [{"type": "ref", "name": "hoof_dirt"},
    {"type": "noise", "lo": 110, "hi": 280, "attack_ms": 8, "decay_ms": 22, "amp": 0.18}]},
  "hoof_gravel": {"gain": 1.0, "layers": [{"type": "ref", "name": "hoof_dirt"},
    {"type": "noise", "lo": 140, "hi": 380, "attack_ms": 3, "decay_ms": 26, "amp": 0.35}]},
  "land": {"_doc": "landing from a jump or drop: knees take it", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 50, "to_hz": 34, "attack_ms": 3, "decay_ms": 55, "amp": 1.0},
    {"type": "noise", "lo": 40, "hi": 140, "decay_ms": 35, "amp": 0.4}
  ]},
  "climb_grab": {"_doc": "hands grab the ledge, the body is hauled up", "gain": 1.0, "layers": [
    {"type": "click", "hz": 200, "cycles": 1, "amp": 0.5},
    {"type": "tone", "hz": 48, "to_hz": 40, "delay_ms": 60, "attack_ms": 80, "decay_ms": 90, "amp": 0.45}
  ]},
  "door_open": {"_doc": "latch, then the door swings", "gain": 1.0, "layers": [
    {"type": "click", "hz": 300, "cycles": 1, "amp": 0.45},
    {"type": "noise", "lo": 60, "hi": 160, "delay_ms": 40, "attack_ms": 60, "decay_ms": 90, "amp": 0.18}
  ]}
}
'''
s = s[:-1].rstrip() + ",\n" + new.lstrip("\n")
json.loads(s)
p.write_text(s, encoding="utf-8")
print("recipes added:", len(json.loads(s)), "keys")
