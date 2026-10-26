"""Real (honor-counting) greeting through the game's own interaction actions, speech-only fallback."""
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


edit("natives.h", [(
    "inline bool IS_CONTROL_PRESSED(int pad, Hash action)",
    """// simulate a game action (not a physical button) for the next frame; value 0..1
inline bool SET_CONTROL_VALUE_NEXT_FRAME(int pad, Hash action, float value) { return invoke<int>(0xE8A25867FBA3B05Eull, pad, action, value) != 0; }
inline bool GET_PLAYER_INTERACTION_TARGET_ENTITY(Player p, Entity* e) { return invoke<int>(0x3EE1F7A8C32F24E1ull, p, e, 0, 0) != 0; }
inline bool UI_PROMPT_IS_CONTROL_ACTION_ACTIVE(Hash action) { return invoke<int>(0x1BE19185B8AFE299ull, action) != 0; }
inline bool IS_CONTROL_PRESSED(int pad, Hash action)""")])

edit("world.h", [(
    """    int reply_target_ = 0;
    double reply_at_ = 0, last_greet_ = -10;""",
    """    void speech_greet(int me, int target, const GameSnapshot& s, std::vector<WorldEvent>& ev);
    int reply_target_ = 0;
    double reply_at_ = 0, last_greet_ = -10;
    // real greeting through the game's interaction actions (counts for honor)
    enum class Greet { Idle, Turn, Lock, Press, Hold } greet_ = Greet::Idle;
    int greet_target_ = 0;
    double greet_t_ = 0, lock_t_ = 0;
    float greet_from_ = 0;
    int press_frames_ = 0;""")])

p = SRC / "world.cpp"
s = p.read_text(encoding="utf-8")
start = s.index("void World::greet(int pl, int me")
end = s.index("void World::tick() {")
new = r'''// Arthur greets `target` with voice lines only (no honor): the fallback when the real interaction fails.
void World::speech_greet(int me, int target, const GameSnapshot& s, std::vector<WorldEvent>& ev) {
    using namespace nat;
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
    LOGI("greeting (voice only, no honor): Arthur says %s", used.c_str());
    TASK_LOOK_AT_ENTITY(target, me, 3500);
    reply_target_ = target;
    reply_at_ = s.time + 1.4;
    ev.push_back({WorldEvent::Ack, 0, 0.5f, "speech"});
}

// Say the phrase: the real greeting, as if you focused the person and chose Greet - it counts for honor.
// Everything goes through the game's own interaction actions (never aim, never a raw button):
//   turn the camera to the person -> request interaction focus -> once the game has focused them and
//   shows the Greet prompt, trigger the Greet action -> let go. Nothing else can be triggered: if the
//   focus doesn't happen, or you start aiming, it stops (and Arthur just says hello, without honor).
void World::greet(int pl, int me, float px, float py, const int* peds, int n, const GameSnapshot& s,
                  std::vector<WorldEvent>& ev) {
    using namespace nat;
    static const Hash kLockOn = joaat("INPUT_INTERACT_LOCKON");
    static const Hash kGreet = joaat("INPUT_INTERACT_LOCKON_POS");
    double now = s.time;
    if (reply_target_ && now >= reply_at_) {           // speech fallback: the other person answers
        int t = reply_target_;
        reply_target_ = 0;
        std::string used;
        if (!IS_PED_DEAD_OR_DYING(t) && speak(t, {"GREET_GENERAL_STRANGER", "GREET_GENERAL"}, me, &used))
            LOGI("greeting: they answered (%s)", used.c_str());
    }
    bool requested = greet_requested_.exchange(false);
    auto fail = [&](const char* why) {
        LOGI("greeting: %s", why);
        int t = greet_target_;
        greet_ = Greet::Idle;
        if (t && config().flag("Voice", "SpeechFallback", true) && !IS_PED_DEAD_OR_DYING(t)) speech_greet(me, t, s, ev);
    };
    if (greet_ != Greet::Idle && (s.blocked || IS_PLAYER_FREE_AIMING(pl))) {
        greet_ = Greet::Idle;
        LOGI("greeting: cancelled (aiming / menu)");
        return;
    }
    if (requested && greet_ == Greet::Idle) {
        if (s.blocked) { LOGI("greeting: not now (menu / cutscene / no control)"); return; }
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
            float score = d + std::fabs(wrap180(bearing - cam)) / 45.0f;
            if (score < best) { best = score; target = p; }
        }
        if (!target) { LOGI("greeting: nobody close enough"); return; }
        last_greet_ = now;
        greet_target_ = target;
        greet_ = s.armed ? Greet::Idle : Greet::Turn;
        if (s.armed) { fail("weapon in hand - the game only greets with it holstered"); return; }
        greet_t_ = now;
        greet_from_ = GET_GAMEPLAY_CAM_RELATIVE_HEADING();
    }
    if (greet_ == Greet::Idle) return;
    Vector3 q = GET_ENTITY_COORDS(greet_target_);
    float want = wrap180(std::atan2(-(q.x - px), q.y - py) * 180.0f / kPi - GET_ENTITY_HEADING(me));
    switch (greet_) {
    case Greet::Turn: {                                   // smooth camera turn onto them (~0.25 s)
        float k = clampv(float(now - greet_t_) / 0.25f, 0.0f, 1.0f);
        k = k * k * (3 - 2 * k);
        SET_GAMEPLAY_CAM_RELATIVE_HEADING(greet_from_ + wrap180(want - greet_from_) * k);
        if (k >= 1.0f) { greet_ = Greet::Lock; greet_t_ = now; lock_t_ = 0; }
        break;
    }
    case Greet::Lock: {                                   // hold "interaction focus" until the game focuses them
        SET_CONTROL_VALUE_NEXT_FRAME(0, kLockOn, 1.0f);
        Entity t = 0;
        bool locked = (GET_PLAYER_INTERACTION_TARGET_ENTITY(pl, &t) || GET_PLAYER_TARGET_ENTITY(pl, &t)) && t &&
                      IS_ENTITY_A_PED(t) && IS_PED_HUMAN(t);
        if (locked && !lock_t_) { lock_t_ = now; greet_target_ = t; }
        bool prompt = UI_PROMPT_IS_CONTROL_ACTION_ACTIVE(kGreet);
        if (lock_t_ && now - lock_t_ > 0.25 && prompt) { greet_ = Greet::Press; press_frames_ = 0; }
        else if (now - greet_t_ > 1.2) fail(locked ? "focused, but no Greet prompt appeared" : "could not focus them");
        break;
    }
    case Greet::Press:                                    // the Greet action for a few frames
        SET_CONTROL_VALUE_NEXT_FRAME(0, kLockOn, 1.0f);
        SET_CONTROL_VALUE_NEXT_FRAME(0, kGreet, 1.0f);
        if (++press_frames_ >= 3) {
            greet_ = Greet::Hold;
            greet_t_ = now;
            LOGI("greeting: real greet (counts for honor)");
            ev.push_back({WorldEvent::Ack, 0, 1, "real"});
        }
        break;
    case Greet::Hold:                                     // keep focus while Arthur talks, then let go
        SET_CONTROL_VALUE_NEXT_FRAME(0, kLockOn, 1.0f);
        if (now - greet_t_ > 0.6) greet_ = Greet::Idle;
        break;
    default:
        break;
    }
}

'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding="utf-8")

# features: real greet = two thumps, voice-only fallback = one soft thump
edit("features.cpp", [(
    """        } else if (e.type == WorldEvent::Ack) {
            cues.push_back(make("whistle_ack", config().num("Mic", "Confirm", 1.0f)));""",
    """        } else if (e.type == WorldEvent::Ack) {
            float g = config().num("Mic", "Confirm", 1.0f);
            cues.push_back(make(e.cause == "speech" ? "hit_confirm" : "whistle_ack", e.cause == "speech" ? g * 2.5f : g));""")])

edit("config.cpp", [(
    """; Say the phrase into the controller: Arthur looks at the closest person (within Range metres) and
; greets them, they look back and answer. Speech only - no buttons are pressed. Two thumps confirm it.""",
    """; Say the phrase into the controller: the camera turns to the closest person (within Range metres) and
; Arthur greets them for real - exactly like focusing them and choosing Greet, so it counts for honor.
; Only the game's own focus + Greet actions are used: it can never aim, draw or attack. Two thumps = done.
; Gun must be holstered. If the game won't focus them, Arthur just says hello (one soft thump, no honor).""")])
edit("config.cpp", [("MinConfidence=0.35\n", "MinConfidence=0.35\n; If the real greeting fails, Arthur still says a greeting line (no honor)\nSpeechFallback=1\n")])
print("patched")
