"""Voice: "giddy up / faster / yah" spurs the horse (the game's own spur, INPUT_HORSE_SPRINT)."""
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


edit("core.h", [("std::vector<std::string> voice_greet_, voice_calm_, voice_stop_;",
                 "std::vector<std::string> voice_greet_, voice_calm_, voice_stop_, voice_spur_;")])
edit("core.cpp", [
    ('        voice_stop_ = words("StopPhrase", "whoa");',
     '        voice_stop_ = words("StopPhrase", "whoa");\n'
     '        voice_spur_ = words("SpeedPhrase", "giddy up,faster,yah,hyah");'),
    ("        phrases.insert(phrases.end(), voice_stop_.begin(), voice_stop_.end());",
     "        phrases.insert(phrases.end(), voice_stop_.begin(), voice_stop_.end());\n"
     "        phrases.insert(phrases.end(), voice_spur_.begin(), voice_spur_.end());"),
    ("                else if (in(voice_stop_)) world().request_horse(World::HorseStop);",
     "                else if (in(voice_stop_)) world().request_horse(World::HorseStop);\n"
     "                else if (in(voice_spur_)) world().request_horse(World::HorseSpur);"),
    ('in(voice_calm_) ? "EASY (calm the horse)" : "WHOA (stop the horse)");',
     'in(voice_calm_) ? "EASY (calm the horse)" : in(voice_stop_) ? "WHOA (stop the horse)" : "FASTER (spur the horse)");'),
])
edit("world.h", [
    ("    enum HorseCommand { HorseNone, HorseCalm, HorseStop };",
     "    enum HorseCommand { HorseNone, HorseCalm, HorseStop, HorseSpur };"),
    ("    int soothe_frames_ = 0;", "    int soothe_frames_ = 0, spur_frames_ = 0, spurs_left_ = 0;\n    double next_spur_ = 0;"),
])
edit("world.cpp", [
    ('        static const Hash kSoothe = joaat("INPUT_INTERACT_ANIMAL"), kStop = joaat("INPUT_HORSE_STOP");',
     '        static const Hash kSoothe = joaat("INPUT_INTERACT_ANIMAL"), kStop = joaat("INPUT_HORSE_STOP"),\n'
     '                          kSpur = joaat("INPUT_HORSE_SPRINT");'),
    ("""        } else if (cmd == HorseCalm) {""",
     """        } else if (cmd == HorseSpur) {
            if (horse) {
                spurs_left_ = clampv(cfg.integer("Voice", "SpurTaps", 2), 1, 6);   // like tapping Cross/A that many times
                next_spur_ = s.time;
                rein_until_ = 0;
                LOGI("voice: faster - spurring at %.1f m/s (horse stamina %d)", s.mount_speed, s.mount_stamina);
            } else {
                LOGI("voice: faster - not riding");
            }
        } else if (cmd == HorseCalm) {"""),
    ("""        if (soothe_frames_ > 0) {""",
     """        if (spurs_left_ > 0 && horse && s.time >= next_spur_) {
            spur_frames_ = 2;
            --spurs_left_;
            next_spur_ = s.time + 0.3;
            ev.push_back({WorldEvent::Horse, 0, 1, "spur"});
        }
        if (!horse) spurs_left_ = 0;
        if (spur_frames_ > 0) {
            SET_CONTROL_VALUE_NEXT_FRAME(0, kSpur, 1.0f);
            --spur_frames_;
        }
        if (soothe_frames_ > 0) {"""),
])
edit("features.cpp", [(
    '            cues.push_back(make(e.cause == "rein" ? "rein_pull" : "horse_pat", g * e.strength));',
    '            const char* cue = e.cause == "rein" ? "rein_pull" : e.cause == "spur" ? "spur" : "horse_pat";\n'
    '            cues.push_back(make(cue, g * e.strength));')])
edit("voice.cpp", [('"hello", "hey", "how", "okay", "yes", "no",', '"hello", "hey", "how", "okay", "yes", "yeah", "no",')])
edit("config.cpp", [(
    "; Stop your horse\nStopPhrase=whoa\n",
    "; Stop your horse\nStopPhrase=whoa\n"
    "; Spur your horse on (each time you say it = SpurTaps taps of Cross/A)\n"
    "SpeedPhrase=giddy up,faster,yah,hyah\n"
    "SpurTaps=2\n")])

hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
txt = hp.read_text(encoding="utf-8").rstrip()
if '"spur"' not in txt:
    rec = {"_doc": "heels into the horse's flanks: a quick double kick, both sides", "gain": 1.0, "layers": [
        {"type": "tone", "hz": 60, "to_hz": 42, "attack_ms": 3, "decay_ms": 45, "amp": 0.55, "pan": -0.7},
        {"type": "tone", "hz": 60, "to_hz": 42, "attack_ms": 3, "decay_ms": 45, "amp": 0.55, "pan": 0.7}]}
    txt = txt[:-1].rstrip() + ',\n  "spur": ' + json.dumps(rec) + "\n}\n"
    json.loads(txt)
    hp.write_text(txt, encoding="utf-8")
print("patched")
