"""One-off patch: features use world surfaces; footsteps, hooves from legs, landings, climbing, doors."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "mod" / "src"
p = ROOT / "features.cpp"
s = p.read_text(encoding="utf-8")


def rep(a, b):
    global s
    if a not in s:
        raise SystemExit("not found: " + a[:80])
    s = s.replace(a, b, 1)


# surface classification moved to world (Surfaces)
start = s.index("// Ground material hash -> surface.")
end = s.index("void Features::horse(")
s = s[:start] + s[end:]

rep("""    hit_gain_ = c.num("Haptics", "HitConfirm", 0.0f);""",
    """    hit_gain_ = c.num("Haptics", "HitConfirm", 0.0f);
    step_gain_ = c.num("Haptics", "Footsteps", 0.4f);
    land_gain_ = c.num("Haptics", "Landing", 0.7f);
    action_gain_ = c.num("Haptics", "Actions", 0.5f);""")

rep("""    if (stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {""",
    """    // fallback when the horse's leg bones were not found: hooves from the gait
    if (!g.hoof_bones && stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {""")
rep("""            std::string surf = surface(g.ground_material, g.mount_in_water);
            if (g.ground_material && surf == "dirt" && log::debug_enabled() && unknown_materials_[g.ground_material]++ == 0)
                LOGD("ground material 0x%08X (treated as dirt)", g.ground_material);
            float pan""", """            const std::string& surf = g.horse_surface;
            float pan""")

rep("""        } else if (e.type == WorldEvent::HitConfirm && hit_gain_ > 0) {
            cues.push_back(make("hit_confirm", hit_gain_, 0.6f, true));
        }""", """        } else if (e.type == WorldEvent::HitConfirm && hit_gain_ > 0) {
            cues.push_back(make("hit_confirm", hit_gain_, 0.6f, true));
        } else if (e.type == WorldEvent::Footstep && step_gain_ > 0) {
            // boots: left foot on the left actuator, right on the right; the surface decides the feel
            cues.push_back(make("step_" + e.cause, step_gain_ * e.strength * rng_.range(0.9f, 1.08f), e.pan, true));
        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0) {
            cues.push_back(make("hoof_" + e.cause, horse_gain_ * e.strength * rng_.range(0.88f, 1.08f), e.pan, true));
        } else if (e.type == WorldEvent::Land && land_gain_ > 0) {
            cues.push_back(make("land", land_gain_ * e.strength));
            cues.push_back(make("step_" + e.cause, step_gain_ * 1.2f));
        } else if (e.type == WorldEvent::Climb && action_gain_ > 0) {
            cues.push_back(make("climb_grab", action_gain_));
        } else if (e.type == WorldEvent::Door && action_gain_ > 0) {
            cues.push_back(make("door_open", action_gain_, e.pan, true));
        }""")
p.write_text(s, encoding="utf-8")

h = ROOT / "features.h"
t = h.read_text(encoding="utf-8")
t = t.replace("    std::string surface(uint32_t material, bool water) const;\n", "", 1)
t = t.replace("          cold_gain_ = 0.5f, hit_gain_ = 0, brightness_ = 1;",
              "          cold_gain_ = 0.5f, hit_gain_ = 0, brightness_ = 1, step_gain_ = 0.4f, land_gain_ = 0.7f, action_gain_ = 0.5f;", 1)
t = t.replace("    std::map<uint32_t, int> unknown_materials_;\n", "", 1)
h.write_text(t, encoding="utf-8")
print("features patched")
