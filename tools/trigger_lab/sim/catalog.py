"""Weapon catalog: classes (shared mechanism behaviour) + every in-game weapon.

A weapon's profile = deep_merge(class, weapon fields, weapon["tune"]). The game
identifies weapons by joaat(internal name); unknown hashes fall back to the
weapon group in the mod.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Optional

from gameaudio.awc import joaat

CATEGORY_ORDER = ["Revolvers", "Pistols", "Repeaters", "Rifles", "Sniper Rifles", "Shotguns", "Bows",
                  "Throwables", "Melee", "Tools", "Mounted"]
_META = ("name", "label", "category", "class", "bank", "verified", "notes", "tune")


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def dumps(obj) -> str:
    """JSON with lists of scalars kept on one line (readable zone curves)."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    return re.sub(r"\[\s*([-\d.,\s\"a-z_]*?)\s*\]",
                  lambda m: "[" + ", ".join(x.strip() for x in m.group(1).split(",")) + "]"
                  if "\n" in m.group(0) else m.group(0), text)


class Catalog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.reload()

    def reload(self) -> None:
        self.raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.classes: dict = self.raw["classes"]
        self.weapons: list[dict] = self.raw["weapons"]
        for w in self.weapons:
            if w["class"] not in self.classes:
                raise ValueError(f"{w['name']}: unknown class {w['class']!r}")

    def categories(self) -> list[str]:
        cats = {w["category"] for w in self.weapons}
        return [c for c in CATEGORY_ORDER if c in cats] + sorted(cats - set(CATEGORY_ORDER))

    def in_category(self, category: str) -> list[dict]:
        return [w for w in self.weapons if w["category"] == category]

    def get(self, name: str) -> Optional[dict]:
        return next((w for w in self.weapons if w["name"] == name), None)

    def resolve(self, name: str) -> dict:
        w = self.get(name)
        if w is None:
            raise KeyError(name)
        prof = deep_merge(self.classes[w["class"]], {k: v for k, v in w.items() if k not in ("tune",)})
        prof = deep_merge(prof, w.get("tune", {}))
        prof["id"] = w["name"]
        prof["hash"] = f"0x{joaat(w['name']):08X}"
        prof["examples"] = w.get("label", w["name"])
        prof.setdefault("notes", "")
        return prof

    def save_tune(self, name: str, tune: dict) -> None:
        """Store per-weapon overrides (merged into the existing tune) and rewrite the file."""
        w = self.get(name)
        w["tune"] = deep_merge(w.get("tune", {}), tune)
        self.path.write_text(dumps(self.raw) + "\n", encoding="utf-8")
