"""Voice horse commands (calm / whoa) through the game's own actions, the game's calm event as feedback,
table games (five finger fillet, poker, blackjack, dominoes) from their scripts / inputs / Arthur's
animation states, and rain on the hat (off by default)."""
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


if "GET_TASK_MOVE_NETWORK_STATE" not in (SRC / "natives.h").read_text(encoding="utf-8"):
    edit("natives.h", [(
        "inline bool GET_TASK_FISHING(Ped p, void* data)",
        r'''inline int GET_NUMBER_OF_THREADS_RUNNING_THE_SCRIPT_WITH_THIS_HASH(Hash h) { return invoke<int>(0x8E34C953364A76DDull, h); }
inline bool IS_DISABLED_CONTROL_JUST_PRESSED(int pad, Hash a) { return invoke<int>(0x91AEF906BCA88877ull, pad, a) != 0; }
inline bool IS_CONTROL_JUST_PRESSED(int pad, Hash a) { return invoke<int>(0x580417101DDB492Full, pad, a) != 0; }
inline const char* GET_TASK_MOVE_NETWORK_STATE(Ped p) { return invoke<const char*>(0x717E4D1F2048376Dull, p); }
inline Ped GET_LAST_MOUNT(Ped p) { return invoke<Ped>(0x4C8B59171957BCF7ull, p); }
inline Ped GET_ACTIVE_HORSE_FOR_PLAYER(Player p) { return invoke<Ped>(0x46FA0AE18F4C7FA9ull, p); }
inline bool DOES_ENTITY_EXIST(Entity e) { return invoke<int>(0xD42BD6EB2E0F1677ull, e) != 0; }
inline void TASK_ANIMAL_INTERACTION(Ped p, Ped target, Hash type, Hash model, bool skip_idle) {
    invoke<void>(0xCD181A959CFDD7F4ull, p, target, type, model, int(skip_idle));
}
inline float GET_PED_MOTIVATION(Ped p, int state, Ped target) { return invoke<float>(0x42688E94E96FD9B4ull, p, state, target); }
// the game's event queue (group 0 = AI events); data are 8-byte slots
inline int GET_NUMBER_OF_EVENTS(int group) { return invoke<int>(0x5CE8DE5909565748ull, group); }
inline Hash GET_EVENT_AT_INDEX(int group, int i) { return invoke<Hash>(0xA85E614430EFF816ull, group, i); }
inline bool GET_EVENT_DATA(int group, int i, void* data, int slots) { return invoke<int>(0x57EC5FA4D4D6AFCAull, group, i, data, slots) != 0; }
// weather
inline float GET_RAIN_LEVEL() { return invoke<float>(0x931B5F4CC130224Bull); }
inline void GET_CURR_WEATHER_STATE(Hash* a, Hash* b, float* pct) { invoke<void>(0x0AC679B2342F14F2ull, a, b, pct); }
inline bool GET_TASK_FISHING(Ped p, void* data)''')])

edit("world.h", [
    ("enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack, Honor } type;",
     "enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack, Honor, Minigame, Horse } type;"),
    ("    int deadeye_marks = 0;         // targets painted in Dead Eye",
     "    int deadeye_marks = 0;         // targets painted in Dead Eye\n"
     "    int minigame = 0;              // 1 five finger fillet, 2 poker, 3 blackjack, 4 dominoes\n"
     "    float rain = 0;                // 0..1\n"
     "    bool thunder = false, indoors = false;"),
    ("    int marks_logged_ = 0;",
     "    int marks_logged_ = 0;\n"
     "    // voice horse commands\n"
     "    int soothe_frames_ = 0;\n"
     "    double rein_until_ = 0;\n"
     "    // table games\n"
     "    int minigame_ = 0;\n"
     "    double minigame_poll_t_ = 0, tile_at_ = 0;\n"
     "    std::string mg_state_;"),
])

edit("world.cpp", [(
    "    // --- honor: the story scripts count every gain / loss in stats ---",
    r'''    // --- the game's events: the horse calmed / patted (by you or your "easy") ---
    {
        static const Hash kCalmPed = 0x89AB08C3;            // EVENT_CALM_PED: calmer, mount, calm type, fully calmed
        int n_ev = GET_NUMBER_OF_EVENTS(0);
        for (int i = 0; i < n_ev; ++i) {
            if (GET_EVENT_AT_INDEX(0, i) != kCalmPed) continue;
            alignas(8) uint64_t d[4] = {};
            if (!GET_EVENT_DATA(0, i, d, 4) || int(uint32_t(d[0])) != me) continue;
            int type = int(uint32_t(d[2]));
            LOGD("horse calmed (type %d, fully %d)", type, int(uint32_t(d[3])));
            ev.push_back({WorldEvent::Horse, 0, type >= 3 ? 1.0f : 0.7f, "calm"});
        }
    }

    // --- voice: horse commands, through the game's own actions ---
    {
        static const Hash kSoothe = joaat("INPUT_INTERACT_ANIMAL"), kStop = joaat("INPUT_HORSE_STOP");
        int cmd = horse_cmd_.exchange(HorseNone);
        if (cmd == HorseStop) {
            if (horse && s.mount_speed > 0.4f) {
                rein_until_ = s.time + 4.0;
                ev.push_back({WorldEvent::Horse, 0, 1, "rein"});
                LOGI("voice: whoa - reining in at %.1f m/s", s.mount_speed);
            } else {
                LOGI("voice: whoa - not riding a moving horse");
            }
        } else if (cmd == HorseCalm) {
            if (horse) {
                soothe_frames_ = 2;                          // the game's Calm / pat while riding
                LOGI("voice: easy - soothing the horse (agitation %.2f)", GET_PED_MOTIVATION(horse, 3, 0));
            } else {
                Ped h = GET_ACTIVE_HORSE_FOR_PLAYER(pl);
                if (!h) h = GET_LAST_MOUNT(me);
                Vector3 hp = h && DOES_ENTITY_EXIST(h) ? GET_ENTITY_COORDS(h) : Vector3{};
                Vector3 mp = GET_ENTITY_COORDS(me);
                float d = std::hypot(hp.x - mp.x, hp.y - mp.y);
                if (h && DOES_ENTITY_EXIST(h) && !IS_PED_DEAD_OR_DYING(h, true) && d < 3.5f) {
                    TASK_ANIMAL_INTERACTION(me, h, joaat("Interaction_PositiveShort"), 0, false);
                    LOGI("voice: easy - patting the horse");
                } else {
                    LOGI("voice: easy - no horse close enough");
                }
            }
        }
        if (soothe_frames_ > 0) {
            SET_CONTROL_VALUE_NEXT_FRAME(0, kSoothe, 1.0f);
            --soothe_frames_;
        }
        if (s.time < rein_until_) {
            if (horse && s.mount_speed > 0.3f) SET_CONTROL_VALUE_NEXT_FRAME(0, kStop, 1.0f);
            else rein_until_ = 0;
        }
    }

    // --- table games: from the game's scripts, the buttons they read and Arthur's hand animations ---
    if (s.time - minigame_poll_t_ > 0.5) {
        minigame_poll_t_ = s.time;
        static const char* const kGames[] = {"", "fillet_sp", "poker_sp", "bjack_sp", "dominoes_sp"};
        int mg = 0;
        for (int i = 1; i <= 4; ++i)
            if (GET_NUMBER_OF_THREADS_RUNNING_THE_SCRIPT_WITH_THIS_HASH(joaat(kGames[i])) > 0) mg = i;
        if (mg != minigame_) LOGI("table game: %s", mg ? kGames[mg] : "none");
        minigame_ = mg;
    }
    s.minigame = minigame_;
    if (minigame_) {
        auto pressed = [](const char* in) {
            Hash a = joaat(in);
            return IS_DISABLED_CONTROL_JUST_PRESSED(0, a) || IS_CONTROL_JUST_PRESSED(0, a);
        };
        auto push = [&](const char* what) { ev.push_back({WorldEvent::Minigame, 0, 1, what}); };
        if (minigame_ == 1) {
            for (const char* k : {"INPUT_MINIGAME_FFF_A", "INPUT_MINIGAME_FFF_B", "INPUT_MINIGAME_FFF_X", "INPUT_MINIGAME_FFF_Y"})
                if (pressed(k)) push("knife");
        } else if (minigame_ == 4 && pressed("INPUT_MINIGAME_DOMINOES_PLAY_TILE")) {
            tile_at_ = s.time + 0.35;                         // the tile reaches the table
        }
        const char* st = GET_TASK_MOVE_NETWORK_STATE(me);
        std::string state = st ? st : "";
        if (state != mg_state_) {
            LOGD("table game: Arthur's hands -> %s", state.c_str());
            auto has = [&](const char* w) { return state.find(w) != std::string::npos; };
            if (minigame_ == 1) {
                if (has("Fail")) push("knife_miss");
            } else if (minigame_ == 2 || minigame_ == 3) {
                if (has("Shuffle")) push("riffle");
                else if (has("Bet")) push("chips");
                else if (state == "Check" || has("Hit")) push("knock");
                else if (has("Fold") || has("Reveal") || has("Peek") || has("HoldCards") || has("Deck") || has("Take") ||
                         has("Flop") || has("Turn") || has("River"))
                    push("card");
            }
            mg_state_ = state;
        }
        if (tile_at_ > 0 && s.time >= tile_at_) {
            push("tile");
            tile_at_ = 0;
        }
    } else {
        mg_state_.clear();
    }

    // --- weather on the hat ---
    s.rain = GET_RAIN_LEVEL();
    {
        Hash w1 = 0, w2 = 0;
        float pct = 0;
        GET_CURR_WEATHER_STATE(&w1, &w2, &pct);
        Hash wt = pct > 0.5f ? w2 : w1;
        s.thunder = wt == joaat("THUNDER") || wt == joaat("THUNDERSTORM") || wt == joaat("HURRICANE");
        s.indoors = GET_INTERIOR_FROM_ENTITY(me) != 0;
    }

    // --- honor: the story scripts count every gain / loss in stats ---''')])

# ---------- features ----------
edit("features.h", [("    double honor_until_ = 0;",
                     "    double honor_until_ = 0;\n"
                     "    float minigame_gain_ = 0.7f, weather_gain_ = 0;\n"
                     "    double next_drop_ = 0, next_thunder_ = 0;")])
edit("features.cpp", [
    ("    action_gain_ = c.num(\"Haptics\", \"Actions\", 0.5f);",
     "    action_gain_ = c.num(\"Haptics\", \"Actions\", 0.5f);\n"
     "    minigame_gain_ = c.num(\"Haptics\", \"TableGames\", 0.7f);\n"
     "    weather_gain_ = c.num(\"Haptics\", \"Weather\", 0.0f);"),
    ("""        } else if (e.type == WorldEvent::Honor) {""",
     """        } else if (e.type == WorldEvent::Minigame && minigame_gain_ > 0) {
            static const std::map<std::string, std::string> kCue = {
                {"knife", "knife_tap"}, {"knife_miss", "knife_finger"}, {"chips", "chips"}, {"knock", "knock"},
                {"card", "card_slide"}, {"riffle", "card_riffle"}, {"tile", "domino_clack"}};
            auto it = kCue.find(e.cause);
            if (it != kCue.end()) cues.push_back(make(it->second, minigame_gain_));
            if (e.cause == "knife_miss") {                    // the blade finds a finger
                damage_flash_ = 0.8f;
                damage_flash_until_ = now + 0.25;
            }
        } else if (e.type == WorldEvent::Horse) {
            float g = config().num("Mic", "Confirm", 1.0f);
            cues.push_back(make(e.cause == "rein" ? "rein_pull" : "horse_pat", g * e.strength));
        } else if (e.type == WorldEvent::Honor) {"""),
    ("""    if (!g.blocked) {
        if (g.holstering && !was_holstering_ && action_gain_ > 0) {""",
     """    if (!g.blocked && weather_gain_ > 0 && !g.indoors) {             // rain on the hat, thunder far off
        if (g.rain > 0.05f && now >= next_drop_) {
            next_drop_ = now + rng_.range(0.3f, 1.7f) / (3.0f + 30.0f * g.rain);
            cues.push_back(make("rain_drop", weather_gain_ * rng_.range(0.3f, 1.0f), rng_.range(-0.8f, 0.8f), true));
        }
        if (g.thunder && now >= next_thunder_) {
            if (next_thunder_ > 0) cues.push_back(make("thunder_far", weather_gain_ * rng_.range(0.5f, 1.0f)));
            next_thunder_ = now + rng_.range(15.0f, 50.0f);
        }
    }
    if (!g.blocked) {
        if (g.holstering && !was_holstering_ && action_gain_ > 0) {"""),
])
edit("config.cpp", [(
    "; Grabbing a ledge, opening a door, drawing / holstering a gun\nActions=0.5\n",
    "; Grabbing a ledge, opening a door, drawing / holstering a gun\nActions=0.5\n"
    "; Five finger fillet (knife taps, the miss), poker / blackjack chips and cards, dominoes tiles\n"
    "TableGames=0.7\n"
    "; Rain drops on the hat and far thunder (0 = off: they are weather, not Arthur)\n"
    "Weather=0\n")])

# ---------- recipes ----------
hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
txt = hp.read_text(encoding="utf-8").rstrip()
new = {
    "knife_tap": {"_doc": "the knife point stabs into the table between the fingers", "gain": 1.0, "layers": [
        {"type": "click", "hz": 260, "cycles": 1, "amp": 0.8, "pan": 0.6},
        {"type": "tone", "hz": 110, "to_hz": 80, "decay_ms": 22, "amp": 0.5, "pan": 0.6}]},
    "knife_finger": {"_doc": "a miss: the blade nicks a finger - a sharp jab", "gain": 1.0, "layers": [
        {"type": "click", "hz": 300, "cycles": 2, "amp": 1.0, "pan": -0.6},
        {"type": "noise", "lo": 150, "hi": 450, "decay_ms": 40, "amp": 0.6, "pan": -0.6},
        {"type": "tone", "hz": 70, "to_hz": 45, "delay_ms": 15, "decay_ms": 120, "amp": 0.6, "pan": -0.6}]},
    "chips": {"_doc": "a small stack of chips pushed in, clicking", "gain": 1.0, "layers": [
        {"type": "click", "hz": 330, "cycles": 1, "amp": 0.5, "pan": 0.4},
        {"type": "click", "hz": 310, "cycles": 1, "delay_ms": 45, "amp": 0.45, "pan": 0.4},
        {"type": "click", "hz": 340, "cycles": 1, "delay_ms": 85, "amp": 0.4, "pan": 0.4}]},
    "knock": {"_doc": "two knuckle raps on the table", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 120, "to_hz": 90, "decay_ms": 25, "amp": 0.6, "pan": 0.5},
        {"type": "tone", "hz": 120, "to_hz": 90, "delay_ms": 140, "decay_ms": 25, "amp": 0.55, "pan": 0.5}]},
    "card_slide": {"_doc": "a card slid over felt", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 120, "hi": 380, "attack_ms": 20, "decay_ms": 60, "amp": 0.3, "pan": 0.3}]},
    "card_riffle": {"_doc": "a riffle shuffle: a fast run of card edges", "gain": 1.0, "layers": [
        {"type": "click", "hz": 360, "cycles": 1, "delay_ms": d, "amp": 0.25, "pan": (-0.4 if i % 2 else 0.4)}
        for i, d in enumerate(range(0, 360, 30))]},
    "domino_clack": {"_doc": "a domino tile set down against the others", "gain": 1.0, "layers": [
        {"type": "click", "hz": 280, "cycles": 1, "amp": 0.7, "pan": 0.4},
        {"type": "click", "hz": 250, "cycles": 1, "delay_ms": 35, "amp": 0.35, "pan": 0.4}]},
    "horse_pat": {"_doc": "your palm on the horse's neck: two soft pats", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 65, "to_hz": 50, "attack_ms": 8, "decay_ms": 60, "amp": 0.5, "pan": 0.0},
        {"type": "tone", "hz": 65, "to_hz": 50, "delay_ms": 260, "attack_ms": 8, "decay_ms": 60, "amp": 0.45, "pan": 0.0}]},
    "rein_pull": {"_doc": "the reins drawn back", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 60, "hi": 180, "attack_ms": 60, "decay_ms": 150, "amp": 0.45, "pan": 0.0},
        {"type": "tone", "hz": 50, "attack_ms": 60, "decay_ms": 160, "amp": 0.4, "pan": 0.0}]},
    "rain_drop": {"_doc": "one drop on the hat brim", "gain": 1.0, "layers": [
        {"type": "click", "hz": 380, "cycles": 1, "amp": 0.3, "pan": 0.0}]},
    "thunder_far": {"_doc": "thunder rolling far away", "gain": 1.0, "layers": [
        {"type": "noise", "lo": 25, "hi": 80, "attack_ms": 400, "decay_ms": 1800, "amp": 0.5, "pan": 0.0}]},
}
d = json.loads(txt)
added = [k for k in new if k not in d]
if added:
    body = ",\n".join(f'  "{k}": ' + json.dumps(new[k]) for k in added)
    txt = txt[:-1].rstrip() + ",\n" + body + "\n}\n"
    json.loads(txt)
    hp.write_text(txt, encoding="utf-8")
print("patched; recipes added:", added)
