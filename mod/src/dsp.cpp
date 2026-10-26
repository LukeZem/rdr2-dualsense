#include "dsp.h"

#include <map>

namespace dsr2::dsp {

Biquad Biquad::lowpass(float hz, float q, float sr) {
    float w = 2 * kPi * hz / sr, c = std::cos(w), s = std::sin(w), alpha = s / (2 * q);
    float a0 = 1 + alpha;
    Biquad b;
    b.b0 = (1 - c) / 2 / a0; b.b1 = (1 - c) / a0; b.b2 = (1 - c) / 2 / a0;
    b.a1 = -2 * c / a0; b.a2 = (1 - alpha) / a0;
    return b;
}

Biquad Biquad::highpass(float hz, float q, float sr) {
    float w = 2 * kPi * hz / sr, c = std::cos(w), s = std::sin(w), alpha = s / (2 * q);
    float a0 = 1 + alpha;
    Biquad b;
    b.b0 = (1 + c) / 2 / a0; b.b1 = -(1 + c) / a0; b.b2 = (1 + c) / 2 / a0;
    b.a1 = -2 * c / a0; b.a2 = (1 - alpha) / a0;
    return b;
}

const Preset& preset(const std::string& name) {
    static const std::map<std::string, Preset> table = {
        {"handgun", {35, 240, 0.75f, 0.85f, 170, 0.45f, 62, 25, 70, 420, 2.2f}},
        {"long", {30, 220, 0.85f, 0.7f, 150, 0.6f, 50, 35, 110, 550, 2.0f}},
        {"heavy", {25, 200, 1.0f, 0.6f, 140, 0.75f, 42, 45, 150, 650, 2.4f}},
        {"small", {60, 300, 0.5f, 0.9f, 200, 0.2f, 80, 10, 40, 220, 1.6f}},
        {"mech", {60, 320, 0.35f, 1.0f, 210, 0.1f, 90, 30, 60, 400, 1.5f}},
        {"explosion", {20, 180, 1.0f, 0.45f, 120, 0.9f, 36, 120, 450, 1600, 2.6f}},
    };
    auto it = table.find(name);
    return it != table.end() ? it->second : table.at("mech");
}

std::vector<float> resample(const float* x, size_t n, int sr) {
    if (sr == kSR || n == 0) return std::vector<float>(x, x + n);
    size_t m = size_t(double(n) * kSR / sr);
    std::vector<float> out(m);
    double step = double(sr) / kSR;
    for (size_t i = 0; i < m; ++i) {
        double p = i * step;
        size_t a = size_t(p);
        float f = float(p - a);
        float va = x[std::min(a, n - 1)], vb = x[std::min(a + 1, n - 1)];
        out[i] = va + (vb - va) * f;
    }
    return out;
}

// Block-peak envelope (1 ms), instant or one-pole attack, exponential release, smoothed, per sample.
static std::vector<float> follow(const std::vector<float>& x, float release_ms, float attack_ms = 0) {
    const int hop = kSR / 1000;
    size_t n = x.size() / hop + 1;
    std::vector<float> blocks(n, 0.0f), env(n);
    for (size_t i = 0; i < x.size(); ++i) blocks[i / hop] = std::max(blocks[i / hop], std::fabs(x[i]));
    float rel = std::exp(-1.0f / std::max(release_ms, 0.1f));
    float att = attack_ms > 0 ? std::exp(-1.0f / attack_ms) : 0.0f;
    float e = 0;
    for (size_t i = 0; i < n; ++i) {
        float v = blocks[i];
        e = v > e ? att * e + (1 - att) * v : std::max(v, e * rel);
        env[i] = e;
    }
    std::vector<float> sm(n);
    for (size_t i = 0; i < n; ++i) {
        float a = env[i > 0 ? i - 1 : 0], b = env[i], c = env[std::min(i + 1, n - 1)];
        sm[i] = (a + b + c) / 3;
    }
    std::vector<float> out(x.size());
    for (size_t i = 0; i < x.size(); ++i) {
        float p = float(i) / hop;
        size_t k = size_t(p);
        float f = p - k;
        out[i] = sm[std::min(k, n - 1)] * (1 - f) + sm[std::min(k + 1, n - 1)] * f;
    }
    return out;
}

static float peak(const std::vector<float>& v) {
    float m = 0;
    for (float s : v) m = std::max(m, std::fabs(s));
    return m;
}

std::vector<float> to_haptic(const std::vector<float>& mono, int sr, const Preset& p, float pan, float amp) {
    std::vector<float> x = resample(mono.data(), mono.size(), sr);
    float pk = peak(x);
    if (pk < 1e-5f) return {0, 0};
    for (auto& s : x) s /= pk;
    size_t start = 0;
    while (start < x.size() && std::fabs(x[start]) <= 0.03f) ++start;
    start = start > size_t(kSR / 500) ? start - kSR / 500 : 0;
    size_t len = std::min(x.size() - start, size_t(kSR * p.max_ms / 1000));
    x = std::vector<float>(x.begin() + start, x.begin() + start + len);

    Band band(p.lo, p.hi);
    std::vector<float> body(x.size());
    for (size_t i = 0; i < x.size(); ++i) body[i] = band.run(x[i]);
    float bp = std::max(1e-6f, peak(body));
    std::vector<float> fast = follow(x, 25), slow = follow(x, 90, 8);
    std::vector<float> trans(x.size());
    for (size_t i = 0; i < x.size(); ++i) trans[i] = std::max(0.0f, fast[i] - slow[i]);
    float tp = std::max(1e-6f, peak(trans)), fp = std::max(1e-6f, peak(fast));

    float hold = p.hold_ms / 1000, tail = p.tail_ms / 1000;
    std::vector<float> h(x.size());
    size_t last = 0;
    for (size_t i = 0; i < x.size(); ++i) {
        float t = float(i) / kSR;
        float shape = t < hold ? 1.0f : std::exp(-(t - hold) / tail);
        if (shape > 0.01f) last = i;
        float crack = std::sin(2 * kPi * p.crack_hz * t) * trans[i] / tp;
        float rumble = std::sin(2 * kPi * p.rumble_hz * t) * fast[i] / fp;
        h[i] = (p.body * body[i] / bp + p.crack * crack + p.rumble * rumble) * shape;
    }
    h.resize(last + 1);
    float hp = std::max(1e-6f, peak(h));
    float td = std::tanh(p.drive);
    Band clean(15, 300);
    for (auto& s : h) s = clean.run(std::tanh(p.drive * s / hp) / td);
    hp = std::max(1e-6f, peak(h));
    size_t fade = std::min(h.size(), size_t(kSR / 200));
    for (size_t i = 0; i < h.size(); ++i) {
        h[i] = h[i] / hp * amp;
        if (i >= h.size() - fade) h[i] *= float(h.size() - i) / fade;
    }
    float gl, gr;
    pan_gains(pan, gl, gr);
    std::vector<float> out(h.size() * 2);
    for (size_t i = 0; i < h.size(); ++i) {
        out[2 * i] = h[i] * gl;
        out[2 * i + 1] = h[i] * gr;
    }
    return out;
}

std::vector<int> kick_steps(const std::vector<float>& mono, int sr, float step_ms, int max_steps) {
    std::vector<float> x = resample(mono.data(), mono.size(), sr);
    float pk = peak(x);
    if (pk < 1e-5f) return {};
    size_t s = 0;
    while (s < x.size() && std::fabs(x[s]) <= 0.03f * pk) ++s;
    x.erase(x.begin(), x.begin() + std::min(s, x.size()));
    std::vector<float> env = follow(x, 30);
    size_t ip = size_t(std::max_element(env.begin(), env.end()) - env.begin());
    env.erase(env.begin(), env.begin() + ip);
    size_t hop = std::max<size_t>(1, size_t(kSR * step_ms / 1000));
    size_t n = std::min<size_t>(max_steps, env.size() / hop);
    std::vector<float> steps(n, 0);
    for (size_t i = 0; i < n * hop; ++i) steps[i / hop] = std::max(steps[i / hop], env[i]);
    float m = 1e-6f;
    for (float v : steps) m = std::max(m, v);
    std::vector<int> out;
    float run = 1e9f;
    for (float v : steps) {
        run = std::min(run, v / m);
        float e = run * run * run;          // expand: game shots are mastered loud
        if (e < 0.12f) break;
        out.push_back(clampv(int(std::lround(8 * e)), 1, 8));
    }
    return out;
}

StreamConverter::StreamConverter() = default;

void StreamConverter::process(float l, float r, float& hl, float& hr) {
    float in[2] = {l, r}, out[2];
    float level = std::max(std::fabs(l), std::fabs(r));
    float norm = std::max(0.02f, agc_.run(level));         // slow AGC: consistent feel at any volume
    for (int c = 0; c < 2; ++c) {
        Chan& ch = ch_[c];
        float x = in[c] / norm;
        float body = ch.body.run(x);
        float f = ch.fast.run(x), s = ch.slow.run(x), bed = ch.bed.run(x);
        // only what rises above the ambient bed (music, wind, crowd) becomes haptics
        float event = clampv((f - 1.6f * bed) / std::max(f, 1e-4f), 0.0f, 1.0f);
        float trans = std::max(0.0f, f - s);
        float y = body * event * 0.9f + std::sin(phase_c_) * trans * 0.8f + std::sin(phase_r_) * std::max(0.0f, f - 1.6f * bed) * 0.35f;
        y = std::tanh(1.8f * y);
        out[c] = ch.out2.run(ch.out1.run(ch.hp.run(y)));
    }
    phase_c_ += 2 * kPi * 165.0f / kSR;
    phase_r_ += 2 * kPi * 48.0f / kSR;
    if (phase_c_ > 2 * kPi) phase_c_ -= 2 * kPi;
    if (phase_r_ > 2 * kPi) phase_r_ -= 2 * kPi;
    hl = out[0] * gain;
    hr = out[1] * gain;
}

void fft(std::vector<std::complex<float>>& a) {
    size_t n = a.size();
    for (size_t i = 1, j = 0; i < n; ++i) {
        size_t bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) std::swap(a[i], a[j]);
    }
    for (size_t len = 2; len <= n; len <<= 1) {
        float ang = -2 * kPi / float(len);
        std::complex<float> wl(std::cos(ang), std::sin(ang));
        for (size_t i = 0; i < n; i += len) {
            std::complex<float> w(1);
            for (size_t k = 0; k < len / 2; ++k) {
                auto u = a[i + k], v = a[i + k + len / 2] * w;
                a[i + k] = u + v;
                a[i + k + len / 2] = u - v;
                w *= wl;
            }
        }
    }
}

}  // namespace dsr2::dsp
