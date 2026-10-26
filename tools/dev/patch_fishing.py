"""Fishing from the game's own fishing task (TASK::_GET_TASK_FISHING): line tension on L2, bites on R2,
the fish's fight in the haptics."""
import json
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


# ---------- shared state ----------
edit("common.h", [(
    "template <typename T>\ninline T clampv(",
    r'''// The game's fishing task, read every frame while the rod is out (fields of the 30-slot struct
// TASK::_GET_TASK_FISHING fills - layout from Rockstar's fishing_core script).
struct FishingState {
    bool active = false;
    int state = 0;          // 1 idle, 2 grip, 3 pulling back, 4 casting, 6 line in the water, 7 hooked, 12 in hand
    float tension = 0;      // 0..1, the line snaps at 1
    float struggle = 0;     // 1 = the hooked fish is fighting, 0 = tired
    float reel = 0;         // > 0 = reeling in
    float side = -1;        // hooked fish left (< 0.5) / right (> 0.5), -1 = n/a
    float weight_lb = 0;    // > 0 while waiting = a fish has taken the bait
    float distance = 0;     // rod to hook, metres
    int cmd = 0;            // script bits: 2 fish lost, 512 nibble
    uint32_t fish = 0;      // hooked fish entity
};

template <typename T>
inline T clampv(''')])

edit("natives.h", [(
    "inline bool IS_PED_WEAPON_READY_TO_SHOOT(Ped p)",
    "inline bool GET_TASK_FISHING(Ped p, void* data) { return invoke<int>(0xF3735ACD11ACD500ull, p, data) != 0; }\n"
    "inline bool IS_PED_WEAPON_READY_TO_SHOOT(Ped p)")])

edit("world.h", [
    ("    bool holstering = false;       // a weapon is going into / coming out of the holster",
     "    bool holstering = false;       // a weapon is going into / coming out of the holster\n"
     "    FishingState fishing;"),
    ("    bool last_ready_ = true;", "    bool last_ready_ = true;\n    int fish_log_state_ = -1;"),
])
edit("world.cpp", [(
    "    s.reloading = IS_PED_RELOADING(me);",
    r'''    // fishing: the game's own fishing task (read only - the fishing script writes it back every frame)
    if (w == joaat("WEAPON_FISHINGROD")) {
        alignas(8) uint64_t buf[32] = {};
        FishingState& f = s.fishing;
        f.active = GET_TASK_FISHING(me, buf);
        auto i32 = [&](int i) { return int32_t(uint32_t(buf[i])); };
        auto f32 = [&](int i) { uint32_t u = uint32_t(buf[i]); float v; std::memcpy(&v, &u, 4); return std::isfinite(v) ? v : 0.0f; };
        if (f.active) {
            f.state = i32(0);
            f.distance = f32(2);
            f.reel = f32(4);
            f.cmd = i32(6);
            f.fish = uint32_t(buf[7]);
            f.weight_lb = f32(8) * 54.25f;
            f.tension = clampv(f32(13), 0.0f, 1.0f);
            f.struggle = f32(17);
            f.side = f32(22);
        }
        if (log::debug_enabled() && f.state != fish_log_state_) {
            LOGD("fishing: state %d -> %d (tension %.2f, fish %.1f lb, struggle %.0f, reel %.2f, side %.2f, bits %d)",
                 fish_log_state_, f.state, f.tension, f.weight_lb, f.struggle, f.reel, f.side, f.cmd);
            fish_log_state_ = f.state;
        }
    } else {
        fish_log_state_ = -1;
    }
    s.reloading = IS_PED_RELOADING(me);''')])

edit("engine.h", [
    ("    bool ready = true;              // the game says the gun can fire (cooldown over, hammer cocked...)",
     "    bool ready = true;              // the game says the gun can fire (cooldown over, hammer cocked...)\n"
     "    FishingState fishing;"),
    ("    fx::Block update_tension(int raw, uint32_t pressed, double now, EngineFrame& f, const GameHints& g);",
     "    fx::Block update_tension(int raw, uint32_t pressed, double now, EngineFrame& f, const GameHints& g);\n"
     "    fx::Block update_fishing(int raw, double now, EngineFrame& f, const GameHints& g);"),
    ("    float lasso_prev_ = 0;",
     "    float lasso_prev_ = 0;\n"
     "    // fishing\n"
     "    int fish_state_ = 0, fish_cmd_ = 0;\n"
     "    bool fish_bite_ = false;\n"
     "    float fish_peak_ = 0, reel_acc_ = 0;\n"
     "    double fish_t_ = 0, bite_until_ = 0, nibble_until_ = 0, next_surge_ = 0, next_flop_ = 0, flop_until_ = 0;"),
])
edit("core.cpp", [("        h.ready = g.ready;", "        h.ready = g.ready;\n        h.fishing = g.fishing;")])

edit("engine.cpp", [
    ("""fx::Block WeaponEngine::update_tension(int raw, uint32_t pressed, double now, EngineFrame& f, const GameHints& g) {
    const json& tn = tension_;""",
     r'''// Fishing, from the game's own fishing task. On a controller R2 casts and strikes, L2 grips the rod and the
// reel is the right stick - so L2 carries the line: its tension, the fish's surges, the strain before it snaps.
fx::Block WeaponEngine::update_fishing(int raw, double now, EngineFrame& f, const GameHints& g) {
    (void)raw;
    const FishingState& fs = g.fishing;
    int st = fs.active ? fs.state : 0;
    double dt = now - fish_t_;
    fish_t_ = now;
    if (dt <= 0 || dt > 0.1) dt = 0;
    int was = fish_state_;
    fish_state_ = st;
    if (st != was) {
        if (st == 4) play(f, "cast");                                         // the line flies out
        if (st == 7) {                                                        // struck: the hook bites in
            play(f, "fish_hooked", clampv(0.6f + fs.weight_lb / 25.0f, 0.6f, 1.0f));
            fish_peak_ = 0;
        }
        if (was == 7 && st == 12) {                                          // landed
            play(f, "fish_landed", clampv(0.5f + fs.weight_lb / 20.0f, 0.5f, 1.0f));
            next_flop_ = now + 0.6;
            flop_until_ = now + clampv(3.0 + fs.weight_lb / 4.0, 3.0, 8.0);
        } else if (was == 7) {                                                // gone: snapped, or it threw the hook
            play(f, fish_peak_ > 0.85f ? "line_snap" : "line_slack");
        }
    }
    // a fish takes the bait while the line waits (and the nibbles before, if the game shows them)
    bool waiting = st == 6 || st == 10;
    bool bite = waiting && fs.weight_lb > 0;
    if (bite && !fish_bite_) {
        play(f, "fish_bite");
        bite_until_ = now + 0.7;
    }
    fish_bite_ = bite;
    if (waiting && (fs.cmd & 512) && !(fish_cmd_ & 512)) {
        play(f, "fish_tug", 0.45f);
        nibble_until_ = now + 0.12;
    }
    fish_cmd_ = fs.cmd;

    if (st == 7) {
        fish_peak_ = std::max(fish_peak_ * 0.995f, fs.tension);
        if (fs.tension > 0.85f) f.l2 = fx::vibration(0, 8, 30);              // about to snap: ease off!
        else f.l2 = fx::feedback(0, clampv(int(1 + std::lround(fs.tension * 7)), 1, 8));
        if (fs.struggle > 0.5f && now >= next_surge_) {                       // it fights: surges to its side
            next_surge_ = now + rng_.range(0.22f, 0.6f);
            Cue c = cue("fish_tug", 0.45f + 0.55f * fs.tension);
            if (fs.side >= 0) {
                c.has_pan = true;
                c.pan = clampv((fs.side - 0.5f) * 2.0f, -1.0f, 1.0f);
            }
            f.cues.push_back(c);
        }
        if (fs.reel > 0.02f) {                                                // the spool clicks as you reel
            reel_acc_ += float(dt) * 16.0f * std::min(1.0f, fs.reel);
            if (reel_acc_ >= 1) {
                reel_acc_ -= 1;
                play(f, "reel_click", 0.3f + 0.3f * fs.tension);
            }
        }
    } else if (st == 12 && now < flop_until_ && now >= next_flop_) {          // flapping in your hand
        next_flop_ = now + rng_.range(0.45f, 1.2f);
        play(f, "fish_flop", rng_.range(0.5f, 0.9f));
    }
    // R2: loading the cast, then the strike when it bites
    if (waiting) {
        if (now < bite_until_) return fx::vibration(2, 7, 9);
        if (now < nibble_until_) return fx::vibration(2, 3, 14);
        return fx::feedback(3, 1);
    }
    if (st == 2 || st == 3) return fx::multi_feedback({0, 0, 1, 1, 2, 2, 3, 3, 3, 3});
    return fx::off();
}

fx::Block WeaponEngine::update_tension(int raw, uint32_t pressed, double now, EngineFrame& f, const GameHints& g) {
    if (g.valid && id_ == "WEAPON_FISHINGROD") return update_fishing(raw, now, f, g);
    const json& tn = tension_;'''),
])

# ---------- recipes ----------
hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
txt = hp.read_text(encoding="utf-8").rstrip()
new = {
    "fish_hooked": {"_doc": "the strike: the hook sets, the rod loads", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 85, "to_hz": 55, "attack_ms": 2, "decay_ms": 70, "amp": 0.9, "pan": 0.0},
        {"type": "click", "hz": 240, "cycles": 1, "amp": 0.5, "pan": 0.0}]},
    "reel_click": {"_doc": "one tooth of the reel's ratchet", "gain": 1.0, "layers": [
        {"type": "click", "hz": 320, "cycles": 1, "amp": 0.45, "pan": 0.35}]},
    "line_snap": {"_doc": "the line parts: a crack, then nothing pulling", "gain": 1.0, "layers": [
        {"type": "click", "hz": 280, "cycles": 2, "amp": 1.0, "pan": 0.0},
        {"type": "noise", "lo": 120, "hi": 400, "decay_ms": 30, "amp": 0.6, "pan": 0.0},
        {"type": "tone", "hz": 60, "to_hz": 35, "delay_ms": 20, "decay_ms": 90, "amp": 0.5, "pan": 0.0}]},
    "line_slack": {"_doc": "the fish throws the hook: the line goes limp", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 55, "to_hz": 35, "attack_ms": 10, "decay_ms": 120, "amp": 0.45, "pan": 0.0}]},
    "fish_landed": {"_doc": "the fish swings in out of the water", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 60, "hi": 250, "attack_ms": 10, "decay_ms": 90, "amp": 0.5, "pan": 0.0},
        {"type": "tone", "hz": 70, "to_hz": 45, "delay_ms": 60, "decay_ms": 80, "amp": 0.7, "pan": 0.0}]},
    "fish_flop": {"_doc": "a wet slap of the tail in your hand", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 95, "to_hz": 60, "attack_ms": 2, "decay_ms": 35, "amp": 0.6, "pan": 0.0},
        {"type": "noise", "lo": 100, "hi": 300, "decay_ms": 25, "amp": 0.3, "pan": 0.0}]},
}
d = json.loads(txt)
added = [k for k in new if k not in d]
if added:
    body = ",\n".join(f'  "{k}": ' + json.dumps(new[k]) for k in added)
    txt = txt[:-1].rstrip() + ",\n" + body + "\n}\n"
    json.loads(txt)
    hp.write_text(txt, encoding="utf-8")
print("patched; recipes added:", added)
