import unittest
from pathlib import Path

from ds5.device import CIRCLE, InputState, R1, SQUARE
from sim.catalog import Catalog
from sim.engine import Calibration, Settings, WeaponEngine

DATA = Path(__file__).resolve().parents[1] / "data"
CAT = Catalog(DATA / "weapons.json")
DT = 0.004  # 250 Hz, like the DualSense over USB


class Rig:
    """Feeds synthetic trigger positions to an engine and collects everything it emits."""

    def __init__(self, weapon: str, profile_patch: dict | None = None, **settings):
        prof = CAT.resolve(weapon)
        if profile_patch:
            prof.update(profile_patch)
        self.eng = WeaponEngine(prof, Calibration(), Settings(**settings))
        self.t = 1.0
        self.frames = []
        self.raws = []

    def feed(self, raws, buttons=0, l2=0):
        for r in raws:
            self.t += DT
            self.raws.append(int(r))
            self.frames.append(self.eng.update(InputState(t=self.t, r2=int(r), l2=l2, buttons=buttons)))
        return self

    def hold(self, raw, seconds, buttons=0, l2=0):
        return self.feed([raw] * int(seconds / DT), buttons, l2)

    def pull(self, to=255, samples=40, l2=0):
        return self.feed([to * i / samples for i in range(samples + 1)], l2=l2)

    def release(self, samples=10, l2=0):
        return self.feed([0] * samples, l2=l2)

    def tap(self, button):
        return self.feed([0], buttons=button).feed([0])

    def events(self, kind):
        return [e for f in self.frames for e in f.events if e["type"] == kind]

    def names(self):
        return [c.name for f in self.frames for c in f.haptics]


class CatalogTests(unittest.TestCase):
    def test_every_weapon_resolves_with_hash(self):
        for w in CAT.weapons:
            p = CAT.resolve(w["name"])
            self.assertRegex(p["hash"], r"^0x[0-9A-F]{8}$")
        self.assertEqual(CAT.resolve("WEAPON_REVOLVER_CATTLEMAN")["hash"], "0x169F59F7")
        self.assertEqual(CAT.resolve("WEAPON_BOW")["hash"], "0x88A8505C")

    def test_tune_overrides_class(self):
        lemat = CAT.resolve("WEAPON_REVOLVER_LEMAT")
        self.assertEqual(lemat["clip"], 9)
        self.assertEqual(lemat["fire"]["break_zone"], 5)          # inherited
        self.assertEqual(lemat["audio"]["convert"], "long")        # overridden
        self.assertEqual(lemat["audio"]["pan"], 0.35)              # inherited inside the same dict

    def test_names_unique(self):
        names = [w["name"] for w in CAT.weapons]
        self.assertEqual(len(names), len(set(names)))


class GunTests(unittest.TestCase):
    def test_single_shot_at_break_and_no_refire_while_held(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", manual_action=False)
        rig.pull().hold(255, 1.0)
        shots = rig.events("shot")
        self.assertEqual(len(shots), 1)
        rts = [f.game_rt for f in rig.frames]
        first = rts.index(255)
        self.assertTrue(all(v == 0 for v in rts[:first]) and all(v == 255 for v in rts[first:]))
        self.assertLess(rig.raws[first - 1], rig.eng.break_raw)
        self.assertGreaterEqual(rig.raws[first], rig.eng.break_raw)

    def test_rearm_needs_release_and_rate(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", manual_action=False)
        rig.pull().release(5).pull()
        self.assertEqual(len(rig.events("shot")), 1)
        rig.release(int(0.5 / DT)).pull()
        self.assertEqual(len(rig.events("shot")), 2)

    def test_single_action_needs_cock_tap_by_default(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", fanning=False)
        rig.pull().release(int(0.5 / DT), l2=200)
        self.assertEqual(rig.eng.state, "action")
        rig.pull(l2=200)                           # this tap cocks, it must not fire
        self.assertEqual(len(rig.events("shot")), 1)
        self.assertIn("hammer_cock", rig.names())
        rig.release(int(0.3 / DT), l2=200).pull(l2=200)
        self.assertEqual(len(rig.events("shot")), 2)

    def test_fanning_when_hip_firing(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", fanning=True)
        rig.pull().release(int(0.4 / DT)).pull()   # rapid second tap, no L2: fans
        self.assertEqual(len(rig.events("shot")), 2)
        self.assertTrue(rig.events("shot")[1]["fanned"])

    def test_no_fanning_while_aiming(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", fanning=True)
        rig.pull(l2=200).release(int(0.4 / DT), l2=200).pull(l2=200)
        self.assertEqual(len(rig.events("shot")), 1)

    def test_double_action_needs_no_cocking(self):
        rig = Rig("WEAPON_REVOLVER_DOUBLEACTION")
        rig.pull(samples=80).release(int(0.4 / DT)).pull(samples=80)
        self.assertEqual(len(rig.events("shot")), 2)
        names = rig.names()
        self.assertLess(names.index("cylinder_index"), names.index("shot_revolver"))

    def test_lever_cycle_between_shots(self):
        rig = Rig("WEAPON_REPEATER_CARBINE")
        rig.pull().release(int(0.5 / DT))
        self.assertEqual(rig.eng.state, "action")
        rig.pull()
        self.assertEqual(len(rig.events("shot")), 1)
        self.assertEqual(len(rig.events("action")), 1)
        rig.release(int(0.3 / DT)).pull()
        self.assertEqual(len(rig.events("shot")), 2)
        self.assertIn("lever_open", rig.names())
        self.assertIn("lever_close", rig.names())

    def test_auto_cycle_haptic_without_manual_cocking(self):
        rig = Rig("WEAPON_REPEATER_CARBINE", manual_action=False)
        rig.pull().hold(255, 0.5)
        self.assertIn("lever_cycle", rig.names())

    def test_recoil_kick_after_lock_time(self):
        rig = Rig("WEAPON_SHOTGUN_DOUBLEBARREL")
        rig.pull()
        shot_idx = next(i for i, f in enumerate(rig.frames) if f.events)
        rig.hold(255, 0.2)
        modes = [f.out.r2[0] for f in rig.frames[shot_idx:]]
        self.assertEqual(modes[0], 0x21)
        self.assertIn(0x26, modes)
        self.assertIn("shot_shotgun", rig.names())

    def test_kick_follows_audio_variant_inside_class_envelope(self):
        rig = Rig("WEAPON_SHOTGUN_DOUBLEBARREL",
                  {"recoil": {**CAT.resolve("WEAPON_SHOTGUN_DOUBLEBARREL")["recoil"], "kick_variants": [[8, 3, 1]]}})
        rig.pull()
        self.assertEqual(rig.eng.kick.steps, [8, 3, 1, 1, 1])
        cue = next(c for f in rig.frames for c in f.haptics if c.name == "shot_shotgun")
        self.assertEqual(cue.variant, 0)

    def test_dry_click_then_auto_reload_revolver(self):
        rig = Rig("WEAPON_SHOTGUN_DOUBLEBARREL")
        for _ in range(2):
            rig.pull().release(int(0.4 / DT))
        self.assertEqual(rig.eng.clip, 0)
        rig.pull()
        self.assertEqual(len(rig.events("dry")), 1)
        self.assertIn("dry_fire", rig.names())
        rig.release(int(0.4 / DT))
        self.assertEqual(rig.eng.state, "reloading")
        rig.release(int(2.5 / DT))
        self.assertEqual((rig.eng.state, rig.eng.clip), ("ready", 2))
        self.assertEqual(rig.names().count("reload_shell"), 2)

    def test_semi_auto_goes_dead_when_empty(self):
        rig = Rig("WEAPON_PISTOL_SEMIAUTO", profile_patch={"clip": 1})
        rig.pull().release(int(0.3 / DT))
        self.assertEqual(rig.eng.clip, 0)
        from ds5.effects import zone_view
        self.assertEqual(max(zone_view(rig.frames[-1].out.r2)[1]), 1)   # no wall left
        rig.pull()
        self.assertNotIn("dry_fire", rig.names())                       # slide locked: no click

    def test_square_reloads(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", manual_action=False)
        rig.pull().release(int(0.5 / DT)).tap(SQUARE)
        self.assertEqual(rig.eng.state, "reloading")

    def test_dead_eye_slows_and_beats(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", dead_eye=True, manual_action=False)
        rig.pull().hold(255, 2.0)
        self.assertGreaterEqual(rig.names().count("heartbeat"), 2)
        shot = next(c for f in rig.frames for c in f.haptics if c.name == "shot_revolver")
        self.assertLess(shot.speed, 1.0)

    def test_snap_analysis_on_synthetic_break(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", manual_action=False)
        b = rig.eng.break_raw
        rig.feed(list(range(0, b - 6, 6)) + [b - 5] * 10 + [b + 60, b + 66, b + 68]).hold(b + 68, 0.2)
        a = rig.events("analysis")
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["dt_ms"], 0.0)

    def test_steady_squeeze_reports_no_snap(self):
        rig = Rig("WEAPON_REVOLVER_CATTLEMAN", manual_action=False)
        rig.pull(samples=60).hold(255, 0.2)
        self.assertFalse(rig.events("analysis")[0]["snap"])

    def test_every_weapon_runs_in_every_mode(self):
        for w in CAT.weapons:
            for mode in (None, "weapon", "hybrid"):
                with self.subTest(weapon=w["name"], mode=mode):
                    rig = Rig(w["name"], mode_override=mode)
                    for _ in range(3):
                        rig.pull().hold(255, 0.3).release(int(0.6 / DT)).tap(R1).tap(CIRCLE)
                    self.assertTrue(all(len(f.out.r2) == 11 and len(f.out.l2) == 11 for f in rig.frames))
                    self.assertTrue(rig.eng.hint())


class OtherTypeTests(unittest.TestCase):
    def test_bow_full_draw(self):
        rig = Rig("WEAPON_BOW")
        rig.pull(to=200, samples=10).hold(200, 1.2).release()
        shots = rig.events("shot")
        self.assertEqual((len(shots), shots[0]["draw"]), (1, 1.0))
        self.assertIn("bow_release", rig.names())

    def test_bow_tension_builds(self):
        from ds5.effects import zone_view
        rig = Rig("WEAPON_BOW")
        rig.pull(to=200, samples=5).hold(200, 1.0)
        strengths = [max(zone_view(f.out.r2)[1]) for f in rig.frames[6:]]
        self.assertEqual(strengths, sorted(strengths))

    def test_bow_quick_tap_lets_down(self):
        rig = Rig("WEAPON_BOW")
        rig.pull(to=200, samples=5).hold(200, 0.1).release()
        self.assertEqual(rig.events("shot"), [])

    def test_gatling_rate(self):
        rig = Rig("WEAPON_TURRET_GATLING")
        rig.pull(samples=5).hold(255, 1.0)
        self.assertAlmostEqual(len(rig.events("shot")), 7, delta=1)

    def test_dynamite_fuse_then_explosion(self):
        rig = Rig("WEAPON_THROWN_DYNAMITE")
        rig.pull().release(int(3.5 / DT))
        names = rig.names()
        self.assertIn("fuse_light", names)
        self.assertLess(names.index("throw"), names.index("explosion_far"))

    def test_melee_hit_when_locked_on(self):
        rig = Rig("WEAPON_MELEE_MACHETE", {"melee": {**CAT.resolve("WEAPON_MELEE_MACHETE")["melee"], "block_chance": 0}})
        rig.feed([0], buttons=R1, l2=200).release(int(0.3 / DT), l2=200)
        self.assertEqual(rig.names()[:2], ["melee_swing_heavy", "impact_chop"])
        self.assertEqual(rig.events("strike")[0]["result"], "hit")
        self.assertTrue(all(f.out.r2[0] == 0x05 for f in rig.frames))

    def test_melee_miss_without_target(self):
        rig = Rig("WEAPON_MELEE_MACHETE")
        rig.tap(R1).release(int(0.3 / DT))
        self.assertEqual(rig.events("strike")[0]["result"], "miss")
        self.assertIn("melee_miss_heavy", rig.names())
        self.assertNotIn("impact_chop", rig.names())

    def test_fists_alternate_hands_and_finish(self):
        prof = CAT.resolve("WEAPON_UNARMED")
        rig = Rig("WEAPON_UNARMED", {"melee": {**prof["melee"], "block_chance": 0}})
        for _ in range(3):
            rig.feed([0], buttons=R1, l2=200).release(int(0.4 / DT), l2=200)
        strikes = rig.events("strike")
        self.assertEqual([x["hand"] for x in strikes], ["right", "left", "right"])
        self.assertEqual([x["result"] for x in strikes], ["hit", "hit", "finisher"])
        self.assertIn("punch_finisher", rig.names())
        pans = [c.pan for f in rig.frames for c in f.haptics if c.name == "punch_swing"]
        self.assertEqual([p > 0 for p in pans], [True, False, True])

    def test_fists_blocked(self):
        prof = CAT.resolve("WEAPON_UNARMED")
        rig = Rig("WEAPON_UNARMED", {"melee": {**prof["melee"], "block_chance": 1.0}})
        rig.feed([0], buttons=R1, l2=200).release(int(0.4 / DT), l2=200)
        self.assertEqual(rig.events("strike")[0]["result"], "blocked")
        self.assertIn("punch_blocked", rig.names())

    def test_punch_miss_lands_later_than_a_hit_would(self):
        rig = Rig("WEAPON_UNARMED")
        rig.tap(R1).release(int(0.4 / DT))
        t_swing = next(i for i, f in enumerate(rig.frames) if any(c.name == "punch_swing" for c in f.haptics))
        t_miss = next(i for i, f in enumerate(rig.frames) if any(c.name == "punch_miss" for c in f.haptics))
        self.assertGreater((t_miss - t_swing) * DT, 0.11)

    def test_lasso_catch_and_struggle(self):
        from ds5.effects import zone_view
        rig = Rig("WEAPON_LASSO")
        rig.pull().release(int(0.6 / DT))
        self.assertEqual(rig.eng.state, "tethered")
        rig.hold(255, 3.0)
        strengths = {max(zone_view(f.out.r2)[1]) for f in rig.frames[-700:]}
        self.assertGreater(len(strengths), 2)                  # the pull varies
        self.assertIn("rope_jerk", rig.names())
        rig.tap(CIRCLE)
        self.assertEqual(rig.eng.state, "ready")

    def test_tools_have_no_effects(self):
        rig = Rig("WEAPON_KIT_BINOCULARS")
        rig.pull()
        self.assertTrue(all(f.out.r2[0] == 0x05 for f in rig.frames))


if __name__ == "__main__":
    unittest.main()
