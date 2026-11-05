// Audio: DualSense haptics + speaker output (WASAPI), game-audio layer (loopback of the speakers),
// whistle detection on the controller's microphone, and a rumble fallback for Bluetooth.
#pragma once

#include "common.h"
#include "haptics.h"

#include <deque>
#include <map>
#include <memory>
#include <thread>

namespace dsr2 {

// the default output (where the game plays): its name and whether it is Bluetooth; any thread
bool default_output(std::string& name, bool& bluetooth);
// every output with what Windows reports about it (test tool)
std::string describe_outputs();

class AudioEngine {
public:
    bool start(HapticLibrary* lib);
    void stop();
    // reopen every device stream (the controller was unplugged / reconnected)
    void restart();
    float mic_level() const { return mic_level_.load(); }
    bool ok() const { return ok_.load(); }
    float latency_ms() const { return latency_ms_.load(); }

    void play(const Cue& c);                           // haptic (+ speaker if c.speaker)
    void set_strength(float g) { strength_ = g; }
    void set_speaker_volume(float v) { speaker_vol_ = v; }
    void set_duck(float d) { duck_level_ = d; }
    // the game's own rumble (XInputSetState), 0..1 per motor
    void set_rumble(float low, float high) { rumble_low_ = low; rumble_high_ = high; }
    void set_rumble_gain(float g) { rumble_gain_ = g; }
    // game-audio layer
    void start_game_audio(float gain, const std::string& device_hint);
    void set_game_audio_gain(float g) { game_audio_gain_ = g; }
    // whistle detector on the controller mic
    void start_mic(float sensitivity, std::function<void()> on_whistle);
    void set_mic_listening(bool on) { mic_listening_ = on; }
    bool mic_listening() const { return mic_listening_.load(); }
    bool scripted_active() const { return scripted_active_.load(); }

    // Bluetooth fallback: cue envelopes on the two rumble motors. Call from the controller thread.
    void rumble_tick(double now, uint8_t& left, uint8_t& right);

    // Long haptic tracks that follow the game's own clock (cutscene audio, spoken lines): mono 48 kHz, played so
    // that sample 0 is FELT at wall time t0 (now_s() clock; the device latency is taken care of here). Moving t0
    // resyncs; stop fades out over ~60 ms. Gains are per side (direction).
    void track_play(uint64_t key, std::shared_ptr<const std::vector<float>> mono, double t0, float gl, float gr);
    void track_move(uint64_t key, double t0, float gl, float gr);
    void track_stop(uint64_t key);
    bool track_playing(uint64_t key);

private:
    void render_thread();
    void loopback_thread(std::string hint);
    void mic_thread(float sens);

    struct Voice {
        Stereo buf;
        size_t pos = 0;
        bool speaker = false;
        bool scripted = true;
    };
    struct EnvVoice {
        std::vector<std::pair<float, float>> env;   // per 4 ms
        double t0;
    };

    struct Track {
        std::shared_ptr<const std::vector<float>> mono;
        double t0 = 0;
        float gl = 1, gr = 1;           // target gains
        float cl = 0, cr = 0;           // current (smoothed: moves and fades never click)
        bool stopping = false;
    };
    std::map<uint64_t, Track> tracks_;   // guarded by mu_

    HapticLibrary* lib_ = nullptr;
    std::thread render_, loop_, mic_;
    std::atomic<bool> running_{false}, ok_{false}, mic_listening_{true}, scripted_active_{false};
    std::atomic<float> latency_ms_{0}, strength_{1}, speaker_vol_{0.35f}, duck_level_{0.3f};
    std::atomic<float> rumble_low_{0}, rumble_high_{0}, rumble_gain_{0.6f}, game_audio_gain_{0.45f};
    std::mutex mu_;
    std::vector<Voice> incoming_;
    std::deque<EnvVoice> env_voices_;
    // game-audio ring (stereo haptic samples at 48 kHz), single producer / single consumer
    std::vector<float> ring_;
    std::atomic<size_t> ring_w_{0}, ring_r_{0};
    std::function<void()> on_whistle_;
    std::atomic<float> mic_level_{0};
    float cooldown_s_ = 1.2f;
  public:
    // a recognition happened: the controller thread flashes the lightbar until this time
    std::atomic<double> ack_flash_until{0};
  private:
    float mic_sens_ = 1.0f, ga_gain_ = 0;
    std::string ga_hint_;
    bool mic_started_ = false, ga_started_ = false;
    std::mutex restart_mu_;
};

}  // namespace dsr2
