// Everything beyond the weapon: lightbar + LEDs, horse (hooves by gait and ground, exhaustion,
// rearing), trains and wagons, directional damage and gunfire, heartbeat, cold, riding trigger pulse.
// Runs on the controller thread.
#pragma once

#include "common.h"
#include "ds5.h"
#include "engine.h"
#include "haptics.h"
#include "world.h"

#include <map>

namespace dsr2 {

class Features {
public:
    void configure();
    // adds cues, sets lightbar/LEDs, may override triggers when no weapon effect is active
    void update(const InputState& in, const GameSnapshot& g, std::vector<WorldEvent> events, const EngineFrame* weapon,
                bool weapon_active, int clip, int clip_size, bool mic_listening, OutputState& out, std::vector<Cue>& cues);

private:
    void horse(const GameSnapshot& g, double now, std::vector<Cue>& cues, OutputState& out, bool weapon_active);
    void transport(const GameSnapshot& g, double now, std::vector<Cue>& cues);
    void through(float wade, bool foliage, float foliage_h, float speed, float gain, float pan, std::vector<Cue>& cues);
    void splash(float wade, float& was, float speed, float gain, std::vector<Cue>& cues);
    float wade_was_ = 0, horse_wade_was_ = 0;    // last depth in water (for the splash going in)
    void rustle(bool in, float height, float speed, float gain, bool& was, double& next, double now, std::vector<Cue>& cues);
    bool foliage_was_ = false, horse_foliage_was_ = false;
    double next_brush_ = 0, next_horse_brush_ = 0;
    void lightbar(const GameSnapshot& g, const EngineFrame* weapon, double now, OutputState& out);

    float horse_gain_ = 0.5f, train_gain_ = 0.6f, damage_gain_ = 1, gunfire_gain_ = 0.6f, heart_gain_ = 1,
          cold_gain_ = 0.5f, hit_gain_ = 0, brightness_ = 1, step_gain_ = 0.4f, land_gain_ = 0.7f, action_gain_ = 0.5f;
    int riding_pulse_ = 2;
    bool lightbar_on_ = true, ammo_leds_ = true, time_of_day_ = true;
    // horse
    double next_horse_heart_ = 0, next_breath_ = 0;
    bool rearing_ = false;
    bool armed_before_ = false;
    double honor_until_ = 0;
    float minigame_gain_ = 0.7f, weather_gain_ = 0;
    double next_drop_ = 0, next_texture_ = 0;
    double shock_t_ = -10;                       // a close blast: both triggers shudder for ~0.45 s
    float shock_amp_ = 0;
    bool triggers_on_ = true;
    float life_gain_ = 0.6f;
    int texture_n_ = 0;
    bool honor_up_ = true;
    uint32_t weapon_before_ = 0;
    int attach_before_ = -1;
    double last_hoof_event_ = -10;
    double mount_t_ = 0;
    // transport
    double rail_dist_ = 0, last_trans_t_ = 0, next_rut_ = 0;
    // body
    double next_heart_ = 0, next_shiver_ = 0;
    double damage_flash_until_ = 0;
    float damage_flash_ = 0;
    std::vector<std::pair<double, Cue>> delayed_;
    Rng rng_{0xFEED};
    float lb_[3] = {0, 0, 0};
};

}  // namespace dsr2
