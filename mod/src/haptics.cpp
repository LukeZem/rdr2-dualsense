#include "haptics.h"

#include "dsp.h"
#include "log.h"

#include <fstream>

namespace dsr2 {

using nlohmann::json;
constexpr int kMaxVariants = 8;

static float jf(const json& j, const char* k, float d) {
    auto it = j.find(k);
    return it != j.end() && it->is_number() ? it->get<float>() : d;
}

static void place(Stereo& dst, const Stereo& src, float delay_ms, float gain = 1.0f) {
    size_t off = size_t(dsp::kSR * delay_ms / 1000) * 2;
    if (dst.size() < off + src.size()) dst.resize(off + src.size(), 0.0f);
    for (size_t i = 0; i < src.size(); ++i) dst[off + i] += src[i] * gain;
}

void HapticLibrary::load(const fs::path& recipes_json, GameAudio* game) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    game_ = game;
    buffers_.clear();
    kicks_.clear();
    source_.clear();
    std::ifstream in(recipes_json);
    try {
        recipes_ = json::parse(in);
    } catch (const std::exception& e) {
        LOGE("haptics.json: %s", e.what());
        recipes_ = json::object();
    }
    int n = 0;
    for (auto& [name, r] : recipes_.items()) {
        if (name.empty() || name[0] == '_') continue;
        try {
            render_recipe(name, 0);
            ++n;
        } catch (const std::exception& e) {
            LOGW("recipe %s: %s", name.c_str(), e.what());
        }
    }
    LOGI("haptics: %d recipes", n);
}

Stereo HapticLibrary::synth_layer(const json& L, float fm, int variant) {
    const std::string type = L.value("type", "");
    float amp = jf(L, "amp", 1.0f);
    std::vector<float> mono;
    if (type == "click") {
        float hz = jf(L, "hz", 250) * fm, cycles = jf(L, "cycles", 1);
        int n = std::max(2, int(dsp::kSR * cycles / hz));
        mono.resize(n);
        for (int i = 0; i < n; ++i) {
            float w = 0.5f - 0.5f * std::cos(2 * kPi * i / (n - 1));
            mono[i] = std::sin(2 * kPi * hz * i / dsp::kSR) * w * amp;
        }
    } else if (type == "tone") {
        float hz0 = jf(L, "hz", 60) * fm, hz1 = jf(L, "to_hz", hz0 / fm) * fm;
        float att = jf(L, "attack_ms", 1) / 1000, dec = std::max(1e-4f, jf(L, "decay_ms", 50) / 1000);
        int n = int(dsp::kSR * (att + 5 * dec));
        mono.resize(n);
        float phase = 0;
        for (int i = 0; i < n; ++i) {
            float t = float(i) / dsp::kSR;
            float f = hz1 + (hz0 - hz1) * std::exp(-t / dec);
            phase += 2 * kPi * f / dsp::kSR;
            float env = t < att ? t / std::max(att, 1e-6f) : std::exp(-(t - att) / dec);
            mono[i] = std::sin(phase) * env * amp;
        }
    } else if (type == "noise") {
        float lo = jf(L, "lo", 60) * fm, hi = std::min(20000.0f, jf(L, "hi", 300) * fm);
        float att = jf(L, "attack_ms", 0.5f) / 1000, dec = std::max(1e-4f, jf(L, "decay_ms", 30) / 1000);
        int n = int(dsp::kSR * (att + 5 * dec));
        Rng r((uint64_t(jf(L, "seed", 7)) + uint64_t(variant) * 101) * 7919 + 1);   // each variant its own grain
        dsp::Band band(lo, hi);
        std::vector<float> noise(n + 2400);
        for (auto& s : noise) s = band.run(r.gauss());
        noise.erase(noise.begin(), noise.begin() + 2400);         // let the filter settle
        float pk = 1e-9f;
        for (float s : noise) pk = std::max(pk, std::fabs(s));
        mono.resize(n);
        for (int i = 0; i < n; ++i) {
            float t = float(i) / dsp::kSR;
            float env = t < att ? t / std::max(att, 1e-6f) : std::exp(-(t - att) / dec);
            mono[i] = noise[i] / pk * env * amp;
        }
    } else {
        throw std::runtime_error("unknown layer type " + type);
    }
    float gl, gr;
    dsp::pan_gains(jf(L, "pan", 0), gl, gr);
    Stereo st(mono.size() * 2);
    for (size_t i = 0; i < mono.size(); ++i) {
        st[2 * i] = mono[i] * gl;
        st[2 * i + 1] = mono[i] * gr;
    }
    Stereo out;
    place(out, st, jf(L, "delay_ms", 0));
    return out;
}

const std::vector<Stereo>& HapticLibrary::render_recipe(const std::string& name, int depth, bool audible) {
    const std::string key = audible ? name + "#spk" : name;
    const float fm = audible ? 6.0f : 1.0f;
    auto it = buffers_.find(key);
    if (it != buffers_.end()) return it->second;
    if (depth > 4) throw std::runtime_error("references nest too deep");
    if (!recipes_.contains(name)) throw std::runtime_error("unknown recipe " + name);
    const json& r = recipes_[name];
    // "variants": N - N takes of a synthesized recipe (each its own noise grain, pitch a few % apart), one picked per
    // play: no two steps on the same ground feel identical
    static const float kJitter[8] = {1.0f, 0.96f, 1.04f, 0.98f, 1.03f, 0.95f, 1.05f, 1.01f};
    const int nvar = audible ? 1 : std::clamp(r.value("variants", 1), 1, 8);
    std::vector<Stereo> statics(static_cast<size_t>(nvar));
    std::vector<std::vector<Stereo>> variant_layers;
    std::string src = "synth";
    for (const auto& L : r.value("layers", json::array())) {
        std::string type = L.value("type", "");
        if (type == "game" && audible) {
            continue;
        } else if (type == "game") {
            std::vector<const GameSound*> sounds;
            if (game_) sounds = game_->variants(L.value("bank", ""), L.value("role", "shot"));
            if (sounds.size() > size_t(kMaxVariants)) sounds.resize(kMaxVariants);
            if (!sounds.empty()) {
                src = "game " + L.value("bank", "") + " x" + std::to_string(sounds.size());
                std::vector<Stereo> vs;
                const auto& p = dsp::preset(L.value("convert", "mech"));
                for (auto* s : sounds) {
                    Stereo b;
                    place(b, dsp::to_haptic(s->mono(), s->rate, p, jf(L, "pan", 0), jf(L, "amp", 1)), jf(L, "delay_ms", 0));
                    vs.push_back(std::move(b));
                }
                variant_layers.push_back(std::move(vs));
            } else if (r.contains("fallback")) {
                for (const auto& F : r["fallback"])
                    for (int v = 0; v < nvar; ++v) place(statics[v], synth_layer(F, fm * kJitter[v], v), 0);
            }
        } else if (type == "ref") {
            const auto& ref = render_recipe(L.value("name", ""), depth + 1, audible);
            for (int v = 0; v < nvar && !ref.empty(); ++v)
                place(statics[v], ref[size_t(v) % ref.size()], jf(L, "delay_ms", 0), jf(L, "amp", 1));
        } else {
            for (int v = 0; v < nvar; ++v) place(statics[v], synth_layer(L, fm * kJitter[v], v), 0);
        }
    }
    float gain = jf(r, "gain", 1);
    size_t count = size_t(nvar);
    for (auto& v : variant_layers) count = std::max(count, v.size());
    std::vector<Stereo> out;
    for (size_t i = 0; i < count; ++i) {
        Stereo b = statics[i % statics.size()];
        for (auto& v : variant_layers) place(b, v[i % v.size()], 0);
        for (auto& s : b) s = clampv(s * gain, -1.0f, 1.0f);
        if (b.empty()) b = {0, 0};
        out.push_back(std::move(b));
    }
    source_[key] = src;
    return buffers_[key] = std::move(out);
}

bool HapticLibrary::has(const std::string& name) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    if (buffers_.count(name)) return true;
    if (!recipes_.contains(name)) return false;
    try { render_recipe(name, 0); } catch (...) { return false; }
    return true;
}

int HapticLibrary::variant_count(const std::string& name) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    auto it = buffers_.find(name);
    return it == buffers_.end() ? 0 : int(it->second.size());
}

std::string HapticLibrary::source(const std::string& name) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    auto it = source_.find(name);
    return it == source_.end() ? "" : it->second;
}

std::vector<std::vector<int>> HapticLibrary::kicks(const std::string& name) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    auto it = kicks_.find(name);
    return it == kicks_.end() ? std::vector<std::vector<int>>{} : it->second;
}

static void respeed(const Stereo& in, float speed, Stereo& out) {
    size_t frames = in.size() / 2;
    size_t n = size_t(frames / speed);
    out.resize(n * 2);
    for (size_t i = 0; i < n; ++i) {
        float p = i * speed;
        size_t a = size_t(p);
        float f = p - a;
        size_t b = std::min(a + 1, frames - 1);
        a = std::min(a, frames - 1);
        out[2 * i] = in[2 * a] * (1 - f) + in[2 * b] * f;
        out[2 * i + 1] = in[2 * a + 1] * (1 - f) + in[2 * b + 1] * f;
    }
}

bool HapticLibrary::render(const Cue& cue, Stereo& out, int* chosen) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    if (!has(cue.name)) return false;
    const auto& vs = buffers_[cue.name];
    int i = cue.variant >= 0 && cue.variant < int(vs.size()) ? cue.variant : rng_.below(int(vs.size()));
    if (chosen) *chosen = i;
    const Stereo& src = vs[size_t(i)];
    if (std::fabs(cue.speed - 1.0f) > 1e-3f) respeed(src, cue.speed, out);
    else out = src;
    if (cue.has_pan) {
        // keep the stronger channel, place it at the requested side
        double el = 0, er = 0;
        for (size_t k = 0; k < out.size(); k += 2) { el += std::fabs(out[k]); er += std::fabs(out[k + 1]); }
        int c = er > el ? 1 : 0;
        float gl, gr;
        dsp::pan_gains(cue.pan, gl, gr);
        for (size_t k = 0; k < out.size(); k += 2) {
            float m = out[k + c];
            out[k] = m * gl;
            out[k + 1] = m * gr;
        }
    }
    for (auto& s : out) s *= cue.gain;
    return true;
}

std::string HapticLibrary::ensure_weapon(const json& prof) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    std::string bank = prof.contains("bank") && prof["bank"].is_string() ? prof["bank"].get<std::string>() : "";
    if (bank.empty() || !game_ || !game_->has_bank(bank)) return "";
    std::string name = prof.value("id", std::string("weapon")) + ":shot";
    if (buffers_.count(name)) return name;
    auto sounds = game_->variants(bank, "shot");
    if (sounds.empty()) return "";
    if (sounds.size() > size_t(kMaxVariants)) sounds.resize(kMaxVariants);
    json audio = prof.value("audio", json::object());
    const auto& p = dsp::preset(audio.value("convert", "handgun"));
    float pan = audio.value("pan", 0.0f), mix = audio.value("synth_mix", 0.4f);
    std::string synth = prof.value("recoil", json::object()).value("haptic", "");
    float step_ms = prof.value("recoil", json::object()).value("trigger", json::object()).value("step_ms", 16.0f);
    const Stereo* thump = nullptr;
    if (!synth.empty() && recipes_.contains(synth)) {
        try { thump = &render_recipe(synth, 0)[0]; } catch (...) {}
    }
    std::vector<Stereo> bufs;
    std::vector<std::vector<int>> kicks;
    for (auto* s : sounds) {
        std::vector<float> mono = s->mono();
        Stereo b = dsp::to_haptic(mono, s->rate, p, pan, 1.0f - 0.3f * mix);
        if (thump) place(b, *thump, 0, mix);
        for (auto& v : b) v = clampv(v, -1.0f, 1.0f);
        bufs.push_back(std::move(b));
        kicks.push_back(dsp::kick_steps(mono, s->rate, step_ms));
    }
    source_[name] = "game " + bank + " x" + std::to_string(bufs.size()) + (thump ? " + " + synth : "");
    kicks_[name] = std::move(kicks);
    buffers_[name] = std::move(bufs);
    LOGI("weapon shot %s: %s", name.c_str(), source_[name].c_str());
    return name;
}

// cue name -> sound role a user can label on the lab's Sounds page
static std::string speaker_role(const std::string& cue) {
    static const std::map<std::string, std::string> m = {
        {"hammer_cock", "cock"}, {"hammer_cock_auto", "cock"}, {"lever_open", "lever_open"},
        {"lever_open_big", "lever_open"}, {"lever_close", "lever_close"}, {"lever_close_big", "lever_close"},
        {"bolt_open", "bolt_open"}, {"bolt_close", "bolt_close"}, {"pump_back", "pump_back"},
        {"pump_forward", "pump_forward"}, {"slide_small_back", "pump_back"}, {"slide_small_forward", "pump_forward"},
        {"reload_round", "reload"}, {"reload_shell", "reload"}, {"stripper_clip", "reload"}, {"mag_in", "reload"},
        {"dry_fire", "dry_fire"}, {"breech_open", "reload"}, {"breech_close", "reload"}, {"cylinder_gate", "reload"},
        // real game recordings found by name (tools/awc/autolabel.py)
        {"gun_draw", "draw"}, {"gun_holster", "holster"}, {"lasso_throw", "lasso_throw"},
        {"rope_jerk", "rope_jerk"}, {"rope_catch", "rope_jerk"},
    };
    auto it = m.find(cue);
    return it == m.end() ? "" : it->second;
}

bool HapticLibrary::speaker_sound(const Cue& cue, Stereo& out) {
    std::lock_guard<std::recursive_mutex> l(mu_);
    std::string role = speaker_role(cue.name);
    if (role.empty()) return false;
    if (game_) {
        for (const std::string& bank : {cue.bank, std::string("WEAPONS")}) {
            if (bank.empty()) continue;
            auto vs = game_->variants(bank, role);
            if (!vs.empty()) {
                const GameSound* s = vs[size_t(rng_.below(int(vs.size())))];
                LOGD("speaker: %s = recording %s/%s (%zu to pick from)", cue.name.c_str(), bank.c_str(), s->key.c_str(), vs.size());
                std::vector<float> L = dsp::resample(s->left.data(), s->left.size(), s->rate);
                std::vector<float> R = s->right.empty() ? L : dsp::resample(s->right.data(), s->right.size(), s->rate);
                out.resize(L.size() * 2);
                for (size_t i = 0; i < L.size(); ++i) { out[2 * i] = L[i]; out[2 * i + 1] = R[std::min(i, R.size() - 1)]; }
                return true;
            }
        }
    }
    // no recording: the same mechanism re-synthesized at an audible pitch
    LOGD("speaker: %s has no recording (role %s) - synthesized", cue.name.c_str(), role.c_str());
    if (!recipes_.contains(cue.name)) return false;
    try {
        const auto& v = render_recipe(cue.name, 0, true);
        if (v.empty()) return false;
        out = v[0];
    } catch (...) {
        return false;
    }
    return true;
}

}  // namespace dsr2
