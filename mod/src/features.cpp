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
    triggers_on_ = c.flag("Triggers", "Enabled", true);
    heart_gain_ = c.num("Haptics", "Heartbeat", 1.0f);
    cold_gain_ = c.num("Haptics", "Cold", 0.5f);
    hit_gain_ = c.num("Haptics", "HitConfirm", 0.0f);
    step_gain_ = c.num("Haptics", "Footsteps", 0.35f);
    land_gain_ = c.num("Haptics", "Landing", 0.7f);
    action_gain_ = c.num("Haptics", "Actions", 0.5f);
    minigame_gain_ = c.num("Haptics", "TableGames", 0.7f);
    weather_gain_ = c.num("Haptics", "Weather", 0.3f);
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

// A real step / hoof that is in water also pushes through it (deeper and faster = heavier); one in bushes brushes
// through them (the game's own foliage state). Both ride on the real steps: nothing is felt between them.
void Features::through(float wade, bool foliage, float foliage_h, float speed, float gain, float pan,
                       std::vector<Cue>& cues) {
    if (wade > 0.06f) {
        float depth = clampv((wade - 0.06f) / 0.35f, 0.2f, 1.0f);
        float pace = clampv(0.55f + speed / 8.0f, 0.55f, 1.1f);
        cues.push_back(make("wade_push", gain * 1.4f * depth * pace * rng_.range(0.85f, 1.1f), pan, true));
    }
    (void)foliage;
    (void)foliage_h;                     // bushes: rustle() - for as long as you move through them, not only on steps
}

// Bushes (the game's own "pushing through foliage" state): a swish going in, then a rustle for as long as you keep
// walking through them - faster when running, stronger in taller bushes. Only while really walking (0.8 m/s): the
// game sets the same flag when Arthur just looks at a plant he can pick, or turns beside tall grass.
void Features::rustle(bool in, float height, float speed, float gain, bool& was, double& next, double now,
                      std::vector<Cue>& cues) {
    if (gain > 0) {
        float tall = clampv(0.5f + 0.5f * height, 0.5f, 1.0f);
        if (in && !was && speed > 0.8f) {
            cues.push_back(make("brush_in", gain * 2.0f * tall * clampv(0.6f + speed / 6.0f, 0.6f, 1.3f),
                                rng_.range(-0.3f, 0.3f), true));
            next = now + 0.18;
        } else if (in && speed > 0.8f && now >= next) {
            cues.push_back(make("brush", gain * 1.6f * tall * clampv(0.55f + speed / 6.0f, 0.75f, 1.2f) * rng_.range(0.75f, 1.1f),
                                rng_.range(-0.5f, 0.5f), true));
            next = now + clampv(0.38f - speed * 0.045f, 0.12f, 0.38f) * rng_.range(0.8f, 1.2f);
        }
    }
    was = in;
}

// Splashing into water at pace (once, when the water gets deeper than the ankles).
void Features::splash(float wade, float& was, float speed, float gain, std::vector<Cue>& cues) {
    if (wade > 0.06f && was <= 0.06f && speed > 1.5f && gain > 0)
        cues.push_back(make("splash", gain * clampv(speed / 6.0f, 0.5f, 1.4f)));
    was = wade;
}

void Features::horse(const GameSnapshot& g, double now, std::vector<Cue>& cues, OutputState& out, bool weapon_active) {
    if (!g.on_mount) {
        mount_t_ = now;
        rearing_ = false;
        return;
    }
    float v = g.mount_speed;
    // The hoofbeats come only from the real hoof touchdowns (World::steps -> Hoof events, in update()); there is no
    // generated gait rhythm any more. The gait table below only paces the optional riding pulse on the triggers.
    float stride_hz;
    int beats;
    if (v < 0.4f) { stride_hz = 0; beats = 0; }
    else if (v < 2.3f) { stride_hz = 0.45f + 0.25f * v; beats = 4; }     // walk, 4-beat
    else if (v < 4.6f) { stride_hz = 1.25f + 0.08f * v; beats = 2; }     // trot, 2-beat
    else if (v < 8.0f) { stride_hz = 1.5f + 0.05f * v; beats = 3; }      // canter, 3-beat
    else { stride_hz = 1.8f + 0.03f * v; beats = 4; }                    // gallop, 4-beat
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
        int hz = clampv(int(std::lround(stride_hz * float(beats) / 2)), 1, 8);
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
        } else if (e.type == WorldEvent::Explosion && gunfire_gain_ > 0) {
            // blasts: the game's own explosion recordings; the strength by distance, the side it came from. A close one
            // (15 m or less) hits at full force and shakes the whole controller - only leaning to its side - and the
            // shock reaches the triggers
            const std::string& k = e.cause;
            std::string name = k == "thunder" ? "thunder_strike" : k == "fire" ? "explosion_fire"
                             : k == "small" ? "explosion_small" : "explosion_far";
            const bool close = e.strength >= 0.8f;
            float pan = close ? e.pan * 0.5f : e.pan;
            cues.push_back(make(name, gunfire_gain_ * 2.0f * e.strength, pan, pan != 0, true));
            if (k == "blast") cues.push_back(make("explosion_roll", gunfire_gain_ * 2.0f * e.strength, pan, pan != 0, true));
            if (close && (k == "blast" || k == "thunder")) {
                shock_t_ = now;
                shock_amp_ = e.strength;
            }
        } else if (e.type == WorldEvent::HitConfirm && hit_gain_ > 0) {
            cues.push_back(make("hit_confirm", hit_gain_, 0.6f, true));
        } else if (e.type == WorldEvent::Footstep && step_gain_ > 0) {
            // boots: left foot on the left actuator, right on the right; the ground decides the character, the pace
            // the weight - a sprint lands heavier and longer than a stroll, not just louder
            Cue c = make("step_" + e.cause, step_gain_ * e.strength * rng_.range(0.9f, 1.08f), e.pan, true);
            c.speed = g.speed < 2.2f ? 1.06f : g.speed < 4.8f ? 0.97f : 0.9f;
            cues.push_back(c);
            through(g.wade, g.foliage, g.foliage_height, g.speed, step_gain_, e.pan, cues);
        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0) {
            last_hoof_event_ = now;
            Cue c = make("hoof_" + e.cause, horse_gain_ * e.strength * rng_.range(0.88f, 1.08f), e.pan, true);
            float v = g.mount_speed;
            c.speed = v < 2.3f ? 1.06f : 1.0f;       // a walk crisper; faster gaits carry their energy in more hoofbeats
            cues.push_back(c);
            through(g.horse_wade, g.horse_foliage, g.horse_foliage_height, v, horse_gain_ * 0.8f, e.pan, cues);
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
        // single drops you can count, not a buzz: ~2/s in a drizzle, ~4/s in rain, ~9/s in a downpour (was up to ~33/s)
        if (g.rain > 0.05f && now >= next_drop_) {
            next_drop_ = now + rng_.range(0.5f, 1.5f) / (1.5f + 8.0f * g.rain);
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
    if (!g.halted) {                    // the world keeps moving in cutscenes: hooves, wagons and trains are felt there too
        horse(g, now, cues, out, weapon_active);
        transport(g, now, cues);
        rustle(!g.on_mount && !g.in_vehicle && !g.swimming && g.foliage, g.foliage_height, g.speed, step_gain_,
               foliage_was_, next_brush_, now, cues);
        rustle(g.on_mount && g.horse_foliage, g.horse_foliage_height, g.mount_speed, horse_gain_, horse_foliage_was_,
               next_horse_brush_, now, cues);
        if (g.on_mount) splash(g.horse_wade, horse_wade_was_, g.mount_speed, horse_gain_, cues);
        else if (!g.in_vehicle && !g.swimming) splash(g.wade, wade_was_, g.speed, step_gain_ * 1.5f, cues);
    }
    if (!g.blocked) {                   // Arthur's own state: only while you play him
        // Gun leather, from the weapon in hand changing (the game's holster flag may rise before or after it): the gun
        // that left the hand is holstered, the new one drawn. The speaker only for guns the game carries in the hip
        // holster (attach point 2 / 3: every revolver and pistol and the sawed-off), not for long arms or tools.
        auto hip = [](int point) { return point == 2 || point == 3; };
        if (g.weapon != weapon_before_ && action_gain_ > 0) {
            LOGD("weapon change: 0x%08X -> 0x%08X, holstering %d", weapon_before_, g.weapon, int(g.holstering));
            if (armed_before_) {
                Cue c = make("gun_holster", action_gain_ * 1.2f, 0.5f, true);
                c.speaker = hip(attach_before_);
                cues.push_back(c);
            }
            if (g.armed) {
                Cue c = make("gun_draw", action_gain_ * 1.2f, 0.5f, true);
                c.speaker = hip(g.attach_point);
                delayed_.push_back({now + (armed_before_ ? 0.25 : 0.0), c});    // after the old gun has gone
            }
        }
        armed_before_ = g.armed;
        attach_before_ = g.attach_point;
        weapon_before_ = g.weapon;
        if (heart_gain_ > 0 && g.health_core < 20 && !g.dead_eye && now >= next_heart_) {
            next_heart_ = now + 0.9;
            cues.push_back(make("heartbeat", heart_gain_ * 0.9f));
        }
        if (cold_gain_ > 0 && g.temperature < -5 && now >= next_shiver_) {
            next_shiver_ = now + rng_.range(4.0f, 9.0f);
            cues.push_back(make("shiver", cold_gain_ * clampv((-g.temperature - 5) / 10.0f + 0.4f, 0.4f, 1.0f)));
        }
    }
    // a close blast's shock in both triggers: hard at first, dying away over ~0.45 s (the weapon's own trigger feel
    // steps aside only for that moment)
    double since = now - shock_t_;
    if (triggers_on_ && !g.halted && since >= 0 && since < 0.45) {
        int a = int(std::lround(shock_amp_ * (since < 0.15 ? 8 : since < 0.3 ? 5 : 2)));
        if (a > 0) {
            out.r2 = fx::vibration(0, a, 35);
            out.l2 = out.r2;
        }
    }
    lightbar(g, weapon, now, out);
}

}  // namespace dsr2
