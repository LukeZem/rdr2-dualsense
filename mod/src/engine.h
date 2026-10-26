// Weapon trigger engine - port of tools/trigger_lab/sim/engine.py, plus live game data in game.
// Runs on the controller thread for every input report (~250 Hz).
#pragma once

#include "common.h"
#include "ds5.h"
#include "effects.h"
#include "haptics.h"

#include <deque>
#include <map>

#include "../third_party/json.hpp"

namespace dsr2 {

struct Calibration {
    std::array<int, 10> r2{0, 26, 51, 77, 102, 128, 153, 179, 204, 230};
    std::array<int, 10> l2{0, 26, 51, 77, 102, 128, 153, 179, 204, 230};
    bool calibrated = false;
    int raw_at(int zone, bool right = true) const { return zone >= 10 ? 255 : (right ? r2 : l2)[std::max(0, zone)]; }
    int zone_of(int raw, bool right = true) const {
        const auto& t = right ? r2 : l2;
        int z = 0;
        for (int i = 0; i < 10; ++i) if (raw >= t[i]) z = i;
        return z;
    }
    bool load(const fs::path& p);
};

struct Settings {
    bool manual_action = true;
    bool fanning = true;
    bool auto_align = true;
    int fire_margin = 4;
    float kick_scale = 1.0f;
    bool aim_resistance = true;
    float audio_latency_ms = 0.0f;
    bool reload_ticks = false;          // in game the reload sounds come through the game-audio layer
    bool scheduled_explosions = false;  // ditto for thrown explosives
};

// What the game tells us this frame (all optional: valid=false in the standalone test).
struct GameHints {
    bool valid = false;
    int clip = -1, clip_max = -1;
    bool reloading = false;
    bool shooting = false;          // the game fired this frame
    bool dead_eye = false;
    float grit = 0;                 // 0-1 from weapon dirt/degradation
    float kick_mult = 1;            // ammo type
    float tremor = 0;               // 0-1: exhaustion, cold, drunk
    bool lasso_attached = false;
    float lasso_pull = 0;           // 0-1 how hard the catch pulls
    int melee_hits = 0;             // counter: damage the player dealt in melee range
    bool melee_target_near = false;
    bool hip_fire = true;           // not aiming down the sights
    bool ready = true;              // the game says the gun can fire (cooldown over, hammer cocked...)
    FishingState fishing;
    int deadeye_marks = 0;
};

struct EngineFrame {
    fx::Block r2 = fx::off(), l2 = fx::off();
    std::vector<Cue> cues;
    int game_rt = -1;               // -1 = pass the real R2 through
    std::string state;
    bool flash = false;             // muzzle flash (lightbar)
};

class WeaponEngine {
public:
    WeaponEngine(const nlohmann::json& profile, const Calibration& cal, const Settings& s,
                 const std::vector<std::vector<int>>& kick_variants);
    EngineFrame update(const InputState& in, const GameHints& g);
    const std::string& id() const { return id_; }
    const std::string& kind() const { return kind_; }
    int break_raw() const { return break_raw_; }
    int clip() const { return clip_; }
    int clip_size() const { return clip_size_; }
    std::string bank() const { return bank_; }

private:
    using Zones = std::array<int, 10>;
    struct Kick {
        int freq = 40;
        std::vector<int> base, steps;
        float step_s = 0.016f;
        float duration(float slow) const { return steps.empty() ? 0.0f : 0.035f * slow + steps.size() * step_s * slow * 1.6f; }
        bool block(float dt, float slow, fx::Block& out) const;
    };

    float slow() const { return dead_eye_ ? 1.7f : 1.0f; }
    float speed() const { return dead_eye_ ? 0.6f : 1.0f; }
    Cue cue(const std::string& name, float gain = 1.0f, int variant = -1) const;
    void play(EngineFrame& f, const std::string& name, float gain = 1.0f, int variant = -1) const;
    void schedule(double at, const std::string& name, float gain = 1.0f, int variant = -1, bool has_pan = false, float pan = 0);
    fx::Block fire_block(int raw, double now);
    fx::Block stop_block(const Zones* base = nullptr) const;
    Zones texture(Zones z, int raw, double now);
    void crossed(const std::map<int, nlohmann::json>& ticks, int raw, EngineFrame& f, double now);
    void shoot(int raw, double now, EngineFrame& f, bool fanned = false);
    void start_reload(double now);
    fx::Block update_gun(int raw, double now, EngineFrame& f, const GameHints& g);
    fx::Block update_reload(double now, EngineFrame& f);
    fx::Block update_auto(int raw, double now, EngineFrame& f);
    fx::Block update_bow(int raw, double now, EngineFrame& f);
    fx::Block update_melee(uint32_t pressed, double now, EngineFrame& f, const GameHints& g);
    fx::Block update_tension(int raw, uint32_t pressed, double now, EngineFrame& f, const GameHints& g);
    fx::Block update_fishing(int raw, double now, EngineFrame& f, const GameHints& g);
    void analyse(double now);

    nlohmann::json p_;
    Calibration cal_;
    Settings set_;
    std::string id_, kind_, mode_, bank_, shot_haptic_, empty_feel_;
    Zones curve_{}, after_curve_{}, action_curve_{};
    std::array<int, 3> weapon_fx_{4, 6, 6}, simple_fx_{100, 160, 200};
    int break_raw_ = 0, reset_raw_ = 0, stop_zone_ = 0, stop_strength_ = 8, action_break_raw_ = 0;
    float grit_ = 0, lock_s_ = 0.005f, rate_s_ = 0.4f, haptic_gain_ = 1.0f;
    Kick kick_;
    std::vector<std::vector<int>> kick_variants_;
    std::map<int, nlohmann::json> ticks_, action_ticks_;
    nlohmann::json action_, reload_, bow_, melee_, tension_;
    int clip_size_ = 0, clip_ = 0;            // clip_size 0 = no magazine
    fx::Block aim_block_ = fx::off();

    // state
    std::string state_ = "ready";
    int game_rt_ = 0;
    double shot_t_ = -10, kick_t_ = -10, action_t_ = -10, reload_t_ = -10, draw_t_ = -10, tether_t_ = -10;
    int reload_ticks_done_ = 0, reload_rounds_ = 0;
    bool last_dry_ = false, dead_eye_ = false;
    int prev_raw_ = 0;
    double prev_t_ = 0;
    uint32_t prev_buttons_ = 0;
    float vel_ = 0;
    int l2_ = 0;
    struct Timer { double at; Cue cue; };
    std::vector<Timer> timers_;
    std::map<int, double> bumps_;
    double grit_until_ = 0;
    std::pair<int, int> grit_zone_{-1, 0};
    std::deque<std::pair<double, int>> history_;
    struct Pending { double t; int raw; };
    std::vector<Pending> pending_;
    std::vector<int> snaps_;
    int shots_ = 0;
    double next_heartbeat_ = 0, next_jerk_ = 0, jerk_until_ = 0;
    float noise_phase_ = 0;
    int hand_ = -1, combo_ = 0;
    std::string last_strike_;
    // in-game melee confirmation
    struct Strike { double deadline; float pan; int hits_at_start; bool done; };
    std::vector<Strike> strikes_;
    int last_melee_hits_ = 0;
    // fire-rate sync: shots the game did not take
    double unconfirmed_since_ = -1;
    bool ready_usable_ = true;      // false if the game's readiness signal doesn't behave for this gun
    double not_ready_since_ = -1;
    float lasso_prev_ = 0;
    // Dead Eye: marks, and the volley the game fires by itself
    int marks_ = 0, last_clip_ = -1;
    bool was_shooting_ = false;
    double mark_tick_until_ = 0;
    // fishing
    int fish_state_ = 0, fish_cmd_ = 0;
    bool fish_bite_ = false;
    float fish_peak_ = 0, reel_acc_ = 0;
    double fish_t_ = 0, bite_until_ = 0, nibble_until_ = 0, next_surge_ = 0, next_flop_ = 0, flop_until_ = 0;
    float game_grit_ = 0, game_tremor_ = 0, game_kick_mult_ = 1;
    mutable Rng rng_{uint64_t(now_s() * 1e6)};
};

}  // namespace dsr2
