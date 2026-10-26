"""Honor feedback (the story scripts' HONOR_* stats) and Dead Eye marks / volley shots from the game."""
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


if "STAT_ID_GET_INT" not in (SRC / "natives.h").read_text(encoding="utf-8"):
  edit("natives.h", [(
    "inline bool GET_TASK_FISHING(Ped p, void* data)",
    r'''// stats: honor lives in the story scripts' HONOR_* stats (written on every honor change)
struct StatId { alignas(8) Hash base; alignas(8) Hash permutation; };
inline bool STAT_ID_GET_INT(StatId* id, int* out) { return invoke<int>(0x767FBC2AC802EF3Eull, id, out) != 0; }
inline int GET_NUM_MARKED_DEADEYE_TARGETS(Player p) { return invoke<int>(0xCCD9B77F70D31C9Dull, p); }
inline bool GET_TASK_FISHING(Ped p, void* data)''')])

edit("world.h", [
    ("enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack } type;",
     "enum Type { Damage, Gunfire, HitConfirm, Footstep, Hoof, Land, Climb, Door, Ack, Honor } type;"),
    ("    FishingState fishing;", "    FishingState fishing;\n    int deadeye_marks = 0;         // targets painted in Dead Eye"),
    ("    int fish_log_state_ = -1;",
     "    int fish_log_state_ = -1;\n"
     "    // honor (story-mode stats)\n"
     "    double honor_poll_t_ = 0;\n"
     "    int honor_ = 0, honor_pos_ = -1, honor_neg_ = -1;\n"
     "    bool honor_ok_ = false, honor_logged_ = false;\n"
     "    int marks_logged_ = 0;"),
])
edit("world.cpp", [
    ("    s.reloading = IS_PED_RELOADING(me);",
     r'''    s.deadeye_marks = s.dead_eye ? GET_NUM_MARKED_DEADEYE_TARGETS(pl) : 0;
    if (s.deadeye_marks != marks_logged_) {
        LOGD("dead eye: %d marked", s.deadeye_marks);
        marks_logged_ = s.deadeye_marks;
    }
    s.reloading = IS_PED_RELOADING(me);'''),
    ("    // --- the surface under you: F10 shows what it is, F10 again (while shown) changes it ---",
     r'''    // --- honor: the story scripts count every gain / loss in stats ---
    if (s.time - honor_poll_t_ > 0.2) {
        honor_poll_t_ = s.time;
        auto stat = [](const char* name, int* v) {
            StatId id{joaat(name), 0};
            return STAT_ID_GET_INT(&id, v);
        };
        int cur = 0, pos = 0, neg = 0;
        bool ok = stat("HONOR_CURRENT", &cur) & stat("HONOR_POSITIVE_TOTAL", &pos) & stat("HONOR_NEGATIVE_TOTAL", &neg);
        if (ok && !honor_logged_) {
            LOGI("honor: %d (%d gains, %d losses so far)", cur, pos, neg);
            honor_logged_ = true;
        } else if (!ok && !honor_logged_) {
            LOGI("honor: the stats can't be read - no honor feedback");
            honor_logged_ = true;
        }
        if (ok && honor_ok_) {
            int d = cur - honor_;
            if (pos > honor_pos_ || neg > honor_neg_) {
                bool up = pos > honor_pos_;
                LOGI("honor %s %+d (now %d)", up ? "up" : "down", d, cur);
                ev.push_back({WorldEvent::Honor, 0, clampv(std::abs(d) / 20.0f, 0.4f, 1.0f), up ? "up" : "down"});
            }
        }
        if (ok) {
            honor_ = cur;
            honor_pos_ = pos;
            honor_neg_ = neg;
        }
        honor_ok_ = ok;
    }

    // --- the surface under you: F10 shows what it is, F10 again (while shown) changes it ---'''),
])

edit("engine.h", [
    ("    FishingState fishing;", "    FishingState fishing;\n    int deadeye_marks = 0;"),
    ("    // fishing\n",
     "    // Dead Eye: marks, and the volley the game fires by itself\n"
     "    int marks_ = 0, last_clip_ = -1;\n"
     "    bool was_shooting_ = false;\n"
     "    double mark_tick_until_ = 0;\n"
     "    // fishing\n"),
])
edit("core.cpp", [("        h.fishing = g.fishing;", "        h.fishing = g.fishing;\n        h.deadeye_marks = g.deadeye_marks;")])

edit("engine.cpp", [
    # marks: a tick on the haptics and the trigger
    ("""    fx::Block blk;
    if (kind_ == "bow") blk = update_bow(raw, now, f);""",
     """    // Dead Eye: every target you paint ticks under your finger
    if (g.valid) {
        if (dead_eye_ && g.deadeye_marks > marks_) {
            play(f, "deadeye_mark");
            mark_tick_until_ = now + 0.035;
        }
        marks_ = g.deadeye_marks;
    }

    fx::Block blk;
    if (kind_ == "bow") blk = update_bow(raw, now, f);"""),
    ("""    f.r2 = blk;
""",
     """    f.r2 = blk;
    if (now < mark_tick_until_) f.r2 = fx::vibration(0, 6, 60);
"""),
    # volley: the game fires the marked shots itself
    ("""    const std::string st = state_;
    if (st == "ready") {
        crossed(ticks_, raw, f, now);""",
     """    // Dead Eye volley: the game fires the marked shots by itself - each one kicks as it really goes off
    if (g.valid) {
        bool fired = (g.shooting && !was_shooting_) || (g.clip >= 0 && last_clip_ >= 0 && g.clip < last_clip_);
        was_shooting_ = g.shooting;
        last_clip_ = g.clip;
        if (dead_eye_ && fired && now - shot_t_ > 0.14 && now - kick_t_ > 0.14) {
            shot_t_ = now;
            kick_t_ = now;
            last_dry_ = false;
            schedule(now, shot_haptic_, haptic_gain_);
        }
        if (dead_eye_ && now - kick_t_ >= 0 && now - kick_t_ < kick_.duration(slow())) {
            fx::Block k;
            if (kick_.block(float(now - kick_t_), slow(), k)) return k;
        }
    }
    const std::string st = state_;
    if (st == "ready") {
        crossed(ticks_, raw, f, now);"""),
])

edit("features.h", [("    bool armed_before_ = false;",
                     "    bool armed_before_ = false;\n    double honor_until_ = 0;\n    bool honor_up_ = true;")])
edit("features.cpp", [
    ("""        } else if (e.type == WorldEvent::Ack) {""",
     """        } else if (e.type == WorldEvent::Honor) {
            honor_up_ = e.cause == "up";
            honor_until_ = now + 1.4;
            cues.push_back(make(honor_up_ ? "honor_up" : "honor_down", e.strength));
        } else if (e.type == WorldEvent::Ack) {"""),
    ("""    } else if (w && w->flash) {
        r = 255; gr = 130; b = 20;
    } else if (g.dead_eye) {""",
     """    } else if (w && w->flash) {
        r = 255; gr = 130; b = 20;
    } else if (now < honor_until_) {                                // honor changed: warm glow / dark ember
        float p = float(std::sin(kPi * (honor_until_ - now) / 1.4));
        if (honor_up_) { r = 255 * p; gr = 200 * p; b = 110 * p; }
        else { r = 120 * p; gr = 10 * p; b = 0; }
    } else if (g.dead_eye) {"""),
])

hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
txt = hp.read_text(encoding="utf-8").rstrip()
new = {
    "deadeye_mark": {"_doc": "a target painted in Dead Eye: a crisp, dry tick", "gain": 1.0, "layers": [
        {"type": "click", "hz": 300, "cycles": 1, "amp": 0.7, "pan": 0.6}]},
    "honor_up": {"_doc": "honor rose: a warm, rising double swell", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 60, "to_hz": 85, "attack_ms": 40, "decay_ms": 120, "amp": 0.5, "pan": 0.0},
        {"type": "tone", "hz": 80, "to_hz": 110, "delay_ms": 170, "attack_ms": 40, "decay_ms": 160, "amp": 0.45, "pan": 0.0}]},
    "honor_down": {"_doc": "honor fell: one low, heavy sinking thud", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 55, "to_hz": 32, "attack_ms": 15, "decay_ms": 260, "amp": 0.7, "pan": 0.0}]},
}
d = json.loads(txt)
added = [k for k in new if k not in d]
if added:
    body = ",\n".join(f'  "{k}": ' + json.dumps(new[k]) for k in added)
    txt = txt[:-1].rstrip() + ",\n" + body + "\n}\n"
    json.loads(txt)
    hp.write_text(txt, encoding="utf-8")
print("patched; recipes added:", added)
