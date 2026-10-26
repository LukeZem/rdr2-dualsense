"""One-off patch: start the voice recognizer, confirm greetings with a knock, config + build."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "mod"


def edit(name, pairs):
    p = ROOT / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:80]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


edit("src/core.h", [
    ('#include "haptics.h"\n', '#include "haptics.h"\n#include "voice.h"\n'),
    ("    DualSense pad_;\n", "    DualSense pad_;\n    Voice voice_;\n"),
])

edit("src/core.cpp", [
    ("""    pad_.start([this](const InputState& s, OutputState& out) { return on_input(s, out); });""",
     """    if (c.flag("Voice", "Enabled", true)) {
        std::string phrase = c.str("Voice", "Phrase", "howdy");
        voice_.start({phrase}, c.num("Voice", "MinConfidence", 0.35f), [this](const std::string& said, float conf) {
            LOGI("voice: \\"%s\\" (confidence %.2f)", said.c_str(), conf);
            if (in_game_) world().request_greet();
            else {                                   // test program: just confirm
                Cue ack;
                ack.name = "whistle_ack";
                ack.scripted = false;
                audio_.play(ack);
            }
        });
    }
    pad_.start([this](const InputState& s, OutputState& out) { return on_input(s, out); });"""),
    ("""    pad_.stop();
    audio_.stop();""", """    pad_.stop();
    voice_.stop();
    audio_.stop();"""),
    ("""        audio_.set_mic_listening(!audio_.mic_listening());""",
     """        audio_.set_mic_listening(!audio_.mic_listening());
        voice_.set_listening(audio_.mic_listening());"""),
    ("""        LOGI("whistle listening %s", audio_.mic_listening() ? "on" : "off");""",
     """        LOGI("whistle + voice listening %s", audio_.mic_listening() ? "on" : "off");"""),
])

edit("src/features.cpp", [
    ("""        } else if (e.type == WorldEvent::Door && action_gain_ > 0) {""",
     """        } else if (e.type == WorldEvent::Ack) {
            cues.push_back(make("whistle_ack", config().num("Mic", "Confirm", 0.8f)));
        } else if (e.type == WorldEvent::Door && action_gain_ > 0) {"""),
])

edit("src/config.cpp", [
    ("""[Touchpad]""", """[Voice]
; Say the phrase into the controller: Arthur turns to the closest person (within Range metres),
; focuses them and greets them. Your gun must be holstered. Two knocks confirm it.
; English speech recognizer (built into Windows). The mute button pauses listening.
Enabled=1
Phrase=howdy
; Button that greets while someone is focused: Y (Triangle) or X (Square)
GreetButton=Y
Range=6
; 0-1: higher = fewer accidental greetings, but you may need to say it more clearly
MinConfidence=0.35

[Touchpad]"""),
])

edit("CMakeLists.txt", [
    ("src/core.cpp src/surfaces.cpp)", "src/core.cpp src/surfaces.cpp src/voice.cpp)"),
    ("set(SYSTEM_LIBS setupapi hid ole32 uuid avrt)", "set(SYSTEM_LIBS setupapi hid ole32 uuid avrt winmm)"),
])
print("core/voice patched")
