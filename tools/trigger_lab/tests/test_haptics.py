import json
import unittest
from pathlib import Path

import numpy as np

from ds5.haptics import SR, Cue, HapticLibrary, RumbleHaptics
from gameaudio import convert
from gameaudio.library import GameAudio, find_game_dir
from sim.catalog import Catalog

DATA = Path(__file__).resolve().parents[1] / "data"
CAT = Catalog(DATA / "weapons.json")
GAME = find_game_dir()


def referenced(obj) -> set[str]:
    keys = {"haptic", "open", "close", "auto", "tick", "begin", "end", "dry", "nock", "pre", "creak",
            "swing", "impact", "jerk", "catch"}
    found = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str):
                found.add(v)
            found |= referenced(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= referenced(v)
    return found


class SynthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = HapticLibrary(DATA / "haptics.json", game=None)      # no game audio: fallbacks

    def test_all_referenced_recipes_exist(self):
        names = referenced(CAT.raw) | {"reset_click", "dry_fire", "bow_letdown", "heartbeat", "hammer_cock_auto"}
        self.assertEqual(names - set(self.lib.buffers), set())

    def test_buffers_are_sane(self):
        for name, bufs in self.lib.buffers.items():
            for buf in bufs:
                with self.subTest(name):
                    self.assertEqual(buf.shape[1], 2)
                    self.assertTrue(np.isfinite(buf).all())
                    self.assertLessEqual(np.abs(buf).max(), 1.0)
                    self.assertGreater(np.abs(buf).max(), 0.05)
                    self.assertLess(len(buf) / SR, 2.0)

    def test_pump_is_support_hand(self):
        buf = self.lib.buffers["pump_back"][0]
        self.assertGreater(np.abs(buf[:, 0]).sum(), 2 * np.abs(buf[:, 1]).sum())

    def test_slow_motion_is_longer(self):
        a = self.lib.get(Cue("shot_revolver"))
        b = self.lib.get(Cue("shot_revolver", speed=0.6))
        self.assertAlmostEqual(len(b) / len(a), 1 / 0.6, delta=0.05)

    def test_repan_moves_to_other_hand(self):
        right = self.lib.get(Cue("punch_impact", pan=0.8))
        left = self.lib.get(Cue("punch_impact", pan=-0.8))
        self.assertGreater(np.abs(right[:, 1]).sum(), np.abs(right[:, 0]).sum())
        self.assertGreater(np.abs(left[:, 0]).sum(), np.abs(left[:, 1]).sum())

    def test_rumble_envelope_decays(self):
        r = RumbleHaptics(self.lib)
        r.play(Cue("shot_shotgun"), now=0.0)
        early, late, gone = r.tick(0.01), r.tick(0.3), r.tick(5.0)
        self.assertGreater(early[0], late[0])
        self.assertEqual(gone, (0, 0))


class ConvertTests(unittest.TestCase):
    def test_synthetic_gunshot(self):
        t = np.arange(int(0.8 * 44100)) / 44100
        rng = np.random.default_rng(1)
        shot = (rng.standard_normal(len(t)) * np.exp(-t / 0.08)).astype(np.float32)   # broadband blast
        h = convert.to_haptic(shot, 44100, "handgun", pan=0.5)
        self.assertEqual(h.shape[1], 2)
        self.assertLess(len(h) / SR, 0.45)                          # tail tightened
        self.assertLess(np.abs(h[:, 0]).max(), np.abs(h[:, 1]).max())   # panned right
        spec = np.abs(np.fft.rfft(h[:, 1]))
        f = np.fft.rfftfreq(len(h), 1 / SR)
        self.assertLess(spec[f > 500].sum() / spec.sum(), 0.1)       # energy where actuators work
        k = convert.kick_steps(shot, 44100, 16)
        self.assertEqual(k[0], 8)
        self.assertEqual(k, sorted(k, reverse=True))

    def test_silence(self):
        self.assertEqual(convert.to_haptic(np.zeros(1000, np.float32), 48000).shape, (1, 2))


@unittest.skipUnless(GAME and (GAME / "lml").is_dir(), "no RDR2 sound mod installed")
class GameAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ga = GameAudio(GAME, Path("nonexistent_labels.json"))
        cls.lib = HapticLibrary(DATA / "haptics.json", cls.ga)

    def test_weapon_banks_have_shots(self):
        for bank in self.ga.banks("weapon"):
            with self.subTest(bank):
                self.assertTrue(self.ga.variants(bank, "shot"))

    def test_every_bank_in_catalog_builds(self):
        for w in CAT.weapons:
            p = CAT.resolve(w["name"])
            if p.get("bank") and p["bank"] in self.ga.paths:
                with self.subTest(w["name"]):
                    name = self.lib.ensure_weapon(p)
                    self.assertTrue(name and self.lib.variant_count(name) >= 1)
                    self.assertEqual(len(self.lib.kicks[name]), self.lib.variant_count(name))

    def test_speaker_sound_matches_haptic_variant(self):
        p = CAT.resolve("WEAPON_REVOLVER_CATTLEMAN")
        name = self.lib.ensure_weapon(p)
        cue = self.lib.pick(Cue(name))
        self.assertIsNotNone(cue.variant)
        audio = self.lib.get_audio(cue)
        src = self.ga.variants(p["bank"], "shot")[cue.variant]
        self.assertAlmostEqual(len(audio) / 48000, src.seconds, delta=0.01)
        self.assertIsNone(self.lib.get_audio(Cue("hammer_cock")))       # synthesized: no game recording

    def test_explosions_from_game(self):
        self.assertTrue(self.lib.source["explosion_far"].startswith("game"))
        self.assertGreater(self.lib.variant_count("explosion_far"), 1)


if __name__ == "__main__":
    unittest.main()
