// Signal processing: filters, envelopes, game audio -> haptics (offline and streaming), small FFT.
// Port of tools/trigger_lab/gameaudio/convert.py, with IIR filters instead of FFT masks.
#pragma once

#include "common.h"

#include <complex>

namespace dsr2::dsp {

constexpr int kSR = 48000;

struct Biquad {
    float b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0, z1 = 0, z2 = 0;
    static Biquad lowpass(float hz, float q = 0.7071f, float sr = kSR);
    static Biquad highpass(float hz, float q = 0.7071f, float sr = kSR);
    float run(float x) {
        float y = b0 * x + z1;
        z1 = b1 * x - a1 * y + z2;
        z2 = b2 * x - a2 * y;
        return y;
    }
};

// 4th-order band: two high-passes at lo, two low-passes at hi.
struct Band {
    Biquad h1, h2, l1, l2;
    Band() = default;
    Band(float lo, float hi, float sr = kSR)
        : h1(Biquad::highpass(lo, 0.7071f, sr)), h2(Biquad::highpass(lo, 0.7071f, sr)),
          l1(Biquad::lowpass(hi, 0.7071f, sr)), l2(Biquad::lowpass(hi, 0.7071f, sr)) {}
    float run(float x) { return l2.run(l1.run(h2.run(h1.run(x)))); }
};

struct Follower {   // one-pole envelope follower
    float att = 0, rel = 0, e = 0;
    Follower() = default;
    Follower(float attack_ms, float release_ms, float sr = kSR) {
        att = attack_ms > 0 ? std::exp(-1.0f / (attack_ms * 0.001f * sr)) : 0.0f;
        rel = std::exp(-1.0f / (release_ms * 0.001f * sr));
    }
    float run(float x) {
        x = std::fabs(x);
        e = x > e ? att * e + (1 - att) * x : rel * e + (1 - rel) * x;
        return e;
    }
};

struct Preset {
    float lo, hi, body, crack, crack_hz, rumble, rumble_hz, hold_ms, tail_ms, max_ms, drive;
};
const Preset& preset(const std::string& name);   // handgun long heavy small mech explosion

// Linear resample of mono audio to 48 kHz.
std::vector<float> resample(const float* x, size_t n, int sr);

// Stereo interleaved (L,R,L,R...) 48 kHz haptic buffer from a recording.
std::vector<float> to_haptic(const std::vector<float>& mono, int sr, const Preset& p, float pan, float amp);

// Trigger recoil envelope (1-8 per step) following a recording's loudness (expanded, decay-only).
std::vector<int> kick_steps(const std::vector<float>& mono, int sr, float step_ms, int max_steps = 8);

inline void pan_gains(float pan, float& gl, float& gr) {
    gl = std::min(1.0f, 1.0f - pan);
    gr = std::min(1.0f, 1.0f + pan);
}

// Real-time game audio -> haptics. Reacts to events above the ambient bed (music/ambience
// are mostly ignored), keeps the left/right balance of the game mix, i.e. direction.
class StreamConverter {
public:
    StreamConverter();
    // in: stereo frame at 48 kHz; out: haptic L/R
    void process(float l, float r, float& hl, float& hr);
    float gain = 0.5f;
private:
    struct Chan {
        Band body{28, 190};
        Follower fast{1, 25}, slow{8, 90}, bed{300, 1500};
        Biquad out1 = Biquad::lowpass(300), out2 = Biquad::lowpass(300), hp = Biquad::highpass(18);
    } ch_[2];
    float phase_c_ = 0, phase_r_ = 0;
    Follower agc_{5, 2500};
};

// In-place radix-2 FFT (n must be a power of two).
void fft(std::vector<std::complex<float>>& a);

}  // namespace dsr2::dsp
