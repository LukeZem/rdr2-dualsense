#include "core.h"

#include "config.h"
#include "input.h"
#include "log.h"
#include "world.h"

namespace dsr2 {

Core& core() {
    static Core c;
    return c;
}

void Core::load_data() {
    Config& c = config();
    c.load((module_dir() / "DualSenseRDR2.ini").wstring());
    log::set_debug(c.flag("General", "Debug", false));
    triggers_on_ = c.flag("Triggers", "Enabled", true);
    haptics_on_ = c.flag("Haptics", "Enabled", true);
    speaker_mechanics_ = c.flag("Speaker", "Mechanics", true);
    settings_ = Settings{};
    settings_.manual_action = c.flag("Triggers", "ManualCocking", true);
    settings_.fanning = c.flag("Triggers", "Fanning", true);
    settings_.auto_align = c.flag("Triggers", "AutoAlign", true);
    settings_.fire_margin = c.integer("Triggers", "FireMargin", 4);
    settings_.kick_scale = c.num("Triggers", "KickStrength", 1.0f);
    settings_.aim_resistance = c.flag("Triggers", "AimResistance", true);
    settings_.reload_ticks = !in_game_;
    settings_.scheduled_explosions = !in_game_ || c.num("Haptics", "GameAudio", 0.0f) <= 0;
    cal_ = Calibration{};
    if (cal_.load(data_dir() / "calibration.json")) LOGI("calibration loaded");
    else LOGI("no calibration.json - estimated trigger zones (auto-align learns where your triggers break)");
    catalog_.load(data_dir() / "weapons.json");
    fs::path game_dir = module_dir();
    std::string override_dir = c.str("General", "GameDir", "");       // test harness: point at the game
    if (!override_dir.empty()) game_dir = fs::path(override_dir);
    game_audio_.discover(game_dir, data_dir() / "sound_labels.json");
    lib_.load(data_dir() / "haptics.json", c.flag("Haptics", "GameShots", true) ? &game_audio_ : nullptr);
    features_.configure();
    input().configure();
    audio_.set_strength(c.num("Haptics", "Strength", 1.0f));
    audio_.set_speaker_volume(c.num("Speaker", "Volume", 0.35f));
    audio_.set_duck(c.num("Haptics", "Duck", 0.3f));
    audio_.set_rumble_gain(c.num("Haptics", "GameRumble", 0.35f));
    audio_.set_game_audio_gain(c.num("Haptics", "GameAudio", 0.0f));
    engine_.reset();
    engine_key_ = 0;
}

bool Core::init(bool in_game, const std::string& test_weapon) {
    in_game_ = in_game;
    test_weapon_ = test_weapon;
    load_data();
    Config& c = config();
    if (!c.flag("General", "Enabled", true)) {
        LOGI("disabled in DualSenseRDR2.ini");
        return false;
    }
    if (in_game) input().install_hook();
    audio_.start(&lib_);
    audio_.start_game_audio(c.num("Haptics", "GameAudio", 0.0f), c.str("Haptics", "GameAudioDevice", ""));
    if (c.flag("Mic", "WhistleForHorse", false))
        audio_.start_mic(c.num("Mic", "Sensitivity", 1.0f), [this] { whistle_at_ = now_s(); });   // acted on in on_input
    if (c.flag("Voice", "Enabled", false)) {
        // each command may list several spellings/words, comma separated: chao = ciao / chow
        auto words = [&](const char* key, const char* def) {
            std::vector<std::string> out;
            std::string cur;
            for (char ch : c.str("Voice", key, def) + ",") {
                if (ch == ',') {
                    while (!cur.empty() && cur.back() == ' ') cur.pop_back();
                    if (!cur.empty()) out.push_back(cur);
                    cur.clear();
                } else if (ch != ' ' || !cur.empty()) {
                    cur += char(tolower((unsigned char)ch));
                }
            }
            return out;
        };
        voice_greet_ = words("Phrase", "ciao,chow");
        voice_calm_ = words("CalmPhrase", "easy,easy boy,easy girl,steady");
        voice_stop_ = words("StopPhrase", "");
        voice_spur_ = words("SpeedPhrase", "");
        std::vector<std::string> phrases = voice_greet_;
        phrases.insert(phrases.end(), voice_calm_.begin(), voice_calm_.end());
        phrases.insert(phrases.end(), voice_stop_.begin(), voice_stop_.end());
        phrases.insert(phrases.end(), voice_spur_.begin(), voice_spur_.end());
        voice_.start(phrases, c.num("Voice", "MinConfidence", 0.7f), [this](const std::string& said, float conf) {
            last_command_t_ = now_s();
            LOGI("voice: \"%s\" (confidence %.2f)", said.c_str(), conf);
            auto in = [&](const std::vector<std::string>& v) { return std::find(v.begin(), v.end(), said) != v.end(); };
            if (in_game_) {
                if (in(voice_greet_)) world().request_greet();
                else if (in(voice_calm_)) world().request_horse(World::HorseCalm);
                else if (in(voice_stop_)) world().request_horse(World::HorseStop);
                else if (in(voice_spur_)) world().request_horse(World::HorseSpur);
            } else {                                 // test program: just confirm
                confirm();
                printf("\n  >>> %s\n", in(voice_greet_) ? "CHAO" : in(voice_calm_) ? "EASY (calm the horse)" : in(voice_stop_) ? "WHOA (stop the horse)" : "FASTER (spur the horse)");
            }
        });
    }
    pad_.start([this](const InputState& s, OutputState& out) { return on_input(s, out); });
    LOGI("started (%s)", in_game ? "in game" : "standalone test");
    return true;
}

// "heard you": two firm thumps and a short lightbar flash
void Core::confirm() {
    Cue ack;
    ack.name = "whistle_ack";
    ack.gain = config().num("Mic", "Confirm", 1.0f);
    ack.scripted = false;
    if (ack.gain > 0) audio_.play(ack);
    audio_.ack_flash_until = now_s() + 0.35;
}

void Core::shutdown() {
    pad_.stop();
    voice_.stop();
    audio_.stop();
    LOGI("stopped");
}

void Core::build_engine(const nlohmann::json& prof0, const std::string& name) {
    if (engine_) learned_break_[engine_->id()] = engine_->break_raw();
    engine_.reset();
    engine_name_ = name;
    if (prof0.is_null()) return;
    nlohmann::json prof = prof0;
    std::string shot = lib_.ensure_weapon(prof);
    std::vector<std::vector<int>> kicks;
    if (!shot.empty()) {
        prof["recoil"]["haptic"] = shot;
        kicks = lib_.kicks(shot);
    }
    auto lb = learned_break_.find(prof.value("id", std::string()));
    if (lb != learned_break_.end()) prof["fire"]["break_raw"] = lb->second;
    Settings s = settings_;
    s.audio_latency_ms = std::min(25.0f, audio_.latency_ms());
    try {
        engine_ = std::make_unique<WeaponEngine>(prof, cal_, s, kicks);
        LOGI("weapon: %s (%s, fires at raw %d)", name.c_str(), engine_->kind().c_str(), engine_->break_raw());
    } catch (const std::exception& e) {
        LOGE("profile %s: %s", name.c_str(), e.what());
    }
}

bool Core::on_input(const InputState& s, OutputState& out) {
    if (reload_requested_.exchange(false)) {
        load_data();
        LOGI("settings and data reloaded");
    }
    GameSnapshot g = in_game_ ? world().snapshot() : GameSnapshot{};
    std::vector<WorldEvent> events = in_game_ ? world().take_events() : std::vector<WorldEvent>{};

    // a whistle is acted on at once - unless the speech recognizer has just heard / guessed a command ("chao")
    double wt = whistle_at_.load();
    if (wt > 0) {
        whistle_at_ = -1;
        double ct = std::max(last_command_t_.load(), voice_.last_command_guess.load());
        bool playing = !in_game_ || (g.valid && !g.blocked && !g.menu && !g.wheel);
        if (ct > wt - 1.0 && ct <= wt + 0.05) {
            LOGI("whistle ignored: it was a spoken word");
        } else if (!playing) {
            LOGI("whistle ignored: a menu is open / not playing");
        } else {
            input().inject(XINPUT_GAMEPAD_DPAD_UP, 0.25);
            confirm();
            if (!in_game_) printf("\n  >>> WHISTLE\n");
        }
    }

    // which weapon is in hand
    uint32_t key = 0;
    if (in_game_) {
        if (g.valid && !g.blocked && g.weapon) key = g.weapon;
    } else if (!test_weapon_.empty()) {
        key = joaat(test_weapon_);
    }
    if (key != engine_key_) {
        engine_key_ = key;
        if (!key) build_engine(nlohmann::json(), "");
        else if (in_game_) {
            std::string name;
            nlohmann::json p = catalog_.resolve(key, g.group, name);
            if (p.is_null()) LOGI("weapon 0x%08X (group 0x%08X) not in the catalog - no trigger effects", key, g.group);
            build_engine(p, name.empty() ? "unknown" : name);
        } else {
            build_engine(catalog_.resolve_name(test_weapon_), test_weapon_);
        }
    }

    GameHints h;
    if (in_game_ && g.valid) {
        h.valid = true;
        h.clip = g.clip;
        h.clip_max = g.clip_max;
        h.reloading = g.reloading;
        h.shooting = g.shooting;
        h.dead_eye = g.dead_eye;
        h.grit = g.grit;
        h.kick_mult = g.kick_mult;
        h.tremor = g.tremor;
        h.lasso_attached = g.lasso_attached;
        h.lasso_pull = g.lasso_pull;
        h.melee_hits = g.melee_hits;
        h.melee_target_near = g.melee_target_near;
        h.hip_fire = !g.aiming;
        h.ready = g.ready;
        h.fishing = g.fishing;
        h.deadeye_marks = g.deadeye_marks;
    }
    // weapon / item wheel: L2/R2 switch weapons there - not shots. Pause the trigger engine while it is
    // open (L1 held, or the game says so) and until R2 has been let go afterwards.
    if (s.pressed(L1)) { if (l1_since_ < 0) l1_since_ = s.t; } else l1_since_ = -1;
    bool wheel = (l1_since_ >= 0 && s.t - l1_since_ > 0.12) || (in_game_ && g.wheel);
    if (wheel) { wheel_until_ = s.t + 0.25; need_r2_release_ = true; }
    if (need_r2_release_ && s.t > wheel_until_ && s.r2 < 25) need_r2_release_ = false;
    bool paused = s.t < wheel_until_ || need_r2_release_;
    EngineFrame frame;
    bool weapon_active = engine_ && triggers_on_ && !paused && !(in_game_ && (g.blocked || g.swimming));
    if (engine_ && !paused) frame = engine_->update(s, h);
    std::vector<Cue> cues = frame.cues;
    for (auto& c : cues) c.speaker = c.speaker && speaker_mechanics_;
    if (weapon_active) {
        out.r2 = frame.r2;
        out.l2 = frame.l2;
    }
    features_.update(s, g, std::move(events), engine_ ? &frame : nullptr, weapon_active,
                     engine_ ? engine_->clip() : -1, engine_ ? engine_->clip_size() : 0, audio_.mic_listening(), out, cues);
    // in the wheel L2/R2 browse weapons: each press is a light selector click (a detent that gives way),
    // with a small tick - a switch, not a shot. After closing it R2 stays loose until let go.
    if (s.t < wheel_until_ && triggers_on_) {
        out.r2 = fx::weapon(2, 4, 3);
        out.l2 = fx::weapon(2, 4, 3);
        int click_r = cal_.raw_at(4, true), click_l = cal_.raw_at(4, false);
        Cue tick;
        tick.name = "wheel_tick";
        tick.gain = config().num("Haptics", "WheelClick", 0.6f);
        tick.has_pan = true;
        if (tick.gain > 0 && s.r2 >= click_r && wheel_r2_ < click_r) { tick.pan = 0.6f; cues.push_back(tick); }
        if (tick.gain > 0 && s.l2 >= click_l && wheel_l2_ < click_l) { tick.pan = -0.6f; cues.push_back(tick); }
    }
    wheel_r2_ = s.r2;
    wheel_l2_ = s.l2;
    if (!g.valid && !in_game_ && engine_) {        // standalone: engine state on the lightbar
        static const std::map<std::string, std::array<uint8_t, 3>> colors = {
            {"ready", {0, 40, 0}}, {"held", {40, 25, 0}}, {"action", {0, 0, 70}}, {"cycling", {0, 30, 80}},
            {"reloading", {40, 0, 40}}, {"draw", {60, 50, 0}}, {"firing", {255, 60, 0}}, {"tethered", {70, 35, 0}}};
        auto it = colors.find(frame.state);
        if (frame.flash) { out.r = 255; out.g = 120; out.b = 0; }
        else if (it != colors.end()) { out.r = it->second[0]; out.g = it->second[1]; out.b = it->second[2]; }
        out.has_lightbar = true;
    }
    if (s.t < audio_.ack_flash_until.load()) {          // recognition flash
        out.has_lightbar = true;
        out.r = 40; out.g = 160; out.b = 255;
    }
    if (haptics_on_)
        for (auto& c : cues) audio_.play(c);

    int rt = weapon_active ? frame.game_rt : -1;
    input().publish(s, rt, true);
    if (s.fresh) {
        input().track_touch(s);
        input().track_gyro(s, in_game_ ? (g.free_aim && !g.lock_on && !g.blocked && !paused) : s.l2 > 128);
    }
    if (paused) audio_.set_rumble(0, 0);                 // the game rumbles while you browse the wheel
    else audio_.set_rumble(input().rumble_low(), input().rumble_high());
    if (!audio_.ok() && haptics_on_) {
        out.has_rumble = true;
        audio_.rumble_tick(s.t, out.rumble_left, out.rumble_right);
    }
    uint32_t pressed = s.buttons & ~prev_buttons_;
    prev_buttons_ = s.buttons;
    if (pressed & MUTE) {
        audio_.set_mic_listening(!audio_.mic_listening());
        voice_.set_listening(audio_.mic_listening());
        LOGI("whistle + voice listening %s", audio_.mic_listening() ? "on" : "off");
    }
    {
        std::lock_guard<std::mutex> l(status_mu_);
        last_state_ = frame.state;
        last_rt_ = rt >= 0 ? rt : s.r2;
    }
    return true;
}

void Core::script_tick() {
    if (in_game_) world().tick();
    if (!pad_.connected()) input().publish(InputState{}, -1, false);   // let other pads through
    // the controller came back (cable, Bluetooth, sleep): Windows recreated its audio devices
    bool conn = pad_.connected();
    if (conn && !pad_was_connected_ && pad_seen_ && !restarting_.exchange(true)) {
        LOGI("controller reconnected - reopening its audio (haptics, mic, voice)");
        std::thread([this] {
            Sleep(1500);                      // give Windows a moment to publish the new endpoints
            audio_.restart();
            voice_.restart();
            restarting_ = false;
        }).detach();
    }
    if (conn) pad_seen_ = true;
    pad_was_connected_ = conn;
    int key = config().integer("General", "ReloadKey", 120);
    bool down = (GetAsyncKeyState(key) & 0x8000) != 0;
    if (down && !reload_key_down_) request_reload();
    reload_key_down_ = down;
}

std::string Core::status() {
    std::lock_guard<std::mutex> l(status_mu_);
    char buf[256];
    snprintf(buf, sizeof buf, "pad %s %.0f Hz | audio %s %.1f ms | weapon %s | state %s | RT %d",
             pad_.connected() ? pad_.name().c_str() : "-", pad_.report_rate(), audio_.ok() ? "ok" : "off",
             audio_.latency_ms(), engine_name_.c_str(), last_state_.c_str(), last_rt_);
    return buf;
}

}  // namespace dsr2
