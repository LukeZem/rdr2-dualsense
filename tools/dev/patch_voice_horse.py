"""Voice: horse commands (calm / stop) next to the greeting."""
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


core = (SRC / "core.cpp").read_text(encoding="utf-8")
start = core.index('        // "Phrase" may list several spellings')
end = core.index("        });", start) + len("        });")
new_block = r'''        // each command may list several spellings/words, comma separated: chao = ciao / chow
        auto words = [&](const char* key, const char* def) {
            std::vector<std::string> out;
            std::string cur;
            for (char ch : c.str("Voice", key, def) + ",") {
                if (ch == ',') {
                    while (!cur.empty() && cur.back() == ' ') cur.pop_back();
                    if (!cur.empty()) out.push_back(cur);
                    cur.clear();
                } else if (ch != ' ' || !cur.empty()) {
                    cur += char(tolower((unsigned char)ch));
                }
            }
            return out;
        };
        voice_greet_ = words("Phrase", "ciao,chow");
        voice_calm_ = words("CalmPhrase", "easy,easy boy,easy girl,steady");
        voice_stop_ = words("StopPhrase", "whoa");
        std::vector<std::string> phrases = voice_greet_;
        phrases.insert(phrases.end(), voice_calm_.begin(), voice_calm_.end());
        phrases.insert(phrases.end(), voice_stop_.begin(), voice_stop_.end());
        voice_.start(phrases, c.num("Voice", "MinConfidence", 0.35f), [this](const std::string& said, float conf) {
            LOGI("voice: \"%s\" (confidence %.2f)", said.c_str(), conf);
            auto in = [&](const std::vector<std::string>& v) { return std::find(v.begin(), v.end(), said) != v.end(); };
            if (in_game_) {
                if (in(voice_greet_)) world().request_greet();
                else if (in(voice_calm_)) world().request_horse(World::HorseCalm);
                else if (in(voice_stop_)) world().request_horse(World::HorseStop);
            } else {                                 // test program: just confirm
                confirm();
                printf("\n  >>> %s\n", in(voice_greet_) ? "CHAO" : in(voice_calm_) ? "EASY (calm the horse)" : "WHOA (stop the horse)");
            }
        });'''
core = core[:start] + new_block + core[end:]
(SRC / "core.cpp").write_text(core, encoding="utf-8")

edit("core.h", [("    bool speaker_mechanics_ = true;",
                 "    bool speaker_mechanics_ = true;\n    std::vector<std::string> voice_greet_, voice_calm_, voice_stop_;")])
edit("world.h", [
    ("    void request_greet() { greet_requested_ = true; }   // any thread (voice recognizer)",
     "    void request_greet() { greet_requested_ = true; }   // any thread (voice recognizer)\n"
     "    enum HorseCommand { HorseNone, HorseCalm, HorseStop };\n"
     "    void request_horse(HorseCommand c) { horse_cmd_ = c; }   // any thread (voice recognizer)"),
    ("    std::atomic<bool> greet_requested_{false};",
     "    std::atomic<bool> greet_requested_{false};\n    std::atomic<int> horse_cmd_{HorseNone};"),
])
edit("config.cpp", [(
    "SpeechFallback=1\n",
    "SpeechFallback=1\n"
    "; Calm your horse (riding it or standing next to it) - the game's own Calm\n"
    "CalmPhrase=easy,easy boy,easy girl,steady\n"
    "; Stop your horse\n"
    "StopPhrase=whoa\n")])
print("patched")
