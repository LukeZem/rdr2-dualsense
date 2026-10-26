#include "config.h"

#include <windows.h>

#include <cctype>
#include <cmath>
#include <filesystem>
#include <cstdio>
#include <fstream>
#include <sstream>

namespace dsr2 {

Config& config() {
    static Config c;
    return c;
}

static std::string lower(std::string s) {
    for (auto& c : s) c = char(std::tolower((unsigned char)c));
    return s;
}

static std::string trim(const std::string& s) {
    size_t a = s.find_first_not_of(" \t\r\n"), b = s.find_last_not_of(" \t\r\n");
    return a == std::string::npos ? std::string() : s.substr(a, b - a + 1);
}

const char* Config::default_text() {
    return R"INI(; ============================================================================
;  DualSense for RDR2 - settings. Edit and restart the game (or press F9 in game to reload).
; ============================================================================

[General]
Enabled=1
; 1 = write detailed events to DualSenseRDR2.log
Debug=0
; The game only sees the DualSense (hides DSX/ViGEm virtual pads that would double the input)
HideOtherPads=1
; Key (virtual-key code) that reloads this file and the data folder in game. 120 = F9
ReloadKey=120
; Ground is identified from the game's material automatically. This key shows what is under you;
; pressing it again while shown changes it (ground, grass, mud, stone, gravel, wood, snow, sand, water).
; Saved in DualSenseRDR2\materials.json. 121 = F10
TeachSurfaceKey=121

[Triggers]
Enabled=1
; RDR2 cycles single-action hammers, levers, bolts and pumps with an R2 tap between shots.
; Set 0 if you use the "Automatic Cocking" mod.
ManualCocking=1
; Hip-firing a single-action revolver with rapid taps fans the hammer
Fanning=1
; Learn where your trigger really breaks and fire exactly there
AutoAlign=1
; Raw units past the break zone before the shot (when not yet aligned)
FireMargin=4
; Trigger recoil strength (0 - 2)
KickStrength=1.0
; Light resistance on L2 while aiming (weight of the gun)
AimResistance=1
; Dirty / worn guns get a gritty trigger
ConditionGrit=1
; Express / explosive ammo kicks harder
AmmoTypeRecoil=1
; Shaky trigger when exhausted, freezing or drunk
Tremor=1
; Triggers pulse with the horse's gait while riding unarmed (0 = off, 1 = on)
RidingPulse=0

[Haptics]
Enabled=1
; Master strength (0 - 2)
Strength=1.0
; Build every gun's shot from its own recordings in the game's sound banks (lml sound mods)
GameShots=1
; The game's own rumble, converted for the voice-coil actuators (0 = off)
GameRumble=0.35
; Everything you hear, turned into haptics (0 = off). Off by default: it also turns music and
; other sounds not made by your character into vibration. Try 0.3 if you want it anyway.
GameAudio=0
; Part of the name of the output to listen to. Empty = the default output (where the game plays)
GameAudioDevice=
; Level of game audio / rumble while a weapon effect plays (so shots stay crisp)
Duck=0.3
; Taking damage, felt from the direction it came from
Damage=1.0
; Pressure wave of nearby gunfire, from its direction
Gunfire=0.6
; Hoofbeats by gait and ground, horse's heartbeat when it is exhausted
Horse=0.3
; Rail joints on trains, ruts on wagons
Train=0.6
; Heartbeat in Dead Eye and at low health
Heartbeat=1.0
; Shivers in freezing weather
Cold=0.5
; A tiny tick when your shot hits someone
HitConfirm=0
; Footsteps on foot, timed by Arthur's real feet, felt per surface (left foot left, right foot right)
Footsteps=0.22
; Landing from a jump or a drop
Landing=0.7
; Grabbing a ledge, opening a door, drawing / holstering a gun
Actions=0.5
; Five finger fillet (knife taps, the miss), poker / blackjack chips and cards, dominoes tiles
TableGames=0.7
; The little click of L2/R2 while browsing the weapon wheel (0 = off)
WheelClick=0.6
; Camp life: bites, sips and puffs, cleaning your gun, brushing / feeding the horse, skinning, stowing pelts,
; picking herbs, bathing, crafting, cooking
CampLife=0.6
; Rain drops on the hat and far thunder (0 = off: they are weather, not Arthur)
Weather=0

[Speaker]
; Cocking, lever, bolt and reload clicks from the controller's speaker
Mechanics=1
Volume=0.35

[Lightbar]
Enabled=1
Brightness=1.0
; Player LEDs show the rounds left
AmmoLeds=1
; Ambient colour follows the time of day when nothing else is shown
TimeOfDay=1

[Gyro]
; Gyro aiming: off, aim = only while aiming, always = always moves the camera
Mode=off
Sensitivity=1.0
InvertX=0
InvertY=0
; 0 - 0.9, higher = smoother but laggier
Smoothing=0.25

[Mic]
; Whistle into the controller to call your horse. The mute button toggles listening.
WhistleForHorse=1
; Higher = reacts to quieter whistles
Sensitivity=1.0
; Two firm thumps + a blue lightbar flash when a whistle or your phrase is recognised (0 = off)
Confirm=1.0
; Seconds after a recognised whistle before the next one counts
Cooldown=1.2

[Voice]
; Say the phrase into the controller: the camera turns to the closest person (within Range metres) and
; Arthur greets them for real - exactly like focusing them and choosing Greet, so it counts for honor.
; Only the game's own focus + Greet actions are used: it can never aim, draw or attack. Two thumps = done.
; Gun must be holstered. If the game won't focus them, Arthur just says hello (one soft thump, no honor).
; English speech recognizer (built into Windows). The mute button pauses listening.
Enabled=1
; Several words allowed, comma separated (chao: the recognizer knows it as "ciao" / "chow")
Phrase=ciao,chow
Range=6
; 0-1: higher = fewer accidental greetings, but you may need to say it more clearly
MinConfidence=0.7
; If the real greeting fails, Arthur still says a greeting line (no honor)
SpeechFallback=1
; Calm your horse (riding it or standing next to it) - the game's own Calm
CalmPhrase=easy,easy boy,easy girl,steady
; Experimental, off by default (they can trigger by accident while you talk): stop / spur the horse
StopPhrase=
SpeedPhrase=
SpurTaps=2

[Touchpad]
; Button sent to the game: A B X Y LB RB LT RT BACK START LS RS UP DOWN LEFT RIGHT, empty = nothing
Click=BACK
SwipeUp=
SwipeDown=
SwipeLeft=
SwipeRight=
TwoFingerTap=
)INI";
}

bool Config::load(const std::wstring& path) {
    values_.clear();
    std::ifstream in{std::filesystem::path(path)};
    if (!in) {
        std::ofstream out{std::filesystem::path(path)};
        out << default_text();
        out.close();
        in.open(std::filesystem::path(path));
    }
    std::string text;
    if (in) {
        std::stringstream ss;
        ss << in.rdbuf();
        text = ss.str();
    } else {
        text = default_text();
    }
    std::istringstream lines(text);
    std::string line, section;
    while (std::getline(lines, line)) {
        line = trim(line);
        if (line.empty() || line[0] == ';' || line[0] == '#') continue;
        if (line.front() == '[' && line.back() == ']') {
            section = lower(trim(line.substr(1, line.size() - 2)));
            continue;
        }
        size_t eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string key = lower(trim(line.substr(0, eq)));
        std::string val = trim(line.substr(eq + 1));
        size_t c = val.find(" ;");
        if (c != std::string::npos) val = trim(val.substr(0, c));
        values_[section + "." + key] = val;
    }
    return true;
}

std::string Config::str(const std::string& s, const std::string& k, const std::string& def) const {
    auto it = values_.find(lower(s) + "." + lower(k));
    return it == values_.end() ? def : it->second;
}

float Config::num(const std::string& s, const std::string& k, float def) const {
    std::string v = str(s, k, "");
    if (v.empty()) return def;
    try { return std::stof(v); } catch (...) { return def; }
}

int Config::integer(const std::string& s, const std::string& k, int def) const {
    return int(std::lround(num(s, k, float(def))));
}

bool Config::flag(const std::string& s, const std::string& k, bool def) const {
    std::string v = lower(str(s, k, ""));
    if (v.empty()) return def;
    return v == "1" || v == "true" || v == "yes" || v == "on";
}

}  // namespace dsr2
