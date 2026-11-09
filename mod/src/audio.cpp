#include "audio.h"

#include "dsp.h"
#include "config.h"
#include "log.h"

#include <initguid.h>
#include <audioclient.h>
#include <avrt.h>
#include <functiondiscoverykeys_devpkey.h>
#include <mmdeviceapi.h>

#include <complex>

namespace dsr2 {

namespace {

template <class T>
struct ComPtr {
    T* p = nullptr;
    ~ComPtr() { if (p) p->Release(); }
    T** operator&() { return &p; }
    T* operator->() const { return p; }
    explicit operator bool() const { return p != nullptr; }
};

std::wstring device_name(IMMDevice* dev) {
    ComPtr<IPropertyStore> props;
    std::wstring out;
    if (SUCCEEDED(dev->OpenPropertyStore(STGM_READ, &props))) {
        PROPVARIANT v;
        PropVariantInit(&v);
        if (SUCCEEDED(props->GetValue(PKEY_Device_FriendlyName, &v)) && v.vt == VT_LPWSTR) out = v.pwszVal;
        PropVariantClear(&v);
    }
    return out;
}

std::string narrow(const std::wstring& w) {
    std::string s;
    for (wchar_t c : w) s += c < 128 ? char(c) : '?';
    return s;
}

bool contains_ci(const std::wstring& hay, const std::wstring& needle) {
    std::wstring a = hay, b = needle;
    for (auto& c : a) c = towlower(c);
    for (auto& c : b) c = towlower(c);
    return a.find(b) != std::wstring::npos;
}

// the bus the endpoint's device hangs on: "BTHENUM" / "BTHLEDEVICE" = Bluetooth, "USB", "HDAUDIO" (HDMI / jack)...
std::wstring device_bus(IMMDevice* dev) {
    static const PROPERTYKEY kEnumerator = {{0xa45c254e, 0xdf1c, 0x4efd, {0x80, 0x20, 0x67, 0xd1, 0x46, 0xa8, 0x50, 0xe0}}, 24};
    ComPtr<IPropertyStore> props;
    std::wstring out;
    if (SUCCEEDED(dev->OpenPropertyStore(STGM_READ, &props))) {
        PROPVARIANT v;
        PropVariantInit(&v);
        if (SUCCEEDED(props->GetValue(kEnumerator, &v)) && v.vt == VT_LPWSTR) out = v.pwszVal;
        PropVariantClear(&v);
    }
    return out;
}

// endpoint whose name contains `match` (and not `exclude`); empty match = default endpoint
IMMDevice* find_endpoint(EDataFlow flow, const std::wstring& match, const std::wstring& exclude) {
    ComPtr<IMMDeviceEnumerator> en;
    if (FAILED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), (void**)&en)))
        return nullptr;
    if (match.empty()) {
        // the default output (multimedia, then console role), unless it is the excluded device
        for (ERole role : {eMultimedia, eConsole}) {
            IMMDevice* d = nullptr;
            if (FAILED(en->GetDefaultAudioEndpoint(flow, role, &d)) || !d) continue;
            if (exclude.empty() || !contains_ci(device_name(d), exclude)) return d;
            d->Release();
        }
    }
    ComPtr<IMMDeviceCollection> col;
    if (FAILED(en->EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE, &col))) return nullptr;
    UINT n = 0;
    col->GetCount(&n);
    for (UINT i = 0; i < n; ++i) {
        IMMDevice* d = nullptr;
        if (FAILED(col->Item(i, &d))) continue;
        std::wstring nm = device_name(d);
        // empty match: first active device that is not excluded (fallback when the default is the controller)
        if ((match.empty() || contains_ci(nm, match)) && (exclude.empty() || !contains_ci(nm, exclude))) return d;
        d->Release();
    }
    return nullptr;
}

bool is_float(const WAVEFORMATEX* f) {
    // KSDATAFORMAT_SUBTYPE_IEEE_FLOAT {00000003-0000-0010-8000-00AA00389B71}
    static const GUID kFloat = {0x00000003, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71}};
    if (f->wFormatTag == WAVE_FORMAT_IEEE_FLOAT) return true;
    if (f->wFormatTag == WAVE_FORMAT_EXTENSIBLE)
        return IsEqualGUID(reinterpret_cast<const WAVEFORMATEXTENSIBLE*>(f)->SubFormat, kFloat);
    return false;
}

float sample_at(const BYTE* data, const WAVEFORMATEX* f, size_t frame, int ch) {
    if (is_float(f)) return reinterpret_cast<const float*>(data)[frame * f->nChannels + ch];
    if (f->wBitsPerSample == 16) return reinterpret_cast<const int16_t*>(data)[frame * f->nChannels + ch] / 32768.0f;
    if (f->wBitsPerSample == 32) return float(reinterpret_cast<const int32_t*>(data)[frame * f->nChannels + ch] / 2147483648.0);
    return 0.0f;
}

}  // namespace

// Where the game's sound goes now (the default output) and whether it is Bluetooth (the sound then reaches the ears
// ~150-250 ms after the PC plays it; our haptics go over USB in ~10 ms). Any thread (COM initialised here).
bool default_output(std::string& name, bool& bluetooth) {
    HRESULT co = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    IMMDevice* d = find_endpoint(eRender, L"", L"DualSense");
    bool ok = d != nullptr;
    if (d) {
        name = narrow(device_name(d));
        std::wstring bus = device_bus(d);
        bluetooth = contains_ci(bus, L"BTH") || contains_ci(bus, L"BLUETOOTH");
        d->Release();
    }
    if (SUCCEEDED(co)) CoUninitialize();
    return ok;
}

// every output: name, bus, what Windows reports as its latency (test tool: dsr2_test --outputs)
std::string describe_outputs() {
    HRESULT co = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    std::string out;
    ComPtr<IMMDeviceEnumerator> en;
    if (SUCCEEDED(CoCreateInstance(__uuidof(MMDeviceEnumerator), nullptr, CLSCTX_ALL, __uuidof(IMMDeviceEnumerator), (void**)&en))) {
        std::wstring def;
        IMMDevice* dd = nullptr;
        if (SUCCEEDED(en->GetDefaultAudioEndpoint(eRender, eMultimedia, &dd)) && dd) { def = device_name(dd); dd->Release(); }
        ComPtr<IMMDeviceCollection> col;
        UINT n = 0;
        if (SUCCEEDED(en->EnumAudioEndpoints(eRender, DEVICE_STATE_ACTIVE, &col))) col->GetCount(&n);
        for (UINT i = 0; i < n; ++i) {
            IMMDevice* d = nullptr;
            if (FAILED(col->Item(i, &d))) continue;
            std::wstring nm = device_name(d);
            ComPtr<IAudioClient> cl;
            WAVEFORMATEX* fmt = nullptr;
            REFERENCE_TIME lat = 0, per_def = 0, per_min = 0;
            UINT32 frames = 0;
            if (SUCCEEDED(d->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&cl)) && SUCCEEDED(cl->GetMixFormat(&fmt)) &&
                SUCCEEDED(cl->Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 0, 0, fmt, nullptr))) {
                cl->GetStreamLatency(&lat);
                cl->GetDevicePeriod(&per_def, &per_min);
                cl->GetBufferSize(&frames);
            }
            char line[512];
            snprintf(line, sizeof line, "%s %-50s bus %-12s stream latency %5.1f ms, period %4.1f ms, buffer %5.1f ms\n",
                     nm == def ? "*" : " ", narrow(nm).c_str(), narrow(device_bus(d)).c_str(), lat / 1e4, per_def / 1e4,
                     fmt && fmt->nSamplesPerSec ? 1000.0 * frames / fmt->nSamplesPerSec : 0.0);
            out += line;
            if (fmt) CoTaskMemFree(fmt);
            d->Release();
        }
    }
    if (SUCCEEDED(co)) CoUninitialize();
    return out;
}

bool AudioEngine::start(HapticLibrary* lib) {
    lib_ = lib;
    ring_.assign(size_t(dsp::kSR) * 2, 0.0f);     // 0.5 s stereo
    running_ = true;
    render_ = std::thread([this] { render_thread(); });
    return true;
}

void AudioEngine::stop() {
    running_ = false;
    for (auto* t : {&render_, &loop_, &mic_})
        if (t->joinable()) t->join();
    ok_ = false;
}

void AudioEngine::restart() {
    std::lock_guard<std::mutex> l(restart_mu_);
    stop();
    running_ = true;
    render_ = std::thread([this] { render_thread(); });
    if (ga_started_) loop_ = std::thread([this] { loopback_thread(ga_hint_); });
    if (mic_started_) mic_ = std::thread([this] { mic_thread(mic_sens_); });
    LOGI("audio devices reopened");
}

void AudioEngine::play(const Cue& c) {
    Stereo buf;
    Cue cue = c;
    cue.gain *= strength_.load();
    if (!lib_ || !lib_->render(cue, buf)) return;
    std::lock_guard<std::mutex> l(mu_);
    if (ok_) incoming_.push_back({std::move(buf), 0, false, c.scripted});
    else {
        // Bluetooth: keep an envelope for the rumble motors
        EnvVoice v;
        v.t0 = now_s();
        const size_t hop = size_t(dsp::kSR * 0.004) * 2;
        for (size_t i = 0; i < buf.size(); i += hop) {
            float l = 0, r = 0;
            for (size_t k = i; k < std::min(buf.size(), i + hop); k += 2) {
                l = std::max(l, std::fabs(buf[k]));
                r = std::max(r, std::fabs(buf[k + 1]));
            }
            v.env.push_back({l, r});
        }
        env_voices_.push_back(std::move(v));
    }
    if (c.speaker && ok_) {
        Stereo spk;
        if (lib_->speaker_sound(c, spk)) incoming_.push_back({std::move(spk), 0, true, false});
    }
}

void AudioEngine::track_play(uint64_t key, std::shared_ptr<const std::vector<float>> mono, double t0, float gl, float gr) {
    std::lock_guard<std::mutex> l(mu_);
    Track& t = tracks_[key];
    t.mono = std::move(mono);
    t.t0 = t0;
    t.gl = gl;
    t.gr = gr;
    t.stopping = false;
}

void AudioEngine::track_move(uint64_t key, double t0, float gl, float gr) {
    std::lock_guard<std::mutex> l(mu_);
    auto it = tracks_.find(key);
    if (it == tracks_.end()) return;
    it->second.t0 = t0;
    it->second.gl = gl;
    it->second.gr = gr;
}

void AudioEngine::track_stop(uint64_t key) {
    std::lock_guard<std::mutex> l(mu_);
    auto it = tracks_.find(key);
    if (it != tracks_.end()) it->second.stopping = true;
}

bool AudioEngine::track_playing(uint64_t key) {
    std::lock_guard<std::mutex> l(mu_);
    auto it = tracks_.find(key);
    return it != tracks_.end() && !it->second.stopping;
}

int AudioEngine::track_count() {
    std::lock_guard<std::mutex> l(mu_);
    return int(tracks_.size());
}

void AudioEngine::rumble_tick(double now, uint8_t& left, uint8_t& right) {
    float l = 0, r = 0;
    std::lock_guard<std::mutex> lk(mu_);
    while (!env_voices_.empty() && (now - env_voices_.front().t0) / 0.004 >= env_voices_.front().env.size())
        env_voices_.pop_front();
    for (auto& v : env_voices_) {
        size_t i = size_t((now - v.t0) / 0.004);
        if (i < v.env.size()) {
            l = std::max(l, v.env[i].first);
            r = std::max(r, v.env[i].second);
        }
    }
    float g = rumble_gain_.load();
    l = std::max(l, rumble_low_.load() * g);
    r = std::max(r, rumble_high_.load() * g);
    left = uint8_t(std::min(255.0f, l * 255));
    right = uint8_t(std::min(255.0f, r * 200));
}

void AudioEngine::render_thread() {
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    IMMDevice* dev = find_endpoint(eRender, L"DualSense", L"");
    if (!dev) {
        LOGW("DualSense audio device not found - haptics fall back to rumble emulation (Bluetooth?)");
        CoUninitialize();
        return;
    }
    LOGI("haptics output: %s", narrow(device_name(dev)).c_str());
    ComPtr<IAudioClient> client;
    ComPtr<IAudioRenderClient> render;
    WAVEFORMATEX* fmt = nullptr;
    HANDLE ev = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    bool good = SUCCEEDED(dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&client)) &&
                SUCCEEDED(client->GetMixFormat(&fmt)) && fmt->nChannels >= 4 &&
                SUCCEEDED(client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_EVENTCALLBACK, 100000, 0, fmt, nullptr)) &&
                SUCCEEDED(client->SetEventHandle(ev)) &&
                SUCCEEDED(client->GetService(__uuidof(IAudioRenderClient), (void**)&render));
    dev->Release();
    if (!good) {
        LOGE("could not open the DualSense audio device (channels %d)", fmt ? fmt->nChannels : 0);
        if (fmt) CoTaskMemFree(fmt);
        CloseHandle(ev);
        CoUninitialize();
        return;
    }
    UINT32 frames = 0;
    client->GetBufferSize(&frames);
    REFERENCE_TIME lat = 0;
    client->GetStreamLatency(&lat);
    latency_ms_ = float(lat) / 10000.0f + 1000.0f * frames / fmt->nSamplesPerSec / 2;
    const int ch = fmt->nChannels;
    const bool flt = is_float(fmt);
    if (fmt->nSamplesPerSec != dsp::kSR)
        LOGW("haptics device runs at %lu Hz (expected 48000) - effects will play at the wrong speed", fmt->nSamplesPerSec);
    LOGI("haptics stream: %d ch, %lu Hz, %s, buffer %u frames, latency %.1f ms", ch, fmt->nSamplesPerSec,
         flt ? "float" : "pcm", frames, latency_ms_.load());
    DWORD task = 0;
    HANDLE mmcss = AvSetMmThreadCharacteristicsW(L"Pro Audio", &task);
    client->Start();
    ok_ = true;
    std::vector<Voice> voices;
    std::vector<float> mix;
    float duck = 1.0f, rl = 0, rh = 0, ph_l = 0, ph_h = 0;
    while (running_) {
        if (WaitForSingleObject(ev, 200) != WAIT_OBJECT_0) continue;
        UINT32 pad = 0;
        if (FAILED(client->GetCurrentPadding(&pad))) break;
        UINT32 n = frames - pad;
        if (!n) continue;
        {
            std::lock_guard<std::mutex> l(mu_);
            for (auto& v : incoming_) voices.push_back(std::move(v));
            incoming_.clear();
        }
        mix.assign(size_t(n) * 4, 0.0f);    // ch0/1 speaker, ch2/3 haptics
        bool scripted = false;
        for (auto& v : voices) scripted |= v.scripted && !v.speaker;
        scripted_active_ = scripted;
        float duck_target = scripted ? duck_level_.load() : 1.0f;
        float strength = strength_.load(), spk = speaker_vol_.load();
        float rg = rumble_gain_.load() * strength, ga = game_audio_gain_.load() * strength;
        float tl = rumble_low_.load(), th = rumble_high_.load();
        for (UINT32 i = 0; i < n; ++i) {
            duck += (duck_target - duck) * (duck_target < duck ? 0.01f : 0.0003f);
            // the game's rumble motors as voice-coil vibration (low ~45 Hz, high ~150 Hz)
            rl += (tl - rl) * 0.002f;
            rh += (th - rh) * 0.002f;
            ph_l += 2 * kPi * 45.0f / fmt->nSamplesPerSec;
            ph_h += 2 * kPi * 150.0f / fmt->nSamplesPerSec;
            if (ph_l > 2 * kPi) ph_l -= 2 * kPi;
            if (ph_h > 2 * kPi) ph_h -= 2 * kPi;
            float rum = (std::sin(ph_l) * rl * 0.8f + std::sin(ph_h) * rh * 0.5f) * rg * duck;
            float hl = rum, hr = rum;
            // game-audio layer
            size_t r = ring_r_.load(), w = ring_w_.load();
            if (r != w) {
                hl += ring_[r] * ga * duck;
                hr += ring_[r + 1] * ga * duck;
                ring_r_ = (r + 2) % ring_.size();
            }
            mix[size_t(i) * 4 + 2] = hl;
            mix[size_t(i) * 4 + 3] = hr;
        }
        // voices are 48 kHz; the device is normally 48 kHz too (ratio 1)
        for (auto& v : voices) {
            size_t frames_v = v.buf.size() / 2;
            for (UINT32 i = 0; i < n && v.pos < frames_v; ++i) {
                size_t k = v.pos;
                if (v.speaker) {
                    // mono: the built-in speaker only plays the right channel (headphones get both)
                    float m = 0.5f * (v.buf[2 * k] + v.buf[2 * k + 1]) * spk;
                    mix[size_t(i) * 4 + 0] += m;
                    mix[size_t(i) * 4 + 1] += m;
                } else {
                    mix[size_t(i) * 4 + 2] += v.buf[2 * k];
                    mix[size_t(i) * 4 + 3] += v.buf[2 * k + 1];
                }
                v.pos += 1;
            }
        }
        voices.erase(std::remove_if(voices.begin(), voices.end(), [](const Voice& v) { return v.pos >= v.buf.size() / 2; }),
                     voices.end());
        // tracks on the game's clock: the first sample written now is felt one device latency later
        {
            std::lock_guard<std::mutex> l(mu_);
            const double felt = now_s() + latency_ms_.load() / 1000.0;
            const float step = 1.0f / (0.06f * float(dsp::kSR));          // gains move / fade over ~60 ms
            const bool muted = tracks_muted_.load();                        // the game is paused
            for (auto it = tracks_.begin(); it != tracks_.end();) {
                Track& t = it->second;
                const std::vector<float>& m = *t.mono;
                const long long k0 = (long long)std::floor((felt - t.t0) * dsp::kSR);
                const bool silent = t.stopping || muted;
                float tl = silent ? 0.0f : t.gl * strength, tr = silent ? 0.0f : t.gr * strength;
                for (UINT32 i = 0; i < n; ++i) {
                    t.cl += clampv(tl - t.cl, -step, step);
                    t.cr += clampv(tr - t.cr, -step, step);
                    long long k = k0 + i;
                    if (k < 0 || k >= (long long)m.size()) continue;
                    mix[size_t(i) * 4 + 2] += m[size_t(k)] * t.cl;
                    mix[size_t(i) * 4 + 3] += m[size_t(k)] * t.cr;
                }
                bool done = (t.stopping && t.cl <= 0 && t.cr <= 0) || k0 > (long long)m.size();
                it = done ? tracks_.erase(it) : std::next(it);
            }
        }
        BYTE* out = nullptr;
        if (FAILED(render->GetBuffer(n, &out))) break;
        for (UINT32 i = 0; i < n; ++i)
            for (int c = 0; c < ch; ++c) {
                float s = c < 4 ? clampv(mix[size_t(i) * 4 + c], -1.0f, 1.0f) : 0.0f;
                if (flt) reinterpret_cast<float*>(out)[size_t(i) * ch + c] = s;
                else reinterpret_cast<int16_t*>(out)[size_t(i) * ch + c] = int16_t(s * 32767);
            }
        render->ReleaseBuffer(n, 0);
    }
    ok_ = false;
    client->Stop();
    if (mmcss) AvRevertMmThreadCharacteristics(mmcss);
    CoTaskMemFree(fmt);
    CloseHandle(ev);
    CoUninitialize();
}

void AudioEngine::start_game_audio(float gain, const std::string& hint) {
    game_audio_gain_ = gain;
    if (gain <= 0 || loop_.joinable()) return;
    ga_started_ = true;
    ga_hint_ = hint;
    loop_ = std::thread([this, hint] { loopback_thread(hint); });
}

void AudioEngine::loopback_thread(std::string hint) {
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    std::wstring whint(hint.begin(), hint.end());
    // the output the game plays on: the default one (or the configured one)
    IMMDevice* dev = find_endpoint(eRender, whint, L"");
    if (!dev) {
        LOGW("game-audio layer: no audio output to listen to");
        CoUninitialize();
        return;
    }
    // if that is the controller itself (headphones in its jack), only its sound channels are
    // captured - channels 3/4 carry our own haptics and must not feed back
    const bool controller = contains_ci(device_name(dev), L"DualSense");
    LOGI("game-audio layer listens to: %s%s", narrow(device_name(dev)).c_str(),
         controller ? " (sound channels only)" : "");
    ComPtr<IAudioClient> client;
    ComPtr<IAudioCaptureClient> cap;
    WAVEFORMATEX* fmt = nullptr;
    bool good = SUCCEEDED(dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&client)) &&
                SUCCEEDED(client->GetMixFormat(&fmt)) &&
                SUCCEEDED(client->Initialize(AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK, 200000, 0, fmt, nullptr)) &&
                SUCCEEDED(client->GetService(__uuidof(IAudioCaptureClient), (void**)&cap));
    dev->Release();
    if (!good) {
        LOGE("game-audio layer: loopback capture failed");
        if (fmt) CoTaskMemFree(fmt);
        CoUninitialize();
        return;
    }
    const int ch = fmt->nChannels;
    const double step = double(fmt->nSamplesPerSec) / dsp::kSR;
    LOGI("game-audio layer: %d ch %lu Hz", ch, fmt->nSamplesPerSec);
    dsp::StreamConverter conv;
    conv.gain = 1.0f;
    client->Start();
    double rs_pos = 0;
    float prev_l = 0, prev_r = 0;
    while (running_) {
        Sleep(4);
        UINT32 packet = 0;
        while (SUCCEEDED(cap->GetNextPacketSize(&packet)) && packet) {
            BYTE* data = nullptr;
            UINT32 n = 0;
            DWORD flags = 0;
            if (FAILED(cap->GetBuffer(&data, &n, &flags, nullptr, nullptr))) break;
            bool silent = flags & AUDCLNT_BUFFERFLAGS_SILENT;
            for (UINT32 i = 0; i < n; ++i) {
                float l = 0, r = 0;
                if (!silent) {
                    // downmix: front L/R plus centre, LFE and surrounds
                    l = sample_at(data, fmt, i, 0);
                    r = ch > 1 ? sample_at(data, fmt, i, 1) : l;
                    if (ch >= 6 && !controller) {
                        float c = sample_at(data, fmt, i, 2), lfe = sample_at(data, fmt, i, 3);
                        l += 0.7f * c + 0.7f * lfe + 0.6f * sample_at(data, fmt, i, 4);
                        r += 0.7f * c + 0.7f * lfe + 0.6f * sample_at(data, fmt, i, 5);
                    }
                }
                // resample to 48 kHz (linear) and convert
                while (rs_pos <= 1.0) {
                    float sl = prev_l + (l - prev_l) * float(rs_pos), sr = prev_r + (r - prev_r) * float(rs_pos);
                    float hl, hr;
                    conv.process(sl, sr, hl, hr);
                    size_t w = ring_w_.load(), nw = (w + 2) % ring_.size();
                    if (nw == ring_r_.load()) ring_r_ = (ring_r_.load() + 2) % ring_.size();   // overrun: drop oldest
                    ring_[w] = hl;
                    ring_[w + 1] = hr;
                    ring_w_ = nw;
                    rs_pos += step;
                }
                rs_pos -= 1.0;
                prev_l = l;
                prev_r = r;
            }
            cap->ReleaseBuffer(n);
        }
        // keep the layer close to real time (drop backlog over ~40 ms)
        size_t w = ring_w_.load(), r = ring_r_.load();
        size_t fill = (w + ring_.size() - r) % ring_.size();
        if (fill > size_t(dsp::kSR * 0.04) * 2) ring_r_ = (w + ring_.size() - size_t(dsp::kSR * 0.015) * 2) % ring_.size();
    }
    client->Stop();
    CoTaskMemFree(fmt);
    CoUninitialize();
}

void AudioEngine::start_mic(float sens, std::function<void()> on_whistle) {
    on_whistle_ = std::move(on_whistle);
    cooldown_s_ = std::max(0.3f, config().num("Mic", "Cooldown", 1.2f));
    if (mic_.joinable()) return;
    mic_started_ = true;
    mic_sens_ = sens;
    mic_ = std::thread([this, sens] { mic_thread(sens); });
}

// A whistle is a strong pure tone (500-4000 Hz) far above the rest of the spectrum, held ~0.15 s.
void AudioEngine::mic_thread(float sens) {
    CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    IMMDevice* dev = find_endpoint(eCapture, L"DualSense", L"");
    if (!dev) {
        LOGW("whistle: DualSense microphone not found");
        CoUninitialize();
        return;
    }
    ComPtr<IAudioClient> client;
    ComPtr<IAudioCaptureClient> cap;
    WAVEFORMATEX* fmt = nullptr;
    bool good = SUCCEEDED(dev->Activate(__uuidof(IAudioClient), CLSCTX_ALL, nullptr, (void**)&client)) &&
                SUCCEEDED(client->GetMixFormat(&fmt)) &&
                SUCCEEDED(client->Initialize(AUDCLNT_SHAREMODE_SHARED, 0, 200000, 0, fmt, nullptr)) &&
                SUCCEEDED(client->GetService(__uuidof(IAudioCaptureClient), (void**)&cap));
    dev->Release();
    if (!good) {
        LOGE("whistle: could not open the microphone");
        if (fmt) CoTaskMemFree(fmt);
        CoUninitialize();
        return;
    }
    LOGI("whistle detector on the controller mic (%d ch %lu Hz)", fmt->nChannels, fmt->nSamplesPerSec);
    const int N = 1024;
    const float sr = float(fmt->nSamplesPerSec);
    std::vector<float> frame;
    frame.reserve(N);
    std::vector<std::complex<float>> spec(N);
    int run = 0, misses = 0;
    float low_bg = 0;                  // background energy 80-400 Hz (game sound, room)
    float last_hz = 0;
    double cooldown_until = 0;
    std::vector<float> mags;
    client->Start();
    while (running_) {
        Sleep(10);
        UINT32 packet = 0;
        while (SUCCEEDED(cap->GetNextPacketSize(&packet)) && packet) {
            BYTE* data = nullptr;
            UINT32 n = 0;
            DWORD flags = 0;
            if (FAILED(cap->GetBuffer(&data, &n, &flags, nullptr, nullptr))) break;
            for (UINT32 i = 0; i < n; ++i) {
                float s = 0;
                if (!(flags & AUDCLNT_BUFFERFLAGS_SILENT)) {
                    for (int c = 0; c < fmt->nChannels; ++c) s += sample_at(data, fmt, i, c);
                    s /= fmt->nChannels;
                }
                frame.push_back(s);
                if (int(frame.size()) < N) continue;
                {
                    float pk = 0;
                    for (float v : frame) pk = std::max(pk, std::fabs(v));
                    mic_level_ = pk;
                }
                for (int k = 0; k < N; ++k) {
                    float w = 0.5f - 0.5f * std::cos(2 * kPi * k / (N - 1));
                    spec[k] = {frame[k] * w, 0.0f};
                }
                frame.erase(frame.begin(), frame.begin() + N / 2);     // 50 % overlap
                dsp::fft(spec);
                // whistles: ~500-4000 Hz. Compare the peak with the MEDIAN of the band (robust: the
                // whistle's own harmonics don't raise it), so low and soft whistles still stand out.
                // whistles: ~850-4000 Hz (yours were 1.1-1.4 kHz). Voices and music in that range have
                // their energy spread over many harmonics; a whistle puts almost all of it in one peak.
                int lo = int(850 * N / sr), hi = int(4000 * N / sr), band_lo = int(250 * N / sr), band_hi = int(6000 * N / sr);
                mags.resize(size_t(band_hi - band_lo));
                int best = lo;
                float best_v = 0, total = 0;
                for (int k = band_lo; k < band_hi; ++k) {
                    float v = std::abs(spec[k]);
                    mags[size_t(k - band_lo)] = v;
                    total += v * v;
                    if (k >= lo && k <= hi && v > best_v) { best_v = v; best = k; }
                }
                float peak_e = 0;
                for (int k = std::max(band_lo, best - 2); k <= std::min(band_hi - 1, best + 2); ++k)
                    peak_e += std::norm(spec[k]);
                float purity = peak_e / std::max(1e-12f, total);             // share of the energy in the peak
                float low_e = 0;                                              // 80-400 Hz: a voice's own pitch
                for (int k = int(80 * N / sr); k < int(400 * N / sr); ++k) low_e += std::norm(spec[k]);
                bool voiced = low_e > 4.0f * low_bg && low_e > 0.3f * peak_e;   // a voice just started
                low_bg = low_bg <= 0 ? low_e : low_bg + (std::min(low_e, 3.0f * low_bg) - low_bg) * 0.02f;
                std::nth_element(mags.begin(), mags.begin() + mags.size() / 2, mags.end());
                float median = std::max(1e-7f, mags[mags.size() / 2]);
                float hz = best * sr / N;
                float level = best_v / (N / 4);
                float s_eff = std::max(0.3f, sens);
                bool tonal = best_v > median * (12.0f / s_eff) && level > 0.0025f / s_eff && purity > 0.55f / std::sqrt(s_eff) && !voiced;
                bool steady = last_hz <= 0 || std::fabs(hz - last_hz) / last_hz < 0.3f;   // whistles glide a bit
                if (tonal && steady) {
                    ++run;
                    misses = 0;
                    last_hz = hz;
                } else if (run > 0 && ++misses <= 2) {
                    // tolerate a dropped frame or two (breath, a wobble)
                } else {
                    if (run >= 3 && run < int(0.15f * sr / (N / 2)))
                        LOGD("whistle candidate too short (%.0f Hz, %d frames)", last_hz, run);
                    run = 0;
                    misses = 0;
                    last_hz = 0;
                }
                double t = now_s();
                // ~0.15 s of steady tone
                if (run == int(0.15f * sr / (N / 2)) && mic_listening_ && t <= cooldown_until)
                    LOGD("whistle heard again during the %.1f s cooldown (%.0f Hz)", cooldown_s_, hz);
                if (run >= int(0.15f * sr / (N / 2)) && t > cooldown_until && mic_listening_) {
                    cooldown_until = t + cooldown_s_;
                    run = 0;
                    LOGI("whistle detected (%.0f Hz)", hz);
                    if (on_whistle_) on_whistle_();
                }
            }
            cap->ReleaseBuffer(n);
        }
    }
    client->Stop();
    CoTaskMemFree(fmt);
    CoUninitialize();
}

}  // namespace dsr2
