"""One-off patch: noticeable confirmation (thumps + lightbar flash), shorter configurable cooldown,
heard-during-cooldown logging, clear detection lines in the mic test."""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "mod" / "src"


def edit(path, pairs):
    s = path.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{path.name}: not found: {a[:80]}")
        s = s.replace(a, b, 1)
    path.write_text(s, encoding="utf-8")


edit(SRC / "audio.cpp", [
    ("""                if (run >= int(0.15f * sr / (N / 2)) && t > cooldown_until && mic_listening_) {
                    cooldown_until = t + 2.5;""",
     """                if (run == int(0.15f * sr / (N / 2)) && mic_listening_ && t <= cooldown_until)
                    LOGD("whistle heard again during the %.1f s cooldown (%.0f Hz)", cooldown_s_, hz);
                if (run >= int(0.15f * sr / (N / 2)) && t > cooldown_until && mic_listening_) {
                    cooldown_until = t + cooldown_s_;"""),
    ("""    on_whistle_ = std::move(on_whistle);
    if (mic_.joinable()) return;""", """    on_whistle_ = std::move(on_whistle);
    cooldown_s_ = std::max(0.3f, config().num("Mic", "Cooldown", 1.2f));
    if (mic_.joinable()) return;"""),
    ('#include "log.h"\n', '#include "config.h"\n#include "log.h"\n'),
])
edit(SRC / "audio.h", [
    ("    std::atomic<float> mic_level_{0};", "    std::atomic<float> mic_level_{0};\n    float cooldown_s_ = 1.2f;\n  public:\n    // a recognition happened: the controller thread flashes the lightbar until this time\n    std::atomic<double> ack_flash_until{0};\n  private:"),
])

# confirmation: thumps + flash, from core (whistle and voice)
edit(SRC / "core.cpp", [
    ("""            input().inject(XINPUT_GAMEPAD_DPAD_UP, 0.25);
            Cue ack;                         // "heard you": two quick knocks
            ack.name = "whistle_ack";
            ack.gain = config().num("Mic", "Confirm", 0.8f);
            ack.scripted = false;
            if (ack.gain > 0) audio_.play(ack);""", """            input().inject(XINPUT_GAMEPAD_DPAD_UP, 0.25);
            confirm();
            if (!in_game_) printf("\\n  >>> WHISTLE\\n");"""),
    ("""            if (in_game_) world().request_greet();
            else {                                   // test program: just confirm
                Cue ack;
                ack.name = "whistle_ack";
                ack.scripted = false;
                audio_.play(ack);
            }""", """            if (in_game_) world().request_greet();
            else {                                   // test program: just confirm
                confirm();
                printf("\\n  >>> %s\\n", said == "ciao" || said == "chow" ? "CHAO" : said.c_str());
            }"""),
    ("""void Core::shutdown() {""", """// "heard you": two firm thumps and a short lightbar flash
void Core::confirm() {
    Cue ack;
    ack.name = "whistle_ack";
    ack.gain = config().num("Mic", "Confirm", 1.0f);
    ack.scripted = false;
    if (ack.gain > 0) audio_.play(ack);
    audio_.ack_flash_until = now_s() + 0.35;
}

void Core::shutdown() {"""),
    ("""    if (haptics_on_)
        for (auto& c : cues) audio_.play(c);""", """    if (s.t < audio_.ack_flash_until.load()) {          // recognition flash
        out.has_lightbar = true;
        out.r = 40; out.g = 160; out.b = 255;
    }
    if (haptics_on_)
        for (auto& c : cues) audio_.play(c);"""),
])
edit(SRC / "core.h", [("    void load_data();", "    void load_data();\n    void confirm();")])

# in game the greeting ack goes through features -> make it the same confirm
edit(SRC / "features.cpp", [
    ("""            cues.push_back(make("whistle_ack", config().num("Mic", "Confirm", 0.8f)));""",
     """            cues.push_back(make("whistle_ack", config().num("Mic", "Confirm", 1.0f)));"""),
])
edit(SRC / "config.cpp", [
    ("""; Two quick knocks when a whistle is heard (0 = off)
Confirm=0.8""", """; Two firm thumps + a blue lightbar flash when a whistle or your phrase is recognised (0 = off)
Confirm=1.0
; Seconds after a recognised whistle before the next one counts
Cooldown=1.2"""),
])

# a recipe you can't miss: two 60 ms thumps
hp = REPO / "tools" / "trigger_lab" / "data" / "haptics.json"
data = json.loads(hp.read_text(encoding="utf-8"))
txt = hp.read_text(encoding="utf-8")
new_recipe = '''"whistle_ack": {"_doc": "heard you: two firm thumps", "gain": 1.0, "layers": [
    {"type": "tone", "hz": 72, "to_hz": 60, "attack_ms": 3, "decay_ms": 30, "amp": 1.0},
    {"type": "click", "hz": 200, "cycles": 1, "amp": 0.8},
    {"type": "tone", "hz": 72, "to_hz": 60, "delay_ms": 170, "attack_ms": 3, "decay_ms": 30, "amp": 1.0},
    {"type": "click", "hz": 200, "cycles": 1, "delay_ms": 170, "amp": 0.8}
  ]}'''
txt = re.sub(r'"whistle_ack": \{.*?\n  \]\}', new_recipe, txt, flags=re.S)
json.loads(txt)
hp.write_text(txt, encoding="utf-8")
print("patched")
