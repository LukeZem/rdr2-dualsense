"""The game's own sounds, organised for haptics.

Sources: every *.awc under <game>/lml/*/audio/sfx (sound mods such as RWS) plus any
extra folders (e.g. vanilla banks exported with CodeX). A bank is one .awc file;
WEAPONS_PLAYER/<bank>.awc wins over dlc_*/<bank>.awc copies.

Per bank the streams are de-duplicated (sound mods often put one recording into
several variation slots) and left/right halves of stereo recordings are paired,
so a bank becomes a short list of distinct sounds. Each sound gets a role:
your label from data/sound_labels.json if present, else an automatic guess.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from . import awc
from .features import features

# Slot ids present in every player weapon bank (same slot names, generic content).
SHARED_SLOT_IDS = {0x002683EB, 0x06CEA918, 0x0A888160, 0x0EB5B890, 0x0F3C0AF7, 0x1D24BDE6}
# Names recovered by hashing candidate names (ids are joaat(name) & 0x1FFFFFFF).
RECOVERED_NAMES = [f"revolver_draw{i}" for i in range(1, 6)] + [f"revolver_holster{i}" for i in range(1, 6)] \
    + [f"pistol_impact_{i:02d}" for i in range(1, 13)] + ["lasso_throw_01"]
KNOWN = {awc.joaat(n) & 0x1FFFFFFF: n for n in RECOVERED_NAMES}

WEAPON_PREFIXES = ("REV_", "PTL_", "RPT_", "RFL_", "SNP_", "SHT_")
ROLES = ["shot", "shot_far", "cock", "lever_open", "lever_close", "bolt_open", "bolt_close", "pump_back",
         "pump_forward", "reload", "shell", "dry_fire", "draw", "holster", "explosion", "impact", "other",
         "ignore", "shared", "unknown"]


def bank_kind(bank: str) -> str:
    if bank.startswith(WEAPON_PREFIXES):
        return "weapon"
    if bank == "EXPLOSIONS":
        return "explosions"
    if bank == "WEAPONS":
        return "resident"
    return "other"


@dataclass
class Sound:
    bank: str
    key: str                    # "0x0123ABCD" of the first stream
    ids: list[int]
    rate: int
    left: np.ndarray            # int16 views
    right: Optional[np.ndarray]
    name: Optional[str] = None
    auto_role: str = "unknown"
    _feats: dict = field(default_factory=dict)

    @property
    def stereo(self) -> bool:
        return self.right is not None

    @property
    def seconds(self) -> float:
        return len(self.left) / self.rate

    def data(self) -> np.ndarray:
        """float32 (n, 2)."""
        l = self.left.astype(np.float32) / 32768.0
        r = self.right.astype(np.float32) / 32768.0 if self.right is not None else l
        return np.stack([l, r], axis=1)

    def mono(self) -> np.ndarray:
        return self.data().mean(axis=1)

    @property
    def feats(self) -> dict:
        if not self._feats:
            self._feats = features(self.mono(), self.rate)
        return self._feats

    @property
    def label(self) -> str:
        return self.name or self.key


class GameAudio:
    def __init__(self, game_dir: Optional[Path], labels_path: Path, extra_dirs: tuple[Path, ...] = ()) -> None:
        self.game_dir = game_dir
        self.labels_path = labels_path
        self.labels: dict[str, str] = json.loads(labels_path.read_text("utf-8")) if labels_path.exists() else {}
        self.paths: dict[str, Path] = {}
        self.sources: dict[str, str] = {}
        self._cache: dict[str, list[Sound]] = {}
        self._lock = threading.Lock()
        self._discover(extra_dirs)

    # ---------- discovery ----------
    def _discover(self, extra_dirs) -> None:
        roots = []
        if self.game_dir:
            lml = self.game_dir / "lml"
            if lml.is_dir():
                roots += [(p.name, p) for p in sorted(lml.iterdir()) if p.is_dir()]
        roots += [(d.name, d) for d in extra_dirs if d.is_dir()]
        for source, root in roots:
            for f in sorted(root.rglob("*.awc")):
                bank = f.stem
                preferred = f.parent.name == "WEAPONS_PLAYER" or f.parent.name in ("RDR3.Resident", "RESIDENT")
                if bank not in self.paths or preferred:
                    self.paths[bank] = f
                    self.sources[bank] = source

    @property
    def available(self) -> bool:
        return bool(self.paths)

    def banks(self, kind: Optional[str] = None) -> list[str]:
        return sorted(b for b in self.paths if kind is None or bank_kind(b) == kind)

    # ---------- decoding ----------
    def sounds(self, bank: str) -> list[Sound]:
        with self._lock:
            if bank not in self._cache:
                self._cache[bank] = self._load(bank)
            return self._cache[bank]

    def _load(self, bank: str) -> list[Sound]:
        kind = bank_kind(bank)
        streams = [s for s in awc.read(self.paths[bank]) if s.codec_ok and len(s.pcm)]
        groups: dict[str, list] = {}
        for s in streams:
            groups.setdefault(hashlib.md5(s.pcm.tobytes()).hexdigest(), []).append(s)
        uniq = [(g[0], [s.id for s in g]) for g in groups.values()]
        # pair stereo halves: same length, similar loudness, correlated
        rms = [float(np.sqrt(np.mean((u[0].pcm.astype(np.float32) / 32768) ** 2))) for u in uniq]
        by_len: dict[int, list[int]] = {}
        for i, (s, _) in enumerate(uniq):
            by_len.setdefault(len(s.pcm), []).append(i)
        partner: dict[int, int] = {}
        for idxs in by_len.values():
            cands = []
            for a in idxs:
                for b in idxs:
                    if a < b and abs(rms[a] - rms[b]) <= 0.04 * max(rms[a], rms[b], 1e-6):
                        x, y = uniq[a][0].pcm.astype(np.float32), uniq[b][0].pcm.astype(np.float32)
                        c = float(np.corrcoef(x, y)[0, 1]) if x.std() and y.std() else 0.0
                        if c > 0.3:
                            cands.append((c, a, b))
            for c, a, b in sorted(cands, reverse=True):
                if a not in partner and b not in partner:
                    partner[a], partner[b] = b, a
        out, done = [], set()
        for i, (s, ids) in enumerate(uniq):
            if i in done:
                continue
            j = partner.get(i)
            right = None
            all_ids = list(ids)
            if j is not None:
                done.add(j)
                right = uniq[j][0].pcm
                all_ids += uniq[j][1]
            snd = Sound(bank, f"0x{s.id:08X}", sorted(all_ids), s.sample_rate, s.pcm, right,
                        name=next((KNOWN[x] for x in all_ids if x in KNOWN), None))
            snd.auto_role = self._guess(kind, snd)
            out.append(snd)
        out.sort(key=lambda x: (x.auto_role != "shot", x.key))
        return out

    @staticmethod
    def _guess(kind: str, s: Sound) -> str:
        if s.name:
            for role in ("draw", "holster", "impact"):
                if role in s.name:
                    return role
        if kind == "weapon":
            return "shared" if set(s.ids) & SHARED_SLOT_IDS else "shot"
        if kind == "explosions":
            return "explosion" if s.seconds > 0.8 else "other"
        return "unknown"

    # ---------- roles ----------
    def role(self, s: Sound) -> str:
        return self.labels.get(f"{s.bank}/{s.key}", s.auto_role)

    def set_role(self, s: Sound, role: str) -> None:
        k = f"{s.bank}/{s.key}"
        if role == s.auto_role:
            self.labels.pop(k, None)
        else:
            self.labels[k] = role
        self.labels_path.write_text(json.dumps(self.labels, indent=2, sort_keys=True), encoding="utf-8")

    def variants(self, bank: str, role: str) -> list[Sound]:
        if bank not in self.paths:
            return []
        return [s for s in self.sounds(bank) if self.role(s) == role]


def find_game_dir() -> Optional[Path]:
    """RDR2 install folder from the Steam library list (or the usual default locations)."""
    import re
    import winreg
    cands = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            steam = Path(winreg.QueryValueEx(k, "SteamPath")[0])
        vdf = steam / "steamapps" / "libraryfolders.vdf"
        libs = [steam] + [Path(m.replace("\\\\", "\\")) for m in
                          re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8"))] if vdf.exists() else [steam]
        cands += [lib / "steamapps" / "common" / "Red Dead Redemption 2" for lib in libs]
    except OSError:
        pass
    cands += [Path(r"C:\Program Files\Rockstar Games\Red Dead Redemption 2"),
              Path(r"C:\Program Files\Epic Games\RedDeadRedemption2")]
    return next((c for c in cands if (c / "RDR2.exe").exists()), None)
