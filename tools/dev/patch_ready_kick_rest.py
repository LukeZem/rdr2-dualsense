"""Fire rate + cocked state from the game (IS_PED_WEAPON_READY_TO_SHOOT), stronger two-phase trigger
recoil, holster/draw haptic, riding pulse off by default."""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "mod" / "src"


def edit(name, pairs):
    p = SRC / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:90]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


edit("engine.cpp", [
    # held: re-arm from the game's readiness instead of a guessed timer
    ("""        if (now - shot_t_ >= rate_s_ * slow() && raw <= reset_raw_) {
            if (last_dry_ && clip_size_ && !g.valid) {""",
     """        bool game_rate = g.valid && ready_usable_;
        if (game_rate && !g.ready && raw <= reset_raw_) {
            if (not_ready_since_ < 0) not_ready_since_ = now;
            // a manual action (single-action hammer, lever, bolt, pump) that isn't ready needs its R2 stroke
            std::string at0 = jstr(action_, "type", "none");
            if (at0 != "none" && at0 != "semi" && set_.manual_action && clip_ != 0 && now - shot_t_ > 0.08) {
                state_ = "action";
                not_ready_since_ = -1;
                return fx::multi_feedback(action_curve_);
            }
            if (now - not_ready_since_ > 2.5) {          // never became ready: don't trust the signal for this gun
                ready_usable_ = false;
                LOGI("%s: the game's 'ready to shoot' never came back - using timing for this gun", id_.c_str());
            }
        }
        bool can_rearm = game_rate ? g.ready : now - shot_t_ >= rate_s_ * slow();
        if (can_rearm && raw <= reset_raw_ && now - shot_t_ > 0.05) {
            not_ready_since_ = -1;
            if (last_dry_ && clip_size_ && !g.valid) {"""),
    ("""            std::string at = jstr(action_, "type", "none");
            if (at != "none" && at != "semi" && set_.manual_action && clip_ != 0) {
                state_ = "action";
                return fx::multi_feedback(action_curve_);
            }
            state_ = "ready";""",
     """            std::string at = jstr(action_, "type", "none");
            if (!game_rate && at != "none" && at != "semi" && set_.manual_action && clip_ != 0) {
                state_ = "action";
                return fx::multi_feedback(action_curve_);
            }
            state_ = "ready";"""),
    # action: if the game cocked it by itself, go straight to firing
    ("""    if (st == "action") {
        crossed(action_ticks_, raw, f, now);""",
     """    if (st == "action") {                         // manual cocking / cycling press
        if (g.valid && ready_usable_ && g.ready && raw <= reset_raw_) {   // the game cocked it itself
            state_ = "ready";
            return fire_block(raw, now);
        }
        crossed(action_ticks_, raw, f, now);"""),
    # cycling: ready again when the game says so
    ("""        if (raw <= reset_raw_ && now - action_t_ >= jnum(action_, "min_ms", 120) / 1000) {""",
     """        bool done = g.valid && ready_usable_ ? g.ready : now - action_t_ >= jnum(action_, "min_ms", 120) / 1000;
        if (raw <= reset_raw_ && done) {"""),
    # the old "skipped shot" learner only when the readiness signal isn't used
    ("""        if (unconfirmed_since_ > 0) {""", """        if (unconfirmed_since_ > 0 && !ready_usable_) {"""),
])

# ---------- engine: two-phase recoil ----------
edit("engine.cpp", [
    ("""bool WeaponEngine::Kick::block(float dt, float slow, fx::Block& out) const {
    float step = step_s * slow;
    if (dt < 0 || step <= 0) return false;
    size_t i = size_t(dt / step);
    if (i >= steps.size()) return false;
    out = fx::vibration(0, steps[i], freq);
    return true;
}""",
     """// Recoil on the trigger: a shove (the motor pushes back against your finger at full force, like a
// trigger slapping forward), then a lower, longer rumble that fades - shaped by the gun's recorded shot.
bool WeaponEngine::Kick::block(float dt, float slow, fx::Block& out) const {
    if (dt < 0 || steps.empty()) return false;
    float shove = 0.035f * slow;
    if (dt < shove) {
        out = fx::feedback(0, std::min(8, steps[0] + 1));
        return true;
    }
    float step = step_s * slow * 1.6f;
    size_t i = size_t((dt - shove) / step);
    if (i >= steps.size()) return false;
    out = fx::vibration(0, steps[i], std::max(18, int(freq * 0.75f)));
    return true;
}"""),
])
edit("engine.h", [(
    "        float duration(float slow) const { return steps.size() * step_s * slow; }",
    "        float duration(float slow) const { return steps.empty() ? 0.0f : 0.035f * slow + steps.size() * step_s * slow * 1.6f; }")])

# ---------- core: hints ----------
edit("core.cpp", [(
    """        h.hip_fire = !g.aiming;""",
    """        h.hip_fire = !g.aiming;
        h.ready = g.ready;""")])

# ---------- features: holster / draw; riding pulse off by default ----------
edit("features.cpp", [
    ("""    riding_pulse_ = c.integer("Triggers", "RidingPulse", 2);""",
     """    riding_pulse_ = c.integer("Triggers", "RidingPulse", 0);"""),
    ("""    if (!g.blocked) {
        horse(g, now, cues, out, weapon_active);""",
     """    if (!g.blocked) {
        if (g.holstering && !was_holstering_ && action_gain_ > 0)    // gun sliding in / out of the leather
            cues.push_back(make("holster_draw", action_gain_ * 1.2f, 0.5f, true));
        was_holstering_ = g.holstering;
        horse(g, now, cues, out, weapon_active);"""),
])
edit("features.h", [("    bool rearing_ = false;", "    bool rearing_ = false;\n    bool was_holstering_ = false;")])
edit("config.cpp", [
    ("; Triggers pulse with the horse's gait while riding unarmed (0 = off, 1-8 strength)\nRidingPulse=2",
     "; Triggers pulse with the horse's gait while riding unarmed (0 = off, 1 = on)\nRidingPulse=0"),
    ("; Grabbing a ledge, opening a door\nActions=0.5", "; Grabbing a ledge, opening a door, drawing / holstering a gun\nActions=0.5"),
])

# ---------- recipe ----------
hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
txt = hp.read_text(encoding="utf-8").rstrip()
if '"holster_draw"' not in txt:
    txt = txt[:-1].rstrip() + ''',
  "holster_draw": {"_doc": "the gun slides through the leather, then seats / clears", "gain": 1.0, "layers": [
    {"type": "noise", "lo": 90, "hi": 260, "attack_ms": 25, "decay_ms": 45, "amp": 0.35, "pan": 0.5},
    {"type": "click", "hz": 210, "cycles": 1, "delay_ms": 90, "amp": 0.55, "pan": 0.5}
  ]}
}
'''
    json.loads(txt)
    hp.write_text(txt, encoding="utf-8")
print("patched")
