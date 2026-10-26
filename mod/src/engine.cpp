#include "engine.h"

#include "log.h"

#include <fstream>

namespace dsr2 {

using nlohmann::json;
constexpr int kAimRaw = 40;

bool Calibration::load(const fs::path& p) {
    std::ifstream in(p);
    if (!in) return false;
    try {
        json j = json::parse(in);
        for (int i = 0; i < 10; ++i) {
            r2[i] = j["r2"][i].get<int>();
            l2[i] = j["l2"][i].get<int>();
        }
        calibrated = true;
    } catch (...) {
        return false;
    }
    return true;
}

static std::array<int, 10> zones_from(const json& j, const char* key, std::array<int, 10> def = {}) {
    if (!j.is_object() || !j.contains(key) || !j[key].is_array() || j[key].size() != 10) return def;
    std::array<int, 10> z{};
    for (int i = 0; i < 10; ++i) z[i] = clampv(j[key][i].get<int>(), 0, 8);
    return z;
}

static float jnum(const json& j, const char* k, float d) {
    if (!j.is_object()) return d;
    auto it = j.find(k);
    return it != j.end() && it->is_number() ? it->get<float>() : d;
}

static std::string jstr(const json& j, const char* k, const std::string& d = "") {
    if (!j.is_object()) return d;
    auto it = j.find(k);
    return it != j.end() && it->is_string() ? it->get<std::string>() : d;
}

static std::vector<int> jints(const json& j, const char* k) {
    std::vector<int> v;
    if (j.is_object() && j.contains(k) && j[k].is_array())
        for (auto& x : j[k]) v.push_back(x.get<int>());
    return v;
}

// Recoil on the trigger: a shove (the motor pushes back against your finger at full force, like a
// trigger slapping forward), then a lower, longer rumble that fades - shaped by the gun's recorded shot.
bool WeaponEngine::Kick::block(float dt, float slow, fx::Block& out) const {
    if (dt < 0 || steps.empty()) return false;
    float shove = 0.035f * slow;
    if (dt < shove) {
        out = fx::feedback(0, std::min(8, steps[0] + 1));
        return true;
    }
    float step = step_s * slow * 1.6f;
    size_t i = size_t((dt - shove) / step);
    if (i >= steps.size()) return false;
    out = fx::vibration(0, steps[i], std::max(18, int(freq * 0.75f)));
    return true;
}

WeaponEngine::WeaponEngine(const json& prof, const Calibration& cal, const Settings& s,
                           const std::vector<std::vector<int>>& kick_variants)
    : p_(prof), cal_(cal), set_(s), kick_variants_(kick_variants) {
    id_ = jstr(p_, "id", "?");
    kind_ = jstr(p_, "type", "gun");
    bank_ = jstr(p_, "bank");
    const json f = p_.value("fire", json::object());
    mode_ = jstr(f, "engine", "feedback");
    curve_ = zones_from(f, "curve");
    auto wf = jints(f, "weapon_effect");
    if (wf.size() == 3) weapon_fx_ = {wf[0], wf[1], wf[2]};
    auto sf = jints(f, "simple_weapon");
    if (sf.size() == 3) simple_fx_ = {sf[0], sf[1], sf[2]};
    if (f.contains("break_raw")) break_raw_ = f["break_raw"].get<int>();
    else if (mode_ == "weapon" || mode_ == "hybrid") break_raw_ = cal_.raw_at(weapon_fx_[1]) + s.fire_margin;
    else if (mode_ == "simple_weapon") break_raw_ = simple_fx_[1];
    else break_raw_ = cal_.raw_at(int(jnum(f, "break_zone", 6))) + s.fire_margin;
    reset_raw_ = cal_.raw_at(int(jnum(f, "reset_zone", 2)));
    if (reset_raw_ >= break_raw_ - 10) reset_raw_ = std::max(0, break_raw_ - 25);
    stop_zone_ = int(jnum(f, "stop_zone", 0));
    stop_strength_ = int(jnum(f, "stop_strength", 8));
    empty_feel_ = jstr(f, "empty", "click");
    after_curve_ = zones_from(p_, "after_shot", {1, 1, 1, 1, 1, 1, 1, 1, 1, 1});
    grit_ = jnum(f, "grit", 0);
    if (f.contains("ticks"))
        for (auto& t : f["ticks"]) ticks_[t.value("zone", 0)] = t;
    const json rec = p_.value("recoil", json::object());
    const json trig = rec.value("trigger", json::object());
    kick_.freq = int(jnum(trig, "freq", 40));
    kick_.base = jints(trig, "steps");
    kick_.step_s = jnum(trig, "step_ms", 16) / 1000;
    float ks = s.kick_scale * jnum(p_, "kick_scale", 1.0f);
    for (int a : kick_.base) kick_.steps.push_back(clampv(int(std::lround(a * ks)), 1, 8));
    lock_s_ = jnum(rec, "lock_ms", 5) / 1000;
    shot_haptic_ = jstr(rec, "haptic");
    haptic_gain_ = jnum(p_, "haptic_gain", 1.0f);
    rate_s_ = jnum(p_, "rate_ms", 400) / 1000;
    action_ = p_.value("action", json{{"type", "none"}});
    action_curve_ = zones_from(action_, "curve");
    action_break_raw_ = cal_.raw_at(int(jnum(action_, "break_zone", 7))) + s.fire_margin;
    if (action_.contains("ticks"))
        for (auto& t : action_["ticks"]) action_ticks_[t.value("zone", 0)] = t;
    clip_size_ = p_.contains("clip") && p_["clip"].is_number() ? p_["clip"].get<int>() : 0;
    clip_ = clip_size_;
    reload_ = p_.value("reload", json::object());
    if (s.aim_resistance) aim_block_ = fx::multi_feedback(zones_from(p_, "aim_curve"));
    bow_ = p_.value("draw", json::object());
    melee_ = p_.value("melee", json::object());
    tension_ = p_.value("tension", json::object());
    noise_phase_ = rng_.range(0, 100);
}

Cue WeaponEngine::cue(const std::string& name, float gain, int variant) const {
    Cue c;
    c.name = name;
    c.gain = gain;
    c.variant = variant;
    c.speed = speed();
    c.bank = bank_;
    c.speaker = kind_ == "tension";     // rope sounds: the game's own recordings where labelled
    return c;
}

void WeaponEngine::play(EngineFrame& f, const std::string& name, float gain, int variant) const {
    if (!name.empty()) f.cues.push_back(cue(name, gain, variant));
}

void WeaponEngine::schedule(double at, const std::string& name, float gain, int variant, bool has_pan, float pan) {
    if (name.empty()) return;
    Cue c = cue(name, gain, variant);
    c.has_pan = has_pan;
    c.pan = pan;
    timers_.push_back({at, c});
}

fx::Block WeaponEngine::fire_block(int raw, double now) {
    if (clip_size_ && clip_ == 0 && empty_feel_ == "dead")
        return fx::multi_feedback({0, 1, 1, 1, 1, 1, 1, 1, 1, 1});            // slide locked open: mush
    if (mode_ == "weapon") return fx::weapon(weapon_fx_[0], weapon_fx_[1], weapon_fx_[2]);
    if (mode_ == "simple_weapon") return fx::simple_weapon(simple_fx_[0], simple_fx_[1], simple_fx_[2]);
    if (mode_ == "hybrid" && raw >= cal_.raw_at(weapon_fx_[0]) - 6) return fx::weapon(weapon_fx_[0], weapon_fx_[1], weapon_fx_[2]);
    Zones z = curve_;
    if (mode_ == "hybrid")
        for (int i = weapon_fx_[0]; i < 10; ++i) z[i] = 0;
    if (dead_eye_)
        for (auto& v : z) if (v) v = std::min(8, v + 1);           // time thickens
    return fx::multi_feedback(texture(z, raw, now));
}

WeaponEngine::Zones WeaponEngine::texture(Zones z, int raw, double now) {
    int zone = cal_.zone_of(raw);
    for (auto it = bumps_.begin(); it != bumps_.end();) {
        if (now < it->second && z[it->first] > 0) z[it->first] = std::min(8, z[it->first] + 2);
        if (now >= it->second) it = bumps_.erase(it);
        else ++it;
    }
    float grit = std::min(1.0f, grit_ + game_grit_);
    if (grit > 0 && z[zone] > 0 && std::fabs(vel_) > 120) {
        if (now >= grit_until_) {
            int step = std::max(1, int(std::lround(grit * 2)));
            int choice = rng_.below(3) - 1;
            grit_zone_ = {zone, choice * step};
            grit_until_ = now + rng_.range(0.006f, 0.014f);
        }
        if (grit_zone_.first == zone) z[zone] = clampv(z[zone] + grit_zone_.second, 1, 8);
    }
    if (game_tremor_ > 0.05f && z[zone] > 0) {     // exhausted / freezing / drunk: the pull wavers
        float w = game_tremor_ * 1.5f * std::sin(2 * kPi * 7.5f * float(now) + noise_phase_);
        z[zone] = clampv(int(std::lround(z[zone] + w)), 1, 8);
    }
    return z;
}

fx::Block WeaponEngine::stop_block(const Zones* base) const {
    Zones z = base ? *base : Zones{};
    if (stop_zone_)
        for (int i = stop_zone_; i < 10; ++i) z[i] = std::max(z[i], stop_strength_);
    return fx::multi_feedback(z);
}

void WeaponEngine::crossed(const std::map<int, json>& ticks, int raw, EngineFrame& f, double now) {
    int zp = cal_.zone_of(prev_raw_), zn = cal_.zone_of(raw);
    for (int z = zp + 1; z <= zn; ++z) {
        auto it = ticks.find(z);
        if (it == ticks.end()) continue;
        play(f, jstr(it->second, "haptic"), jnum(it->second, "gain", 1));
        if (it->second.value("bump", true)) bumps_[z] = now + 0.015;
    }
}

EngineFrame WeaponEngine::update(const InputState& in, const GameHints& g) {
    double now = in.t;
    int raw = in.r2;
    l2_ = in.l2;
    double dt = now - prev_t_;
    if (dt > 0 && dt < 0.1) vel_ = 0.5f * vel_ + 0.5f * float((raw - prev_raw_) / dt);
    history_.push_back({now, raw});
    while (history_.size() > 200) history_.pop_front();
    EngineFrame f;
    f.l2 = aim_block_;
    uint32_t pressed = in.buttons & ~prev_buttons_;

    if (g.valid) {
        dead_eye_ = g.dead_eye;
        game_grit_ = g.grit;
        game_tremor_ = g.tremor;
        if (g.clip >= 0 && clip_size_) clip_ = g.clip;
        if (g.clip_max > 0 && clip_size_) clip_size_ = g.clip_max;
        if (std::fabs(g.kick_mult - game_kick_mult_) > 0.01f) {
            game_kick_mult_ = g.kick_mult;
            float ks = set_.kick_scale * jnum(p_, "kick_scale", 1.0f) * game_kick_mult_;
            kick_.steps.clear();
            for (int a : kick_.base) kick_.steps.push_back(clampv(int(std::lround(a * ks)), 1, 8));
        }
        if (game_tremor_ > 0.05f && aim_block_[0] != fx::OFF) {   // the gun's weight wobbles in tired hands
            Zones az = zones_from(p_, "aim_curve");
            float w = game_tremor_ * 1.2f * std::sin(2 * kPi * 6.0f * float(now));
            for (auto& v : az) if (v) v = clampv(int(std::lround(v + 1 + w)), 1, 8);
            f.l2 = fx::multi_feedback(az);
        }
    } else if (pressed & SQUARE && clip_size_ && clip_ < clip_size_ && (state_ == "ready" || state_ == "held")) {
        start_reload(now);
    }

    // Dead Eye: every target you paint ticks under your finger
    if (g.valid) {
        if (dead_eye_ && g.deadeye_marks > marks_) {
            play(f, "deadeye_mark");
            mark_tick_until_ = now + 0.035;
        }
        marks_ = g.deadeye_marks;
    }

    fx::Block blk;
    if (kind_ == "bow") blk = update_bow(raw, now, f);
    else if (kind_ == "auto") blk = update_auto(raw, now, f);
    else if (kind_ == "melee") blk = update_melee(pressed, now, f, g);
    else if (kind_ == "tension") blk = update_tension(raw, pressed, now, f, g);
    else if (kind_ == "tool") blk = fx::off();
    else blk = update_gun(raw, now, f, g);
    f.r2 = blk;
    if (now < mark_tick_until_) f.r2 = fx::vibration(0, 6, 60);

    if (dead_eye_ && now >= next_heartbeat_) {
        next_heartbeat_ = now + 0.85;
        Cue c;
        c.name = "heartbeat";
        c.gain = 0.8f;
        c.scripted = false;
        f.cues.push_back(c);
    }
    for (auto it = timers_.begin(); it != timers_.end();) {
        if (it->at <= now) {
            f.cues.push_back(it->cue);
            it = timers_.erase(it);
        } else {
            ++it;
        }
    }
    analyse(now);
    f.flash = now - shot_t_ >= 0 && now - shot_t_ < 0.06 && (kind_ == "gun" || kind_ == "auto" || kind_ == "bow");
    f.game_rt = game_rt_;
    if (kind_ == "melee" || kind_ == "tool" || kind_ == "tension") f.game_rt = -1;
    f.state = state_;
    prev_raw_ = raw;
    prev_t_ = now;
    prev_buttons_ = in.buttons;
    return f;
}

// ---------------- guns & throwables ----------------
fx::Block WeaponEngine::update_gun(int raw, double now, EngineFrame& f, const GameHints& g) {
    if (g.valid) {
        if (g.reloading && state_ != "reloading") {
            state_ = "reloading";
            game_rt_ = 0;
        } else if (!g.reloading && state_ == "reloading") {
            state_ = "ready";
        }
        // fire-rate sync: a shot we felt but the game did not take means we re-armed too early
        if (unconfirmed_since_ > 0 && !ready_usable_) {
            if (g.shooting) unconfirmed_since_ = -1;
            else if (now - unconfirmed_since_ > 0.3) {
                rate_s_ = std::min(2.5f, rate_s_ * 1.12f);
                LOGI("%s: the game skipped a shot - re-arm delay now %.0f ms", id_.c_str(), rate_s_ * 1000);
                unconfirmed_since_ = -1;
            }
        }
    }
    // Dead Eye volley: the game fires the marked shots by itself - each one kicks as it really goes off
    if (g.valid) {
        bool fired = (g.shooting && !was_shooting_) || (g.clip >= 0 && last_clip_ >= 0 && g.clip < last_clip_);
        was_shooting_ = g.shooting;
        last_clip_ = g.clip;
        if (dead_eye_ && fired && now - shot_t_ > 0.14 && now - kick_t_ > 0.14) {
            shot_t_ = now;
            kick_t_ = now;
            last_dry_ = false;
            schedule(now, shot_haptic_, haptic_gain_);
        }
        if (dead_eye_ && now - kick_t_ >= 0 && now - kick_t_ < kick_.duration(slow())) {
            fx::Block k;
            if (kick_.block(float(now - kick_t_), slow(), k)) return k;
        }
    }
    const std::string st = state_;
    if (st == "ready") {
        crossed(ticks_, raw, f, now);
        std::string pre = jstr(p_, "pre");
        if (!pre.empty() && cal_.zone_of(prev_raw_) < 2 && cal_.zone_of(raw) >= 2) play(f, pre);
        if (raw >= break_raw_) {
            shoot(raw, now, f);
            return stop_block();
        }
        return fire_block(raw, now);
    }
    if (st == "held") {
        if (raw <= reset_raw_) game_rt_ = 0;
        double kdt = now - kick_t_;
        fx::Block k;
        if (!last_dry_ && kdt < kick_.duration(slow())) return kick_.block(float(kdt), slow(), k) ? k : stop_block();
        bool game_rate = g.valid && ready_usable_;
        if (game_rate && !g.ready && raw <= reset_raw_) {
            if (not_ready_since_ < 0) not_ready_since_ = now;
            // a manual action (single-action hammer, lever, bolt, pump) that isn't ready needs its R2 stroke
            std::string at0 = jstr(action_, "type", "none");
            if (at0 != "none" && at0 != "semi" && set_.manual_action && clip_ != 0 && now - shot_t_ > 0.08) {
                state_ = "action";
                not_ready_since_ = -1;
                return fx::multi_feedback(action_curve_);
            }
            if (now - not_ready_since_ > 2.5) {          // never became ready: don't trust the signal for this gun
                ready_usable_ = false;
                LOGI("%s: the game's 'ready to shoot' never came back - using timing for this gun", id_.c_str());
            }
        }
        bool can_rearm = game_rate ? g.ready : now - shot_t_ >= rate_s_ * slow();
        if (can_rearm && raw <= reset_raw_ && now - shot_t_ > 0.05) {
            not_ready_since_ = -1;
            if (last_dry_ && clip_size_ && !g.valid) {
                start_reload(now);
                return fx::off();
            }
            std::string at = jstr(action_, "type", "none");
            if (!game_rate && at != "none" && at != "semi" && set_.manual_action && clip_ != 0) {
                state_ = "action";
                return fx::multi_feedback(action_curve_);
            }
            state_ = "ready";
            if (p_.value("fire", json::object()).value("reset_click", true) && !last_dry_) play(f, "reset_click");
            return fire_block(raw, now);
        }
        return stop_block(&after_curve_);
    }
    if (st == "action") {                         // manual cocking / cycling press
        if (g.valid && ready_usable_ && g.ready && raw <= reset_raw_) {   // the game cocked it itself
            state_ = "ready";
            return fire_block(raw, now);
        }
        crossed(action_ticks_, raw, f, now);
        if (raw >= action_break_raw_) {
            bool fan = action_.value("fan", false) && set_.fanning && l2_ < kAimRaw && now - shot_t_ < 0.9 * slow();
            if (fan) {                     // palm slaps the hammer: cock and fire in one stroke
                play(f, "hammer_cock_auto", 0.7f);
                shoot(raw, now, f, true);
                return stop_block();
            }
            Cue c = cue(jstr(action_, "open"));
            c.speaker = true;
            if (!c.name.empty()) timers_.push_back({now, c});
            state_ = "cycling";
            action_t_ = now;
            game_rt_ = 255;
            return fx::off();
        }
        return fx::multi_feedback(action_curve_);
    }
    if (st == "cycling") {
        bool done = g.valid && ready_usable_ ? g.ready : now - action_t_ >= jnum(action_, "min_ms", 120) / 1000;
        if (raw <= reset_raw_ && done) {
            Cue c = cue(jstr(action_, "close"));
            c.speaker = true;
            if (!c.name.empty()) timers_.push_back({now, c});
            state_ = "ready";
            game_rt_ = 0;
            return fire_block(raw, now);
        }
        return fx::off();
    }
    if (st == "reloading") return g.valid ? fx::off() : update_reload(now, f);
    return fx::off();
}

void WeaponEngine::shoot(int raw, double now, EngineFrame& f, bool fanned) {
    bool empty = clip_size_ && clip_ == 0;
    state_ = "held";
    shot_t_ = now;
    game_rt_ = 255;
    kick_t_ = now + std::max(double(lock_s_ * slow()), set_.audio_latency_ms / 1000.0);
    last_dry_ = empty;
    if (empty) {
        if (empty_feel_ == "click") {
            Cue c = cue(jstr(p_, "dry", "dry_fire"));
            c.speaker = true;
            f.cues.push_back(c);
        }
        return;
    }
    if (clip_size_) clip_ = std::max(0, clip_ - 1);
    ++shots_;
    unconfirmed_since_ = kind_ == "gun" ? now : -1;
    int variant = -1;
    if (!kick_variants_.empty()) {
        variant = rng_.below(int(kick_variants_.size()));
        const auto& a = kick_variants_[size_t(variant)];
        float ks = set_.kick_scale * jnum(p_, "kick_scale", 1.0f) * game_kick_mult_;
        kick_.steps.clear();
        for (size_t i = 0; i < kick_.base.size(); ++i) {
            int au = i < a.size() ? a[i] : 1;
            kick_.steps.push_back(clampv(int(std::lround(std::min(kick_.base[i], au) * ks)), 1, 8));
        }
    }
    schedule(now + lock_s_ * slow(), shot_haptic_, haptic_gain_, variant);
    std::string at = jstr(action_, "type", "none");
    if (!set_.manual_action || at == "semi") {
        Cue c = cue(jstr(action_, "auto"));
        c.speaker = true;
        if (!c.name.empty()) timers_.push_back({now + jnum(action_, "auto_ms", 200) / 1000 * slow(), c});
    }
    if (kind_ == "throw" && p_.contains("explode") && set_.scheduled_explosions) {
        const json ex = p_["explode"];
        schedule(now + jnum(ex, "after_ms", 2500) / 1000 * slow(), jstr(ex, "haptic", "explosion_far"), jnum(ex, "gain", 1));
    }
    if (!fanned) pending_.push_back({now, raw});
}

void WeaponEngine::start_reload(double now) {
    if (!clip_size_) return;
    state_ = "reloading";
    reload_t_ = now;
    game_rt_ = 0;
    reload_ticks_done_ = 0;
    reload_rounds_ = reload_.value("per_round", false) ? clip_size_ - clip_ : 1;
    last_dry_ = false;
    Cue c = cue(jstr(reload_, "begin"));
    c.speaker = true;
    if (!c.name.empty()) timers_.push_back({now, c});
}

fx::Block WeaponEngine::update_reload(double now, EngineFrame& f) {
    float tick = jnum(reload_, "tick_ms", 400) / 1000 * slow(), start = jnum(reload_, "start_ms", 300) / 1000 * slow();
    double el = now - reload_t_;
    int due = el < start ? 0 : std::min(reload_rounds_, int((el - start) / tick) + 1);
    while (reload_ticks_done_ < due) {
        ++reload_ticks_done_;
        if (set_.reload_ticks) {
            Cue c = cue(jstr(reload_, "tick", "reload_round"));
            c.speaker = true;
            f.cues.push_back(c);
        }
    }
    if (el >= start + reload_rounds_ * tick + jnum(reload_, "end_ms", 250) / 1000 * slow()) {
        clip_ = clip_size_;
        play(f, jstr(reload_, "end"));
        state_ = "ready";
    }
    return fx::off();
}

// ---------------- mounted machine guns ----------------
fx::Block WeaponEngine::update_auto(int raw, double now, EngineFrame& f) {
    double interval = 60.0 / jnum(p_, "rpm", 400) / speed();
    if (state_ == "ready") {
        if (raw >= break_raw_) {
            state_ = "firing";
            shot_t_ = now - interval;
            game_rt_ = 255;
        } else {
            return fire_block(raw, now);
        }
    }
    if (state_ == "firing") {
        if (raw <= reset_raw_) {
            state_ = "ready";
            game_rt_ = 0;
            return fire_block(raw, now);
        }
        if (now - shot_t_ >= interval) {
            shot_t_ = now;
            ++shots_;
            schedule(now, shot_haptic_, haptic_gain_);
        }
        int amp = kick_.steps.empty() ? 6 : kick_.steps[0];
        return fx::vibration(0, amp, std::max(1, int(std::lround(1 / interval))));
    }
    return fx::off();
}

// ---------------- bow ----------------
fx::Block WeaponEngine::update_bow(int raw, double now, EngineFrame& f) {
    int start_raw = cal_.raw_at(int(jnum(bow_, "start_zone", 2)));
    int pos = int(jnum(bow_, "position", 1));
    double draw_s = jnum(bow_, "draw_ms", 900) / 1000 / speed();
    if (state_ == "ready") {
        if (raw >= start_raw) {
            state_ = "draw";
            draw_t_ = now;
            game_rt_ = 255;
            play(f, jstr(bow_, "creak"));
        } else {
            return fx::feedback(pos, int(jnum(bow_, "rest_strength", 1)));
        }
    }
    if (state_ == "draw") {
        float p = float(std::min(1.0, (now - draw_t_) / draw_s));
        if (raw < start_raw - 8) {
            game_rt_ = 0;
            state_ = "held";
            shot_t_ = now;
            last_dry_ = false;
            if (p >= jnum(bow_, "min_draw", 0.35f)) {
                ++shots_;
                play(f, shot_haptic_.empty() ? "bow_release" : shot_haptic_, 0.35f + 0.65f * p);
                kick_t_ = now + set_.audio_latency_ms / 1000;
                schedule(now + rate_s_ * 0.7, jstr(bow_, "nock", "bow_nock"));
            } else {
                play(f, "bow_letdown");
                kick_t_ = -10;
            }
            return fx::off();
        }
        float eased = 1 - (1 - p) * (1 - p);
        float lo = jnum(bow_, "strength_from", 2), hi = jnum(bow_, "strength_to", 7);
        float strength = lo + (hi - lo) * eased;
        double hold = now - draw_t_ - draw_s - jnum(bow_, "tremor_after_ms", 2500) / 1000;
        float tremor = game_tremor_;
        if (hold > 0) tremor += float(std::min(1.0, hold / 2.0));
        if (tremor > 0) {
            float depth = jnum(bow_, "tremor_depth", 2) * std::min(1.5f, tremor);
            strength += depth * std::sin(2 * kPi * jnum(bow_, "tremor_hz", 9) * float(now)) + rng_.range(-0.4f, 0.4f) * depth;
        }
        return fx::feedback(pos, clampv(int(std::lround(strength)), 1, 8));
    }
    if (state_ == "held") {
        fx::Block k;
        if (now - kick_t_ < kick_.duration(slow()) && kick_.block(float(now - kick_t_), slow(), k)) return k;
        if (now - shot_t_ >= rate_s_ && raw < start_raw) state_ = "ready";
        return fx::off();
    }
    return fx::off();
}

// ---------------- melee ----------------
fx::Block WeaponEngine::update_melee(uint32_t pressed, double now, EngineFrame& f, const GameHints& g) {
    float sl = slow();
    auto impacts = [&]() {
        std::vector<std::string> v;
        if (melee_.contains("impact") && melee_["impact"].is_array())
            for (auto& x : melee_["impact"]) v.push_back(x.get<std::string>());
        else v.push_back(jstr(melee_, "impact", "impact_blade"));
        return v;
    };
    auto land = [&](const std::string& result, float pan, double at) {
        bool finisher = result == "hit" && combo_ >= int(jnum(melee_, "finisher_at", 3)) && !jstr(melee_, "finisher").empty();
        std::string name;
        if (result == "hit") {
            auto v = impacts();
            name = finisher ? jstr(melee_, "finisher") : v[size_t(rng_.below(int(v.size())))];
        } else if (result == "blocked") {
            name = jstr(melee_, "blocked", "melee_blocked");
        } else {
            name = jstr(melee_, "miss", "melee_miss");
        }
        schedule(at, name, 1.0f, -1, true, pan);
        if (finisher) combo_ = 0;
        last_strike_ = finisher ? "finisher" : result;
        LOGD("strike: %s", last_strike_.c_str());
    };
    // in game: resolve pending strikes from real damage
    if (g.valid) {
        for (auto& s : strikes_) {
            if (s.done) continue;
            if (g.melee_hits > s.hits_at_start) {
                s.done = true;
                land("hit", s.pan, now);
            } else if (now > s.deadline) {
                s.done = true;
                land(g.melee_target_near ? "blocked" : "miss", s.pan, now);
            }
        }
        strikes_.erase(std::remove_if(strikes_.begin(), strikes_.end(), [](const Strike& s) { return s.done; }), strikes_.end());
    }
    if (!(pressed & R1) || now - shot_t_ <= jnum(melee_, "recover_ms", 330) / 1000 * sl) return fx::off();
    bool in_combo = last_strike_ == "hit" && now - shot_t_ < jnum(melee_, "combo_ms", 1100) / 1000 * sl;
    combo_ = in_combo ? combo_ + 1 : 1;
    shot_t_ = now;
    ++shots_;
    hand_ = melee_.value("alternate", false) ? -hand_ : 1;
    float pan = 0.65f * hand_;
    Cue sw = cue(jstr(melee_, "swing", "melee_swing"));
    sw.has_pan = true;
    sw.pan = pan;
    f.cues.push_back(sw);
    double impact_at = now + jnum(melee_, "impact_ms", 140) / 1000 * sl;
    if (g.valid) {
        strikes_.push_back({impact_at + 0.3 * sl, pan, g.melee_hits, false});
    } else {
        std::string result = l2_ < kAimRaw ? "miss" : (rng_.uniform() < jnum(melee_, "block_chance", 0.15f) ? "blocked" : "hit");
        land(result, pan, result == "miss" ? impact_at + 0.04 * sl : impact_at);
    }
    return fx::off();
}

// ---------------- lasso / fishing ----------------
// Fishing, from the game's own fishing task. On a controller R2 casts and strikes, L2 grips the rod and the
// reel is the right stick - so L2 carries the line: its tension, the fish's surges, the strain before it snaps.
fx::Block WeaponEngine::update_fishing(int raw, double now, EngineFrame& f, const GameHints& g) {
    (void)raw;
    const FishingState& fs = g.fishing;
    int st = fs.active ? fs.state : 0;
    double dt = now - fish_t_;
    fish_t_ = now;
    if (dt <= 0 || dt > 0.1) dt = 0;
    int was = fish_state_;
    fish_state_ = st;
    if (st != was) {
        if (st == 4) play(f, "cast");                                         // the line flies out
        if (st == 7) {                                                        // struck: the hook bites in
            play(f, "fish_hooked", clampv(0.6f + fs.weight_lb / 25.0f, 0.6f, 1.0f));
            fish_peak_ = 0;
        }
        if (was == 7 && st == 12) {                                          // landed
            play(f, "fish_landed", clampv(0.5f + fs.weight_lb / 20.0f, 0.5f, 1.0f));
            next_flop_ = now + 0.6;
            flop_until_ = now + clampv(3.0 + fs.weight_lb / 4.0, 3.0, 8.0);
        } else if (was == 7) {                                                // gone: snapped, or it threw the hook
            play(f, fish_peak_ > 0.85f ? "line_snap" : "line_slack");
        }
    }
    // a fish takes the bait while the line waits (and the nibbles before, if the game shows them)
    bool waiting = st == 6 || st == 10;
    bool bite = waiting && fs.weight_lb > 0;
    if (bite && !fish_bite_) {
        play(f, "fish_bite");
        bite_until_ = now + 0.7;
    }
    fish_bite_ = bite;
    if (waiting && (fs.cmd & 512) && !(fish_cmd_ & 512)) {
        play(f, "fish_tug", 0.45f);
        nibble_until_ = now + 0.12;
    }
    fish_cmd_ = fs.cmd;

    if (st == 7) {
        fish_peak_ = std::max(fish_peak_ * 0.995f, fs.tension);
        if (fs.tension > 0.85f) f.l2 = fx::vibration(0, 8, 30);              // about to snap: ease off!
        else f.l2 = fx::feedback(0, clampv(int(1 + std::lround(fs.tension * 7)), 1, 8));
        if (fs.struggle > 0.5f && now >= next_surge_) {                       // it fights: surges to its side
            next_surge_ = now + rng_.range(0.22f, 0.6f);
            Cue c = cue("fish_tug", 0.45f + 0.55f * fs.tension);
            if (fs.side >= 0) {
                c.has_pan = true;
                c.pan = clampv((fs.side - 0.5f) * 2.0f, -1.0f, 1.0f);
            }
            f.cues.push_back(c);
        }
        if (fs.reel > 0.02f) {                                                // the spool clicks as you reel
            reel_acc_ += float(dt) * 16.0f * std::min(1.0f, fs.reel);
            if (reel_acc_ >= 1) {
                reel_acc_ -= 1;
                play(f, "reel_click", 0.3f + 0.3f * fs.tension);
            }
        }
    } else if (st == 12 && now < flop_until_ && now >= next_flop_) {          // flapping in your hand
        next_flop_ = now + rng_.range(0.45f, 1.2f);
        play(f, "fish_flop", rng_.range(0.5f, 0.9f));
    }
    // R2: loading the cast, then the strike when it bites
    if (waiting) {
        if (now < bite_until_) return fx::vibration(2, 7, 9);
        if (now < nibble_until_) return fx::vibration(2, 3, 14);
        return fx::feedback(3, 1);
    }
    if (st == 2 || st == 3) return fx::multi_feedback({0, 0, 1, 1, 2, 2, 3, 3, 3, 3});
    return fx::off();
}

fx::Block WeaponEngine::update_tension(int raw, uint32_t pressed, double now, EngineFrame& f, const GameHints& g) {
    if (g.valid && id_ == "WEAPON_FISHINGROD") return update_fishing(raw, now, f, g);
    const json& tn = tension_;
    auto jerk_gap = [&]() {
        auto v = jints(tn, "jerk_every_ms");
        float lo = v.size() == 2 ? float(v[0]) : 600, hi = v.size() == 2 ? float(v[1]) : 1800;
        return rng_.range(lo, hi) / 1000;
    };
    bool live = g.valid && id_.find("LASSO") != std::string::npos;
    if (live) {                                              // the game tells us when the rope is on something
        if (g.lasso_attached && state_ != "tethered") {
            state_ = "tethered";
            tether_t_ = now;
            play(f, jstr(tn, "catch"));
        } else if (!g.lasso_attached && state_ == "tethered") {
            state_ = "ready";
        }
    }
    if (state_ == "ready") {
        if (raw >= break_raw_ && cal_.zone_of(prev_raw_) < cal_.zone_of(break_raw_)) {
            play(f, shot_haptic_);
            if (!live) {
                state_ = "flying";
                shot_t_ = now;
            }
            return fx::off();
        }
        return fire_block(raw, now);
    }
    if (state_ == "flying") {
        if (now - shot_t_ >= jnum(tn, "catch_ms", 500) / 1000 / speed()) {
            state_ = "tethered";
            tether_t_ = now;
            play(f, jstr(tn, "catch"));
            next_jerk_ = now + jerk_gap();
        }
        return fx::off();
    }
    if (state_ == "tethered") {
        if (!live && ((pressed & CIRCLE) || now - tether_t_ > jnum(tn, "hold_s", 12))) {
            state_ = "ready";
            return fx::off();
        }
        float t = float(now) * 1.3f + noise_phase_;
        float noise = 0.5f + 0.25f * std::sin(t) + 0.15f * std::sin(2.7f * t + 1) + 0.1f * std::sin(6.1f * t + 2);
        float pull = live ? 0.6f * g.lasso_pull + 0.4f * noise : noise;
        float strength = jnum(tn, "base", 3) + jnum(tn, "range", 4) * pull;
        if (raw >= break_raw_) strength += 1;
        bool jerk = live ? g.lasso_pull - lasso_prev_ > 0.25f : now >= next_jerk_;
        lasso_prev_ = g.lasso_pull;
        if (jerk && now > jerk_until_ + 0.25) {
            next_jerk_ = now + jerk_gap();
            jerk_until_ = now + 0.07;
            play(f, jstr(tn, "jerk"));
        }
        if (now < jerk_until_) strength = 8;
        return fx::feedback(1, clampv(int(std::lround(strength)), 1, 8));
    }
    return fx::off();
}

// ---------------- auto-align: fire exactly where this trigger really snaps ----------------
void WeaponEngine::analyse(double now) {
    for (auto it = pending_.begin(); it != pending_.end();) {
        if (now - it->t < 0.06) { ++it; continue; }
        double t0 = it->t - 0.05, t1 = it->t + 0.06;
        float best_v = 0;
        int snap_from = -1;
        std::vector<float> speeds;
        const std::pair<double, int>* prev = nullptr;
        for (auto& h : history_) {
            if (h.first < t0 || h.first > t1) continue;
            if (prev) {
                float v = float((h.second - prev->second) / std::max(1e-4, h.first - prev->first));
                speeds.push_back(std::fabs(v));
                if (v > best_v) { best_v = v; snap_from = prev->second; }
            }
            prev = &h;
        }
        it = pending_.erase(it);
        if (speeds.size() < 2 || snap_from < 0) continue;
        std::sort(speeds.begin(), speeds.end());
        if (best_v < 1500 || best_v < 3 * speeds[speeds.size() / 2]) continue;
        // a real break can only happen where this gun's wall is: from one zone before the configured
        // break to three zones after it. Anything else is a fast pull or a tap, not a snap.
        int bz = int(jnum(p_.value("fire", json::object()), "break_zone", 6));
        if (snap_from < cal_.raw_at(std::max(1, bz - 1)) || snap_from > cal_.raw_at(std::min(10, bz + 3))) {
            LOGD("%s: ignored a jump at raw %d (not where the wall is)", id_.c_str(), snap_from);
            continue;
        }
        snaps_.push_back(snap_from);
        if (snaps_.size() > 5) snaps_.erase(snaps_.begin());
        if (set_.auto_align && snaps_.size() >= 3 && kind_ == "gun") {
            std::vector<int> s = snaps_;
            std::sort(s.begin(), s.end());
            int target = s[s.size() / 2] + 2;
            if (std::abs(target - break_raw_) >= 3) {
                LOGI("%s: shot point %d -> %d (the trigger snaps at ~%d)", id_.c_str(), break_raw_, target, target - 2);
                break_raw_ = target;
                reset_raw_ = std::min(reset_raw_, target - 25);
            }
        }
    }
}

}  // namespace dsr2
