// Haptic recipe library: synthesized recipes (haptics.json) + weapon shots built from game audio.
// Port of tools/trigger_lab/ds5/haptics.py.
#pragma once

#include "common.h"
#include "gameaudio.h"

#include <map>

#include "../third_party/json.hpp"

namespace dsr2 {

struct Cue {
    std::string name;
    float gain = 1.0f;
    int variant = -1;           // -1 = pick one
    float speed = 1.0f;         // <1 = slow motion (longer, deeper)
    bool has_pan = false;
    float pan = 0.0f;           // re-pan (which hand)
    bool scripted = true;       // ducks the game-audio layer while it plays
    bool speaker = false;       // also play on the controller speaker
    std::string bank;           // weapon bank (speaker sounds labelled per weapon)
};

using Stereo = std::vector<float>;   // interleaved L,R at 48 kHz

class HapticLibrary {
public:
    void load(const fs::path& recipes_json, GameAudio* game);
    bool has(const std::string& name);
    int variant_count(const std::string& name);
    // Ready-to-play buffer (variant chosen if -1, speed/pan/gain applied).
    bool render(const Cue& cue, Stereo& out, int* chosen = nullptr);
    // Builds "<WEAPON>:shot" from the weapon's own recordings (+ the class's synthesized thump).
    std::string ensure_weapon(const nlohmann::json& profile);
    std::vector<std::vector<int>> kicks(const std::string& name);
    // Sound for the controller speaker: a labelled game recording for this mechanism if there is one,
    // else an audible version of the haptic.
    bool speaker_sound(const Cue& cue, Stereo& out);
    std::string source(const std::string& name);

private:
    // audible = the same recipe an octave-and-more up, for the controller's small speaker
    const std::vector<Stereo>& render_recipe(const std::string& name, int depth, bool audible = false);
    Stereo synth_layer(const nlohmann::json& layer, float freq_mul = 1.0f);

    nlohmann::json recipes_;
    GameAudio* game_ = nullptr;
    std::map<std::string, std::vector<Stereo>> buffers_;
    std::map<std::string, std::vector<std::vector<int>>> kicks_;
    std::map<std::string, std::string> source_;
    std::recursive_mutex mu_;
    Rng rng_{0xC0FFEE};
};

}  // namespace dsr2
