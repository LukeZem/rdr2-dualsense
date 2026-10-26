// Owns every subsystem and runs the controller pipeline.
#pragma once

#include "audio.h"
#include "catalog.h"
#include "common.h"
#include "ds5.h"
#include "engine.h"
#include "features.h"
#include "gameaudio.h"
#include "haptics.h"
#include "voice.h"

#include <memory>

namespace dsr2 {

class Core {
public:
    bool init(bool in_game, const std::string& test_weapon = "");
    void shutdown();
    void script_tick();                 // ScriptHook thread (in game) or test loop
    void request_reload() { reload_requested_ = true; }
    // test harness introspection
    std::string status();
    DualSense& pad() { return pad_; }
    AudioEngine& audio() { return audio_; }

private:
    bool on_input(const InputState& s, OutputState& out);
    void load_data();
    void confirm();
    void build_engine(const nlohmann::json& profile, const std::string& name);

    bool in_game_ = false;
    std::string test_weapon_;
    Calibration cal_;
    int wheel_r2_ = 0, wheel_l2_ = 0;      // last trigger positions, for the wheel's selector clicks
    Settings settings_;
    Catalog catalog_;
    GameAudio game_audio_;
    HapticLibrary lib_;
    AudioEngine audio_;
    Features features_;
    DualSense pad_;
    Voice voice_;
    std::unique_ptr<WeaponEngine> engine_;
    uint32_t engine_key_ = 0;
    std::string engine_name_;
    std::map<std::string, int> learned_break_;
    std::atomic<bool> reload_requested_{false};
    bool speaker_mechanics_ = true;
    std::vector<std::string> voice_greet_, voice_calm_, voice_stop_, voice_spur_;
    // a whistle waits ~1 s for the speech recognizer: if a spoken command ("chao") lands around it, it was a word
    std::atomic<double> whistle_at_{-1}, last_command_t_{-10};
    bool triggers_on_ = true, haptics_on_ = true;
    uint32_t prev_buttons_ = 0;
    std::mutex status_mu_;
    std::string last_state_;
    int last_rt_ = 0;
    bool reload_key_down_ = false;
    bool pad_was_connected_ = false, pad_seen_ = false;
    double l1_since_ = -1, wheel_until_ = 0;
    bool need_r2_release_ = false;
    std::atomic<bool> restarting_{false};
};

Core& core();

}  // namespace dsr2
