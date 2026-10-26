"""One-off patch: voice greeting - turn the camera to the nearest person, focus (L2), greet, confirm."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "mod" / "src"


def edit(name, pairs):
    p = ROOT / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:80]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


edit("natives.h", [(
    "inline bool IS_PLAYER_TARGETTING_ANYTHING(Player p)",
    "inline bool GET_PLAYER_TARGET_ENTITY(Player p, Entity* e) { return invoke<int>(0xAE663DDD99C8A670ull, p, e) != 0; }\n"
    "inline bool IS_PLAYER_TARGETTING_ANYTHING(Player p)")])

edit("world.h", [
    ("    enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door } type;",
     "    enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack } type;"),
    ("    void add_gyro(float yaw_deg, float pitch_deg);",
     "    void add_gyro(float yaw_deg, float pitch_deg);\n"
     "    void request_greet() { greet_requested_ = true; }   // any thread (voice recognizer)"),
    ("    std::set<uint32_t> logged_materials_;",
     "    std::set<uint32_t> logged_materials_;\n"
     "    // voice greeting\n"
     "    void greet(int pl, int me, float px, float py, const int* peds, int n, const GameSnapshot& s,\n"
     "               std::vector<WorldEvent>& ev);\n"
     "    std::atomic<bool> greet_requested_{false};\n"
     "    enum class Greet { Idle, Turn, Focus, Done } greet_ = Greet::Idle;\n"
     "    int greet_target_ = 0;\n"
     "    double greet_t_ = 0, focus_t_ = 0;\n"
     "    float greet_from_ = 0;"),
])

edit("world.cpp", [
    ('#include "natives.h"\n', '#include "input.h"\n#include "natives.h"\n'),
    ("void World::tick() {", r'''static float wrap180(float a) {
    while (a > 180) a -= 360;
    while (a < -180) a += 360;
    return a;
}

// Say "howdy": the camera turns to the closest person in reach, the mod holds L2 to focus them,
// presses Greet once the game has focused a person, lets go. Nothing is pressed if no one gets focused.
void World::greet(int pl, int me, float px, float py, const int* peds, int n, const GameSnapshot& s,
                  std::vector<WorldEvent>& ev) {
    using namespace nat;
    Config& cfg = config();
    double now = s.time;
    bool requested = greet_requested_.exchange(false);
    auto abort = [&](const char* why) {
        if (greet_ != Greet::Idle) input().hold_lt(0);
        greet_ = Greet::Idle;
        if (why) LOGI("greeting: %s", why);
    };
    if (s.blocked) {
        if (greet_ != Greet::Idle || requested) abort("not now (menu / cutscene / no control)");
        return;
    }
    if (requested && greet_ == Greet::Idle) {
        if (s.armed) {
            abort("holster your gun first - RDR2 does not greet with a weapon out");
            return;
        }
        float range = cfg.num("Voice", "Range", 6.0f);
        float cam = GET_GAMEPLAY_CAM_ROT().z;
        int best = 0;
        float best_score = 1e9f;
        for (int i = 0; i < n; ++i) {
            int p = peds[i];
            if (!p || p == me || !IS_PED_HUMAN(p) || IS_PED_DEAD_OR_DYING(p)) continue;
            Vector3 q = GET_ENTITY_COORDS(p);
            float dx = q.x - px, dy = q.y - py, d = std::sqrt(dx * dx + dy * dy);
            if (d > range) continue;
            float bearing = std::atan2(-dx, dy) * 180.0f / kPi;
            float score = d + std::fabs(wrap180(bearing - cam)) / 45.0f;     // prefer who you're looking at
            if (score < best_score) { best_score = score; best = p; }
        }
        if (!best) {
            abort("nobody close enough");
            return;
        }
        greet_target_ = best;
        greet_ = Greet::Turn;
        greet_t_ = now;
        greet_from_ = GET_GAMEPLAY_CAM_RELATIVE_HEADING();
    }
    if (greet_ == Greet::Idle) return;
    Vector3 q = GET_ENTITY_COORDS(greet_target_);
    float bearing = std::atan2(-(q.x - px), q.y - py) * 180.0f / kPi;
    float want = wrap180(bearing - GET_ENTITY_HEADING(me));
    if (greet_ == Greet::Turn) {
        // smooth turn of the camera onto them (~0.25 s)
        float k = clampv(float(now - greet_t_) / 0.25f, 0.0f, 1.0f);
        k = k * k * (3 - 2 * k);
        SET_GAMEPLAY_CAM_RELATIVE_HEADING(greet_from_ + wrap180(want - greet_from_) * k);
        if (k >= 1.0f) {
            input().hold_lt(2.0);
            greet_ = Greet::Focus;
            greet_t_ = now;
            focus_t_ = 0;
        }
        return;
    }
    if (greet_ == Greet::Focus) {
        Entity t = 0;
        bool focused = GET_PLAYER_TARGET_ENTITY(pl, &t) && t && IS_ENTITY_A_PED(t) && IS_PED_HUMAN(t);
        if (focused && focus_t_ == 0) focus_t_ = now;
        if (focus_t_ > 0 && now - focus_t_ >= 0.3) {          // the Greet prompt is up
            input().inject(xbutton_from_name(cfg.str("Voice", "GreetButton", "Y")), 0.15);
            ev.push_back({WorldEvent::Ack, 0, 1, ""});
            LOGI("greeting: done");
            greet_ = Greet::Done;
            greet_t_ = now;
        } else if (focus_t_ == 0 && now - greet_t_ > 0.9) {
            abort("could not focus them - nothing pressed");
        }
        return;
    }
    if (greet_ == Greet::Done && now - greet_t_ > 0.5) {
        input().hold_lt(0);
        greet_ = Greet::Idle;
    }
}

void World::tick() {'''),
    ("    ped_health_.swap(seen);",
     "    ped_health_.swap(seen);\n    greet(pl, me, pos.x, pos.y, peds, n, s, ev);"),
])
print("greeting patched")
