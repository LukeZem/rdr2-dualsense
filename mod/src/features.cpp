#include "features.h"

#include "config.h"
#include "log.h"

#include <map>

namespace dsr2 {

void Features::configure() {
    Config& c = config();
    horse_gain_ = c.num("Haptics", "Horse", 0.3f);
    train_gain_ = c.num("Haptics", "Train", 0.6f);
    damage_gain_ = c.num("Haptics", "Damage", 1.0f);
    gunfire_gain_ = c.num("Haptics", "Gunfire", 0.6f);
    heart_gain_ = c.num("Haptics", "Heartbeat", 1.0f);
    cold_gain_ = c.num("Haptics", "Cold", 0.5f);
    hit_gain_ = c.num("Haptics", "HitConfirm", 0.0f);
    step_gain_ = c.num("Haptics", "Footsteps", 0.22f);
    land_gain_ = c.num("Haptics", "Landing", 0.7f);
    action_gain_ = c.num("Haptics", "Actions", 0.5f);
    minigame_gain_ = c.num("Haptics", "TableGames", 0.7f);
    weather_gain_ = c.num("Haptics", "Weather", 0.0f);
    life_gain_ = c.num("Haptics", "CampLife", 0.6f);
    riding_pulse_ = c.integer("Triggers", "RidingPulse", 0);
    lightbar_on_ = c.flag("Lightbar", "Enabled", true);
    brightness_ = c.num("Lightbar", "Brightness", 1.0f);
    ammo_leds_ = c.flag("Lightbar", "AmmoLeds", true);
    time_of_day_ = c.flag("Lightbar", "TimeOfDay", true);
}

static Cue make(const std::string& name, float gain, float pan = 0, bool has_pan = false, bool scripted = false) {
    Cue c;
    c.name = name;
    c.gain = gain;
    c.has_pan = has_pan;
    c.pan = pan;
    c.scripted = scripted;
    return c;
}

void Features::horse(const GameSnapshot& g, double now, std::vector<Cue>& cues, OutputState& out, bool weapon_active) {
    if (!g.on_mount) {
        last_gait_t_ = now;
        mount_t_ = now;
        rearing_ = false;
        hooves_live_ = true;
        return;
    }
    double dt = now - last_gait_t_;
    last_gait_t_ = now;
    float v = g.mount_speed;
    // gait: stride rate and footfall pattern (fraction of the stride where each hoof lands)
    float stride_hz, amp;
    std::vector<float> beats;
    if (v < 0.4f) { stride_hz = 0; amp = 0; }
    else if (v < 2.3f) { stride_hz = 0.45f + 0.25f * v; amp = 0.35f; beats = {0.0f, 0.25f, 0.5f, 0.75f}; }    // walk, 4-beat
    else if (v < 4.6f) { stride_hz = 1.25f + 0.08f * v; amp = 0.5f; beats = {0.0f, 0.5f}; }                     // trot, 2-beat
    else if (v < 8.0f) { stride_hz = 1.5f + 0.05f * v; amp = 0.7f; beats = {0.0f, 0.3f, 0.45f}; }               // canter, 3-beat
    else { stride_hz = 1.8f + 0.03f * v; amp = 0.9f; beats = {0.0f, 0.12f, 0.36f, 0.48f}; }                    // gallop, 4-beat
    // the real hoof contacts drive the hooves while they keep up with the gait (each hoof lands once per
    // stride); if they fall behind - or the legs were not found - the gait rhythm takes over
    float expected = 4 * stride_hz;
    if (!g.hoof_bones) hooves_live_ = false;
    else if (expected > 0 && g.hoof_rate > 0.7f * expected) hooves_live_ = true;
    else if (expected > 0 && g.hoof_rate < 0.45f * expected && now - mount_t_ > 2.0) hooves_live_ = false;
    bool gait_driven = !hooves_live_;
    if (gait_driven && stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {
        double before = gait_phase_;
        gait_phase_ = std::fmod(gait_phase_ + dt * stride_hz, 1.0);
        for (size_t i = 0; i < beats.size(); ++i) {
            float b = beats[i];
            bool hit = before <= gait_phase_ ? (before < b && b <= gait_phase_) : (before < b || b <= gait_phase_);
            if (!hit) continue;
            const std::string& surf = g.horse_surface;
            float pan = (hoof_++ % 2 ? 0.25f : -0.25f);
            cues.push_back(make("hoof_" + surf, amp * horse_gain_ * rng_.range(0.85f, 1.1f), pan, true));
        }
    }
    // the horse is spent: its heart pounds, it heaves
    if (g.mount_stamina < 15 && v > 2 && horse_gain_ > 0) {
        if (now >= next_horse_heart_) {
            next_horse_heart_ = now + 0.55;
            cues.push_back(make("horse_heartbeat", 0.8f * horse_gain_));
        }
        if (now >= next_breath_) {
            next_breath_ = now + 1.3;
            cues.push_back(make("horse_breath", 0.6f * horse_gain_));
        }
    }
    // rearing / bucking
    bool rear = g.mount_pitch > 25.0f;
    if (rear && !rearing_) cues.push_back(make("horse_rear", horse_gain_ * 1.2f));
    rearing_ = rear;
    // the triggers feel the gait while riding unarmed
    if (!weapon_active && riding_pulse_ > 0 && stride_hz > 0.8f && !g.aiming) {
        int hz = clampv(int(std::lround(stride_hz * float(beats.size()) / 2)), 1, 8);
        out.r2 = fx::galloping(3, 9, 4, 7, hz);
        out.l2 = fx::galloping(3, 9, 4, 7, hz);
    }
}

void Features::transport(const GameSnapshot& g, double now, std::vector<Cue>& cues) {
    double dt = now - last_trans_t_;
    last_trans_t_ = now;
    if (dt <= 0 || dt > 0.1 || train_gain_ <= 0) return;
    if (g.in_train && g.speed > 2) {
        // 39 ft rails: a joint every ~12 m, felt twice (front and rear bogie)
        double before = rail_dist_;
        rail_dist_ += g.speed * dt;
        if (std::floor(before / 12.0) != std::floor(rail_dist_ / 12.0)) {
            float gain = train_gain_ * clampv(g.speed / 18.0f, 0.3f, 1.0f);
            cues.push_back(make("rail_clack", gain));
            // the rear bogie crosses the same joint ~10 m later
            delayed_.push_back({now + 10.0 / std::max(2.0f, g.speed), make("rail_clack", gain * 0.8f)});
        }
    } else if (g.in_vehicle && !g.in_train && g.speed > 1.5f) {
        if (now >= next_rut_) {
            next_rut_ = now + rng_.range(0.4f, 2.5f) / clampv(g.speed / 5.0f, 0.5f, 3.0f);
            cues.push_back(make("wagon_rut", train_gain_ * rng_.range(0.4f, 1.0f), rng_.range(-0.5f, 0.5f), true));
        }
    }
}

void Features::lightbar(const GameSnapshot& g, const EngineFrame* w, double now, OutputState& out) {
    if (!lightbar_on_) return;
    float r = 0, gr = 0, b = 0;
    float t = float(now);
    if (now < damage_flash_until_) {
        r = 255 * damage_flash_; gr = 10; b = 0;
    } else if (w && w->flash) {
        r = 255; gr = 130; b = 20;
    } else if (now < honor_until_) {                                // honor changed: warm glow / dark ember
        float p = float(std::sin(kPi * (honor_until_ - now) / 1.4));
        if (honor_up_) { r = 255 * p; gr = 200 * p; b = 110 * p; }
        else { r = 120 * p; gr = 10 * p; b = 0; }
    } else if (g.dead_eye) {
        float p = 0.7f + 0.3f * std::sin(t * 2.0f);
        r = 200 * p; gr = 120 * p; b = 30 * p;                      // sepia glow
    } else if (g.lantern) {
        float fl = 0.75f + 0.15f * std::sin(t * 13.0f) + 0.1f * std::sin(t * 31.0f + 1.3f);
        r = 255 * fl; gr = 140 * fl; b = 40 * fl;                   // warm flicker
    } else if (g.wanted) {
        bool red = std::fmod(t, 1.0f) < 0.5f;
        r = red ? 200.0f : 120.0f; gr = red ? 0.0f : 120.0f; b = red ? 0.0f : 140.0f;
    } else if (g.health_core < 25) {
        float beat = std::fmod(t, 0.9f) < 0.15f ? 1.0f : 0.25f;
        r = 180 * beat;
    } else if (time_of_day_) {
        int h = g.hour;
        if (h >= 21 || h < 5) { r = 5; gr = 10; b = 40; }               // night
        else if (h < 7) { r = 120; gr = 60; b = 30; }                   // dawn
        else if (h < 18) { r = 70; gr = 55; b = 35; }                   // day: warm, dim
        else { r = 150; gr = 60; b = 15; }                              // sunset
    }
    // smooth (except flashes)
    float k = (now < damage_flash_until_ || (w && w->flash)) ? 1.0f : 0.15f;
    lb_[0] += (r - lb_[0]) * k;
    lb_[1] += (gr - lb_[1]) * k;
    lb_[2] += (b - lb_[2]) * k;
    out.has_lightbar = true;
    out.r = uint8_t(clampv(lb_[0] * brightness_, 0.0f, 255.0f));
    out.g = uint8_t(clampv(lb_[1] * brightness_, 0.0f, 255.0f));
    out.b = uint8_t(clampv(lb_[2] * brightness_, 0.0f, 255.0f));
}

void Features::update(const InputState& in, const GameSnapshot& g, std::vector<WorldEvent> events, const EngineFrame* weapon,
                      bool weapon_active, int clip, int clip_size, bool mic_listening, OutputState& out, std::vector<Cue>& cues) {
    double now = in.t;
    out.mute_led = mic_listening ? 0 : 1;
    for (auto it = delayed_.begin(); it != delayed_.end();) {
        if (it->first <= now) { cues.push_back(it->second); it = delayed_.erase(it); }
        else ++it;
    }
    if (ammo_leds_) {
        if (weapon_active && clip_size > 0 && clip >= 0) {
            int lit = clip == 0 ? 0 : clampv(int(std::ceil(5.0f * clip / clip_size)), 1, 5);
            static const int masks[6] = {0x00, 0x04, 0x0A, 0x15, 0x1B, 0x1F};   // centre-out like the PS5 player LEDs
            out.player_leds = masks[lit];
        } else {
            out.player_leds = 0;
        }
    }
    if (!g.valid) {          // standalone test: weapon state colours only
        lightbar(g, weapon, now, out);
        return;
    }
    for (auto& e : events) {
        if (e.type == WorldEvent::Damage && damage_gain_ > 0) {
            std::string name = e.cause == "melee" ? "hit_melee" : e.cause == "animal" ? "hit_animal"
                             : e.cause == "fall" ? "hit_fall" : "hit_bullet";
            cues.push_back(make(name, damage_gain_ * (0.5f + 0.5f * e.strength), e.pan, e.cause != "fall", true));
            damage_flash_until_ = now + 0.18;
            damage_flash_ = 0.5f + 0.5f * e.strength;
        } else if (e.type == WorldEvent::Gunfire && gunfire_gain_ > 0) {
            cues.push_back(make("gunfire_near", gunfire_gain_ * e.strength, e.pan, true));
        } else if (e.type == WorldEvent::HitConfirm && hit_gain_ > 0) {
            cues.push_back(make("hit_confirm", hit_gain_, 0.6f, true));
        } else if (e.type == WorldEvent::Footstep && step_gain_ > 0) {
            // boots: left foot on the left actuator, right on the right; the surface decides the feel
            cues.push_back(make("step_" + e.cause, step_gain_ * e.strength * rng_.range(0.9f, 1.08f), e.pan, true));
        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0 && hooves_live_) {
            last_hoof_event_ = now;
            cues.push_back(make("hoof_" + e.cause, horse_gain_ * e.strength * rng_.range(0.88f, 1.08f), e.pan, true));
        } else if (e.type == WorldEvent::Land && land_gain_ > 0) {
            cues.push_back(make("land", land_gain_ * e.strength));
            cues.push_back(make("step_" + e.cause, step_gain_ * 1.2f));
        } else if (e.type == WorldEvent::Climb && action_gain_ > 0) {
            cues.push_back(make("climb_grab", action_gain_));
        } else if (e.type == WorldEvent::Minigame && minigame_gain_ > 0) {
            static const std::map<std::string, std::string> kCue = {
                {"knife", "knife_tap"}, {"knife_miss", "knife_finger"}, {"chips", "chips"}, {"knock", "knock"},
                {"card", "card_slide"}, {"riffle", "card_riffle"}, {"tile", "domino_clack"}};
            auto it = kCue.find(e.cause);
            if (it != kCue.end()) cues.push_back(make(it->second, minigame_gain_));
            if (e.cause == "knife_miss") {                    // the blade finds a finger
                damage_flash_ = 0.8f;
                damage_flash_until_ = now + 0.25;
            }
        } else if (e.type == WorldEvent::Life && life_gain_ > 0) {
            static const std::map<std::string, std::string> kCue = {
                {"bite", "bite"}, {"gulp", "gulp"}, {"puff", "puff"}, {"brush", "brush_stroke"}, {"feed", "horse_feed"},
                {"stow", "stow"}, {"heave", "heave"}, {"pluck", "pluck"}};
            auto it = kCue.find(e.cause);
            if (it != kCue.end()) cues.push_back(make(it->second, life_gain_ * e.strength));
        } else if (e.type == WorldEvent::Horse) {
            float g = config().num("Mic", "Confirm", 1.0f);
            const char* cue = e.cause == "rein" ? "rein_pull" : e.cause == "spur" ? "spur" : "horse_pat";
            cues.push_back(make(cue, g * e.strength));
        } else if (e.type == WorldEvent::Honor) {
            honor_up_ = e.cause == "up";
            honor_until_ = now + 1.4;
            cues.push_back(make(honor_up_ ? "honor_up" : "honor_down", e.strength));
        } else if (e.type == WorldEvent::Ack) {
            float g = config().num("Mic", "Confirm", 1.0f);
            cues.push_back(make(e.cause == "speech" ? "hit_confirm" : "whistle_ack", e.cause == "speech" ? g * 2.5f : g));
        } else if (e.type == WorldEvent::Door && action_gain_ > 0) {
            cues.push_back(make("door_open", action_gain_, e.pan, true));
        }
    }
    if (!g.blocked && weather_gain_ > 0 && !g.indoors) {             // rain on the hat, as heavy as the game's rain
        if (g.rain > 0.05f && now >= next_drop_) {
            next_drop_ = now + rng_.range(0.3f, 1.7f) / (3.0f + 30.0f * g.rain);
            cues.push_back(make("rain_drop", weather_gain_ * rng_.range(0.3f, 1.0f), rng_.range(-0.8f, 0.8f), true));
        }
    }
    // what Arthur is busy with, felt as a texture while it lasts
    if (!g.blocked && life_gain_ > 0 && !g.activity.empty() && now >= next_texture_) {
        float pan = g.activity_pan;
        std::string cue;
        double gap = 0.5;
        if (g.activity == "clean_gun") { cue = "cloth_rub"; gap = rng_.range(0.4f, 0.6f); pan = (texture_n_ % 2) ? 0.4f : -0.1f; }
        else if (g.activity == "skin") { cue = "skin_cut"; gap = rng_.range(0.55f, 0.9f); pan = 0.3f; }
        else if (g.activity == "scrub") { cue = "scrub"; gap = rng_.range(0.35f, 0.5f); }
        else if (g.activity == "craft") { cue = "craft_tap"; gap = rng_.range(0.8f, 1.5f); pan = 0.2f; }
        else if (g.activity == "cook") { cue = "sizzle"; gap = rng_.range(0.12f, 0.3f); pan = 0.3f; }
        ++texture_n_;
        next_texture_ = now + gap;
        if (!cue.empty()) cues.push_back(make(cue, life_gain_ * rng_.range(0.75f, 1.0f), pan, true));
    }
    if (!g.blocked) {
        if (g.holstering && !was_holstering_ && action_gain_ > 0) {   // gun sliding in / out of the leather
            // drawing if the hands were empty before, else putting it away
            Cue c = make(armed_before_ ? "gun_holster" : "gun_draw", action_gain_ * 1.2f, 0.5f, true);
            static const uint32_t kRevolver = joaat("GROUP_REVOLVER"), kPistol = joaat("GROUP_PISTOL");
            c.speaker = group_before_ == kRevolver || group_before_ == kPistol || !armed_before_;   // sidearm leather
            cues.push_back(c);
        }
        if (!g.holstering) {
            armed_before_ = g.armed;
            group_before_ = g.group;
        }
        was_holstering_ = g.holstering;
        horse(g, now, cues, out, weapon_active);
        transport(g, now, cues);
        if (heart_gain_ > 0 && g.health_core < 20 && !g.dead_eye && now >= next_heart_) {
            next_heart_ = now + 0.9;
            cues.push_back(make("heartbeat", heart_gain_ * 0.9f));
        }
        if (cold_gain_ > 0 && g.temperature < -5 && now >= next_shiver_) {
            next_shiver_ = now + rng_.range(4.0f, 9.0f);
            cues.push_back(make("shiver", cold_gain_ * clampv((-g.temperature - 5) / 10.0f + 0.4f, 0.4f, 1.0f)));
        }
    }
    lightbar(g, weapon, now, out);
}

}  // namespace dsr2
