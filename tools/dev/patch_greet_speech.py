"""Greeting by speech natives (no input at all), weapon-wheel pause, hoof fallback + stats, quieter steps."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "mod" / "src"


def edit(name, pairs):
    p = SRC / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:90]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


# ---------------- natives ----------------
edit("natives.h", [(
    "// on-screen text (the surface teaching note)",
    """// speech and looking (greeting)
struct ScriptedSpeechParams {
    const char* speechName;
    const char* voiceName;
    alignas(8) int variation;
    alignas(8) Hash speechParamHash;
    alignas(8) Ped listenerPed;
    alignas(8) int syncOverNetwork;
    alignas(8) int v7;
    alignas(8) int v8;
};
static_assert(sizeof(ScriptedSpeechParams) == 0x40, "ScriptedSpeechParams size");
inline bool PLAY_PED_AMBIENT_SPEECH_NATIVE(Ped speaker, ScriptedSpeechParams* p) { return invoke<int>(0x8E04FEDD28D42462ull, speaker, p) != 0; }
inline bool IS_AMBIENT_SPEECH_PLAYING(Ped p) { return invoke<int>(0x9072C8B49907BFADull, p) != 0; }
inline void TASK_LOOK_AT_ENTITY(Ped p, Entity target, int ms) { invoke<void>(0x69F4BE8C8CC4796Cull, p, target, ms, 2048, 3, 0); }
inline bool IS_PED_MALE(Ped p) { return invoke<int>(0x6D9F5FAA7488BA46ull, p) != 0; }
inline bool IS_CONTROL_PRESSED(int pad, Hash action) { return invoke<int>(0xF3A21BCD95725A4Aull, pad, action) != 0; }
inline bool IS_DISABLED_CONTROL_PRESSED(int pad, Hash action) { return invoke<int>(0xE2587F8CBBD87B1Dull, pad, action) != 0; }

// on-screen text (the surface teaching note)""")])

# ---------------- world.h ----------------
edit("world.h", [
    ("    bool lantern = false;", "    bool lantern = false;\n    bool wheel = false;            // weapon / item wheel open"),
    ("""    std::atomic<bool> greet_requested_{false};
    enum class Greet { Idle, Turn, Focus, Done } greet_ = Greet::Idle;
    int greet_target_ = 0;
    double greet_t_ = 0, focus_t_ = 0;
    float greet_from_ = 0;""", """    bool speak(int ped, const std::vector<std::string>& lines, int listener, std::string* used);
    std::atomic<bool> greet_requested_{false};
    int reply_target_ = 0;
    double reply_at_ = 0, last_greet_ = -10;"""),
    ("""    void tick();                                     // script thread, every frame""",
     """    void tick();                                     // script thread, every frame
    // hoof diagnostics (debug log)
    int hoof_plants_ = 0;
    double hoof_stat_t_ = 0;"""),
])

# ---------------- world.cpp: replace the greet() function ----------------
p = SRC / "world.cpp"
s = p.read_text(encoding="utf-8")
start = s.index("// Say \"howdy\":")
end = s.index("void World::tick() {")
new_greet = r'''// Say the phrase: Arthur turns his head to the closest person and says a greeting line, they look
// back and answer. Only speech - no buttons are pressed, so it can never do anything but greet.
bool World::speak(int ped, const std::vector<std::string>& lines, int listener, std::string* used) {
    using namespace nat;
    for (const auto& line : lines) {
        for (Hash param : {joaat("SPEECH_PARAMS_FORCE"), joaat("SPEECH_PARAMS_STANDARD"), Hash(0)}) {
            ScriptedSpeechParams sp{line.c_str(), nullptr, 0, param, listener, 0, 1, 1};
            if (PLAY_PED_AMBIENT_SPEECH_NATIVE(ped, &sp)) {
                if (used) *used = line;
                return true;
            }
        }
    }
    return false;
}

void World::greet(int pl, int me, float px, float py, const int* peds, int n, const GameSnapshot& s,
                  std::vector<WorldEvent>& ev) {
    using namespace nat;
    (void)pl;
    double now = s.time;
    // the other person answers a moment later
    if (reply_target_ && now >= reply_at_) {
        int t = reply_target_;
        reply_target_ = 0;
        if (!IS_PED_DEAD_OR_DYING(t)) {
            std::string used;
            bool male = IS_PED_MALE(me);
            if (speak(t, {"GREET_GENERAL_STRANGER", male ? "GREET_MALE" : "GREET_FEMALE", "GREET_GENERAL"}, me, &used))
                LOGI("greeting: they answered (%s)", used.c_str());
        }
    }
    if (!greet_requested_.exchange(false)) return;
    if (s.blocked) {
        LOGI("greeting: not now (menu / cutscene / no control)");
        return;
    }
    if (now - last_greet_ < 2.0) return;
    float range = config().num("Voice", "Range", 6.0f);
    float cam = GET_GAMEPLAY_CAM_ROT().z;
    int target = 0;
    float best = 1e9f;
    for (int i = 0; i < n; ++i) {
        int p = peds[i];
        if (!p || p == me || !IS_PED_HUMAN(p) || IS_PED_DEAD_OR_DYING(p)) continue;
        Vector3 q = GET_ENTITY_COORDS(p);
        float dx = q.x - px, dy = q.y - py, d = std::sqrt(dx * dx + dy * dy);
        if (d > range) continue;
        float bearing = std::atan2(-dx, dy) * 180.0f / kPi;
        float score = d + std::fabs(wrap180(bearing - cam)) / 45.0f;     // prefer who you're looking at
        if (score < best) { best = score; target = p; }
    }
    if (!target) {
        LOGI("greeting: nobody close enough");
        return;
    }
    last_greet_ = now;
    TASK_LOOK_AT_ENTITY(me, target, 3000);
    bool male = IS_PED_MALE(target);
    int h = s.hour;
    std::vector<std::string> lines;
    if (h >= 5 && h < 12) lines.push_back(male ? "GREET_MORNING_MALE" : "GREET_MORNING_FEMALE");
    if (h >= 18 && h < 23) lines.push_back(male ? "GREET_EVENING_MALE" : "GREET_EVENING_FEMALE");
    lines.push_back(male ? "GREET_MALE" : "GREET_FEMALE");
    lines.push_back("GREET_GENERAL");
    std::string used;
    if (!speak(me, lines, target, &used)) {
        LOGI("greeting: the game refused every greeting line");
        return;
    }
    LOGI("greeting: Arthur says %s", used.c_str());
    TASK_LOOK_AT_ENTITY(target, me, 3500);
    reply_target_ = target;
    reply_at_ = now + 1.4;
    ev.push_back({WorldEvent::Ack, 0, 1, ""});
}

'''
s = s[:start] + new_greet + s[end:]

# weapon wheel state + hoof stats
s = s.replace("""    s.reloading = IS_PED_RELOADING(me);""", """    s.reloading = IS_PED_RELOADING(me);
    static const Hash kWheel = joaat("INPUT_OPEN_WHEEL_MENU");
    s.wheel = IS_CONTROL_PRESSED(0, kWheel) || IS_DISABLED_CONTROL_PRESSED(0, kWheel);""", 1)
s = s.replace("""        if (s.hoof_bones) steps(horse, hooves_, hoof_count_, s.mount_speed, s.time, true, ev);""",
              """        size_t before = ev.size();
        if (s.hoof_bones) steps(horse, hooves_, hoof_count_, s.mount_speed, s.time, true, ev);
        hoof_plants_ += int(ev.size() - before);
        if (log::debug_enabled() && s.time - hoof_stat_t_ > 3.0) {
            if (s.mount_speed > 1.0f)
                LOGD("hooves: speed %.1f m/s, %.1f plants/s detected", s.mount_speed, hoof_plants_ / (s.time - hoof_stat_t_));
            hoof_plants_ = 0;
            hoof_stat_t_ = s.time;
        }""", 1)
p.write_text(s, encoding="utf-8")

# ---------------- features: hoof fallback when the legs go quiet at speed, quieter defaults ----------------
edit("features.cpp", [
    ("""    // fallback when the horse's leg bones were not found: hooves from the gait
    if (!g.hoof_bones && stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {""",
     """    // fallback: no leg bones, or the legs went quiet at speed (detection misses fast gaits)
    bool legs_quiet = now - last_hoof_event_ > 0.45;
    if ((!g.hoof_bones || legs_quiet) && stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {"""),
    ("""        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0) {""",
     """        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0) {
            last_hoof_event_ = now;"""),
    ("""    horse_gain_ = c.num("Haptics", "Horse", 0.5f);""", """    horse_gain_ = c.num("Haptics", "Horse", 0.3f);"""),
    ("""    step_gain_ = c.num("Haptics", "Footsteps", 0.4f);""", """    step_gain_ = c.num("Haptics", "Footsteps", 0.22f);"""),
])
edit("features.h", [("    bool rearing_ = false;", "    bool rearing_ = false;\n    double last_hoof_event_ = -10;")])

# walking much lighter than running (background texture, not thumps)
edit("world.cpp", [(
    """                                   : clampv(sp < 2.2f ? 0.45f : sp < 4.8f ? 0.7f : 0.9f, 0.3f, 1.0f) * step_strength_;""",
    """                                   : clampv(sp < 2.2f ? 0.35f : sp < 4.8f ? 0.6f : 0.8f, 0.2f, 1.0f) * step_strength_;""")])

# ---------------- core: weapon wheel pause ----------------
edit("core.h", [("    bool pad_was_connected_ = false, pad_seen_ = false;",
                 "    bool pad_was_connected_ = false, pad_seen_ = false;\n    double l1_since_ = -1, wheel_until_ = 0;\n    bool need_r2_release_ = false;")])
edit("core.cpp", [(
    """    EngineFrame frame;
    bool weapon_active = engine_ && triggers_on_ && !(in_game_ && (g.blocked || g.swimming));
    if (engine_) frame = engine_->update(s, h);""",
    """    // weapon / item wheel: L2/R2 switch weapons there - not shots. Pause the trigger engine while it is
    // open (L1 held, or the game says so) and until R2 has been let go afterwards.
    if (s.pressed(L1)) { if (l1_since_ < 0) l1_since_ = s.t; } else l1_since_ = -1;
    bool wheel = (l1_since_ >= 0 && s.t - l1_since_ > 0.12) || (in_game_ && g.wheel);
    if (wheel) { wheel_until_ = s.t + 0.25; need_r2_release_ = true; }
    if (need_r2_release_ && s.t > wheel_until_ && s.r2 < 25) need_r2_release_ = false;
    bool paused = s.t < wheel_until_ || need_r2_release_;
    EngineFrame frame;
    bool weapon_active = engine_ && triggers_on_ && !paused && !(in_game_ && (g.blocked || g.swimming));
    if (engine_ && !paused) frame = engine_->update(s, h);""")])

# ---------------- config ----------------
edit("config.cpp", [
    ("Footsteps=0.4\n", "Footsteps=0.22\n"),
    ("; Hoofbeats by gait and ground, horse's heartbeat when it is exhausted\nHorse=0.5",
     "; Hoofbeats by gait and ground, horse's heartbeat when it is exhausted\nHorse=0.3"),
    ("""; Say the phrase into the controller: Arthur turns to the closest person (within Range metres),
; focuses them and greets them. Your gun must be holstered. Two knocks confirm it.""",
     """; Say the phrase into the controller: Arthur looks at the closest person (within Range metres) and
; greets them, they look back and answer. Speech only - no buttons are pressed. Two thumps confirm it."""),
    ("""; Button that greets while someone is focused: Y (Triangle) or X (Square)
GreetButton=Y
""", ""),
])
print("patched")
