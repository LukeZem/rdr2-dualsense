#include "dialogue.h"

#include "audio.h"
#include "config.h"
#include "dsp.h"
#include "gamemem.h"
#include "log.h"

#include <complex>
#include <tuple>

namespace dsr2 {

Dialogue& dialogue() {
    static Dialogue d;
    return d;
}

namespace {

constexpr uint64_t kKeyCutSpeech = 0xD000000000000000ull, kKeyLine = 0xA000000000000000ull;
constexpr double kLive = 0.3;          // a stem is playing if its position moved within this long
// measured against loopback recordings of the game: a spoken line leaves the PC 47 ms (median of 19) after its
// request turns "playing"; a cutscene stem's position field runs 62 ms ahead of what leaves the PC
constexpr double kSpeechOut = 0.047, kCutsceneOut = 0.062;
// A spoken line does not start when its request turns "playing": NPC lines are heard ~0.26 s later (0 - 0.4 s),
// Arthur's at once. The line's wave player ([sound+0xC0]) keeps a millisecond play clock at +0x11C that starts a
// constant ~0.21 s after the voice leaves the PC (36 lines against a loopback recording, Arthur and NPCs alike) -
// so each line is timed from that clock: felt at clock start - 0.21 + 0.047 + the TV / headphone delay.
// Before the clock starts the track waits; no clock within 0.8 s -> timed from "playing" as before.
constexpr double kClockAfterOut = 0.21;
// "auto" sound delay after the PC: Bluetooth headphones buffer ~150-250 ms (A2DP codecs), TVs / wired ~20-100 ms
constexpr float kBluetoothDelay = 0.200f, kWiredDelay = 0.060f;

float percentile(std::vector<float> v, float p) {
    if (v.empty()) return 0;
    size_t k = std::min(v.size() - 1, size_t(p * float(v.size() - 1)));
    std::nth_element(v.begin(), v.begin() + long(k), v.end());
    return v[k];
}

std::vector<float> to48k(std::vector<float>&& x, int rate) {
    if (rate == dsp::kSR || rate <= 0) return std::move(x);
    return dsp::resample(x.data(), x.size(), rate);
}

}  // namespace

// The voice itself in the actuators - its 70 - 900 Hz band (pitch and first harmonics: deep, not a high buzz; the speaker's
// own timbre; the controller speaks into your hands), extra weight below 250 Hz, at a steady level
// (compressed: quiet lines are felt, stressed syllables still lead), silence gated.
std::vector<float> speech_haptic(const std::vector<float>& v) {
    const size_t n = v.size();
    std::vector<float> out(n, 0.0f);
    if (!n) return out;
    std::vector<float> y(n), lev(n), gate(n);
    dsp::Band band(70, 900), weight(60, 250);
    dsp::Follower f_lev(3, 80), f_gl(2, 25);
    for (size_t i = 0; i < n; ++i) {
        y[i] = band.run(v[i]) + 0.9f * weight.run(v[i]);
        lev[i] = f_lev.run(y[i]);
        gate[i] = f_gl.run(y[i]);
    }
    std::vector<float> s_lev;
    for (size_t i = 0; i < n; i += 48) s_lev.push_back(lev[i]);
    const float ref = percentile(s_lev, 0.95f);
    if (ref < 1e-5f) return out;
    dsp::Follower f_gate(2, 30);
    for (size_t i = 0; i < n; ++i) {
        float r = lev[i] / ref;
        float g = clampv((gate[i] / ref - 0.05f) / 0.10f, 0.0f, 1.0f);
        g = f_gate.run(g * g * (3 - 2 * g));
        float gain = 0.55f / std::max(lev[i], 0.15f * ref);          // steady level
        float dyn = std::pow(std::min(r, 1.3f), 0.35f);              // some of the stress stays
        out[i] = std::tanh(1.6f * y[i] * gain * dyn) * 0.85f * g;
    }
    return out;
}

void Dialogue::configure() {
    Config& c = config();
    bool on = c.flag("Haptics", "Enabled", true);
    enabled_ = on;
    // Dialogue (on / off), its strength (Speech), where (everywhere / cutscenes)
    on = on && c.flag("Haptics", "Dialogue", false);
    speech_gain_ = on ? clampv(c.num("Haptics", "Speech", 0.6f), 0.0f, 2.0f) : 0.0f;
    cutscenes_only_ = c.str("Haptics", "DialogueIn", "everywhere") == "cutscenes";
    probes_on_ = c.flag("General", "Probes", false) && log::debug_enabled();
    // the sound reaches you later than the PC plays it (TV, Bluetooth headphones...): "auto" = by the output
    // device (Bluetooth ~200 ms, anything else ~60 ms; Windows does not report the real figure), or a number in ms
    std::string d = c.str("Haptics", "SoundDelayMs", "auto");
    auto_delay_ = d.empty() || d == "auto";
    if (!auto_delay_) tv_s_ = clampv(float(atof(d.c_str())), 0.0f, 500.0f) / 1000.0f;
    else tv_s_ = out_bluetooth_ ? kBluetoothDelay : kWiredDelay;
    cv_.notify_all();
}

void Dialogue::start(const fs::path& game_dir, AudioEngine* audio) {
    if (running_) return;
    game_dir_ = game_dir;
    audio_ = audio;
    running_ = true;
    th_ = std::thread([this] { worker(); });
}

void Dialogue::stop() {
    running_ = false;
    cv_.notify_all();
    if (th_.joinable()) th_.join();
}

void Dialogue::stop_cutscene() {
    if (!tracks_on_) return;
    audio_->track_stop(kKeyCutSpeech | playing_file_);
    tracks_on_ = false;
    LOGD("dialogue haptics: cutscene stopped");
}

void Dialogue::worker() {
    // nothing at all (no index, no scans) until it is switched on
    while (running_ && speech_gain_ <= 0) {
        std::unique_lock<std::mutex> l(mu_);
        cv_.wait_for(l, std::chrono::milliseconds(500));
    }
    if (!running_) return;
    if (!gamemem::init()) {
        LOGW("dialogue haptics: the game's audio state was not found (other game version?) - off");
        return;
    }
    awc::Index& ix = awc::index();
    ix.build(game_dir_);
    cut_bits_.assign((1u << 20) / 64, 0);
    for (const awc::Entry& e : ix.all(awc::Cutscene)) {
        cut_ids_.insert(e.id);
        uint32_t b = e.id & 0xFFFFF;
        cut_bits_[b >> 6] |= 1ull << (b & 63);
    }
    double next_scan = 0, next_out = 0;
    while (running_) {
        if (now_s() >= next_out) {                     // where the sound goes (headphones switched on / off)
            next_out = now_s() + 2.0;
            std::string name;
            bool bt = false;
            if (default_output(name, bt) && (name != out_name_ || bt != out_bluetooth_)) {
                out_name_ = name;
                out_bluetooth_ = bt;
                if (auto_delay_) tv_s_ = bt ? kBluetoothDelay : kWiredDelay;
                LOGI("dialogue haptics: the sound goes to %s%s - sound delay %s %.0f ms", name.c_str(), bt ? " (Bluetooth)" : "",
                     auto_delay_ ? "auto" : "set to", tv_s_ * 1000);
            }
        }
        LineJob job;
        bool have = false;
        {
            std::lock_guard<std::mutex> l(mu_);
            if (!line_jobs_.empty()) {
                job = line_jobs_.front();
                line_jobs_.pop_front();
                have = true;
            }
        }
        if (have) {
            prepare_line(job.key, job.e, job.t_start, job.gl, job.gr);
            continue;
        }
        double now = now_s();
        if (speech_gain_ > 0 && gamemem::pool_ok()) {
            if (now >= next_scan) {
                cutscene_scan(now);
                next_scan = now + 0.25;
            }
            cutscene_poll(now);
        } else {
            stop_cutscene();
        }
        std::unique_lock<std::mutex> l(mu_);
        cv_.wait_for(l, std::chrono::milliseconds(10), [this] { return !line_jobs_.empty() || !running_; });
    }
    stop_cutscene();
}

// every 250 ms: which cutscene stems are in the sound pool (prepared or playing); decode new cutscene files
void Dialogue::cutscene_scan(double now) {
    std::vector<gamemem::Stem> st;
    gamemem::pool_stems(
        [this](uint32_t id) {
            uint32_t b = id & 0xFFFFF;
            return ((cut_bits_[b >> 6] >> (b & 63)) & 1) && cut_ids_.count(id);
        },
        st);
    std::map<uintptr_t, StemSeen> next;
    std::set<uint64_t> files;
    for (const auto& s : st) {
        auto it = stems_.find(s.field);
        StemSeen v = it != stems_.end() && it->second.id == s.id ? it->second : StemSeen{};
        if (!v.file) {
            auto f = awc::index().find(s.id, awc::Cutscene);
            if (f.empty()) continue;
            v.file = f[0].file;
            v.id = s.id;
            v.ms = s.ms;
            v.t = now;
        }
        next[s.field] = v;
        files.insert(v.file);
    }
    stems_.swap(next);
    for (uint64_t f : files)
        if (!cuts_.count(f)) {
            for (const auto& [field, s] : stems_)
                if (s.file == f) {
                    auto e = awc::index().find(s.id, awc::Cutscene);
                    if (!e.empty()) prepare_cutscene(e[0]);
                    break;
                }
        }
}

// A cutscene file holds the cutscene's mastered dialogue in sets of three stems; the game plays one set, and what
// you hear is the set's FIRST stem (checked against loopback recordings of three cutscenes: correlation 0.9 - 1.0;
// the other two are not heard). Every set's first stem becomes a speech haptic; playback picks the live set.
void Dialogue::prepare_cutscene(const awc::Entry& e) {
    Cut& c = cuts_[e.file];
    c.entry = e;
    double t0 = now_s();
    std::vector<std::vector<float>> ch;
    int rate = 0;
    if (!awc::decode_cutscene(awc::index(), e, ch, c.ids, rate) || ch.empty()) {
        c.failed = true;
        LOGW("dialogue haptics: could not decode a cutscene's dialogue (file 0x%llX)", (unsigned long long)e.file);
        return;
    }
    double secs = 0;
    for (size_t k = 0; k < ch.size(); k += 3) {
        secs = std::max(secs, double(ch[k].size()) / std::max(1, rate));
        c.speech[int(k / 3)] = std::make_shared<const std::vector<float>>(speech_haptic(to48k(std::move(ch[k]), rate)));
    }
    c.decoded = true;
    LOGI("dialogue haptics: cutscene dialogue ready (%.1f s, %zu set(s)) in %.0f ms", secs, c.speech.size(),
         (now_s() - t0) * 1000);
    // keep the last few
    while (cuts_.size() > 3) {
        auto victim = cuts_.end();
        for (auto it = cuts_.begin(); it != cuts_.end(); ++it)
            if (it->first != e.file && it->first != playing_file_) { victim = it; break; }
        if (victim == cuts_.end()) break;
        cuts_.erase(victim);
    }
}

// every 10 ms: the playing cutscene's position -> its dialogue haptic on the game's clock
void Dialogue::cutscene_poll(double now) {
    uint64_t file = 0;
    uint32_t live_id = 0;
    double est = 1e18;
    for (auto& [field, s] : stems_) {
        uint32_t v[2];
        if (!gamemem::read(field, v, sizeof v) || (v[1] & 0x1FFFFFFF) != s.id) continue;   // the slot was reused
        if (v[0] != s.ms) {
            if (v[0] > s.ms && v[0] - s.ms < 2000) s.advanced = now;
            s.ms = v[0];
            s.t = now;
        }
        if (s.advanced > 0 && now - s.advanced < kLive) {
            file = s.file;
            live_id = s.id;
            est = std::min(est, s.t - s.ms / 1000.0);   // when the file's sample 0 left the game's mixer
        }
    }
    if (!file || file != playing_file_) stop_cutscene();   // nothing playing, or another cutscene now
    if (!file) return;
    // the position field moves in ~40 ms steps: the least delayed estimate is the best; a jump = seek / restart
    if (!tracks_on_ || std::fabs(est - play_t0_) > 0.25) play_t0_ = est;
    else if (est < play_t0_) play_t0_ = est;
    auto it = cuts_.find(file);
    if (it == cuts_.end() || !it->second.decoded) return;
    const Cut& c = it->second;
    int set = 0;
    for (size_t k = 0; k < c.ids.size(); ++k)
        if (c.ids[k] == live_id) set = int(k / 3);
    auto sp = c.speech.find(set);
    if (sp == c.speech.end()) return;
    double t_felt = play_t0_ + kCutsceneOut + tv_s_;
    float g = speech_gain_;
    uint64_t key = kKeyCutSpeech | file;
    if (!tracks_on_ || set != playing_set_) {
        if (tracks_on_) audio_->track_stop(key);
        playing_file_ = file;
        playing_set_ = set;
        audio_->track_play(key, sp->second, t_felt, g, g);
        tracks_on_ = true;
        LOGD("dialogue haptics: cutscene file 0x%llX set %d from %.2f s", (unsigned long long)file, set, now - play_t0_);
    } else {
        audio_->track_move(key, t_felt, g, g);
    }
}

void Dialogue::prepare_line(uint64_t key, const awc::Entry& e, double t_start, float gl, float gr) {
    std::vector<float> v;
    int rate = 0;
    if (!awc::decode_line(awc::index(), e, v, rate)) {
        LOGD("speech haptics: could not decode line %08X", e.id);
        return;
    }
    auto h = std::make_shared<const std::vector<float>>(speech_haptic(to48k(std::move(v), rate)));
    audio_->track_play(key, h, t_start + 30.0, gl, gr);     // waits: game_tick times it from the line's play clock
}

void Dialogue::game_tick(const std::vector<Talker>& talkers, uint32_t native_player_line) {
    if (!running_ || !audio_) return;
    bool on = speech_gain_ > 0 && !cutscenes_only_ && !speech_layout_bad_ && gamemem::speech_ok() && awc::index().ready();
    double now = now_s();
    for (auto& [a, s] : said_) s.seen = false;
    std::vector<gamemem::Request> reqs;
    if (on) {
        for (const Talker& t : talkers) {
            if (!gamemem::ped_requests(t.obj, reqs)) continue;
            for (const auto& r : reqs) {
                if (r.state != 5 || (r.type != 1 && r.type != 2) || !r.partial) continue;
                uint32_t sid = awc::line_stream_id(r.partial, r.variation);
                uint64_t key = kKeyLine | (uint64_t(r.addr & 0xFFFFFFFFFFFull) << 12) | (sid & 0xFFF);
                float g = speech_gain_ * (t.player ? 1.0f : clampv(1.0f - (t.dist - 3.0f) / 22.0f, 0.2f, 1.0f));
                float gl = 1, gr = 1;
                if (!t.player) dsp::pan_gains(t.pan, gl, gr);
                auto it = said_.find(r.addr);
                if (it != said_.end() && it->second.key == key) {
                    Said& sd = it->second;
                    sd.seen = true;
                    // the wave player's play clock (ms): when the line really started
                    uintptr_t child = 0;
                    uint32_t ms = 0;
                    if (r.sound && gamemem::read(r.sound + 0xC0, child) && child && gamemem::read(child + 0x11C, ms) &&
                        ms > 0 && ms < 60000) {
                        double est = now - ms / 1000.0;
                        if (sd.start < 0 || std::fabs(est - sd.start) > 0.25) sd.start = est;     // first sight / restart
                        else sd.start = std::min(sd.start, est);                                   // least delayed reading
                    }
                    double t0 = sd.start >= 0 ? sd.start - kClockAfterOut + kSpeechOut + tv_s_
                                : now - sd.t > 0.8 ? sd.t + kSpeechOut + tv_s_                    // no clock: as before
                                                   : now + 30.0;                                  // wait for the clock
                    audio_->track_move(key, t0, gl * g, gr * g);    // follows the speaker's side
                    continue;
                }
                if (it != said_.end()) audio_->track_stop(it->second.key);
                said_[r.addr] = {key, now, true};
                if (probes_on_) probe_start(r.sound, sid, r.voice, t.dist, t.player, now);
                // the memory layout checked against the game's own native, on the player's lines
                if (t.player && native_player_line) {
                    if (awc::joaat_finish(r.partial) == native_player_line) ++check_ok_;
                    else if (++check_bad_ >= 4 && check_ok_ == 0) {
                        speech_layout_bad_ = true;
                        LOGW("speech haptics: the game's speech data does not match (other game version?) - off");
                        return;
                    }
                }
                awc::Entry line;
                if (!awc::index().find_line(sid, r.voice, line)) {
                    // not a spoken line (animals, grunts) or no sure match: nothing rather than another speaker's take
                    LOGD("dialogue haptics: line %08X voice %08X - no recording of this speaker", sid, r.voice);
                    continue;
                }
                {
                    std::lock_guard<std::mutex> l(mu_);
                    line_jobs_.push_back({key, line, now, gl * g, gr * g});
                }
                cv_.notify_one();
            }
        }
    }
    for (auto it = said_.begin(); it != said_.end();) {
        if (!it->second.seen) {
            audio_->track_stop(it->second.key);
            it = said_.erase(it);
        } else {
            ++it;
        }
    }
    if (probes_on_) probe_tick(now);
}

static const char* const kProbeNames[6] = {"snd", "c0", "c8", "d0", "o8", "o10"};

void Dialogue::probe_start(uintptr_t sound, uint32_t sid, uint32_t voice, float dist, bool player, double now) {
    if (!sound) return;
    Probe& p = probes_[sound];
    p = Probe{};
    p.t0 = now;
    p.sid = sid;
    p.voice = voice;
    p.addr[0] = sound;
    const uint32_t offs[5] = {0xC0, 0xC8, 0xD0, 0x08, 0x10};
    for (int k = 0; k < 5; ++k) gamemem::read(sound + offs[k], p.addr[k + 1]);
    LOGD("lineprobe NEW %.4f line %08X voice %08X dist %.1f%s snd %llX c0 %llX c8 %llX d0 %llX o8 %llX o10 %llX", now, sid,
         voice, dist, player ? " player" : "", (unsigned long long)sound, (unsigned long long)p.addr[1],
         (unsigned long long)p.addr[2], (unsigned long long)p.addr[3], (unsigned long long)p.addr[4], (unsigned long long)p.addr[5]);
    for (int k = 0; k < 6; ++k) {
        uintptr_t a = p.addr[k];
        if (a < 0x10000000000ull || a > 0x7FF000000000ull) continue;
        p.last[k].resize(0x300);
        if (!gamemem::read(a, p.last[k].data(), 0x300)) { p.last[k].clear(); continue; }
        for (size_t o = 0; o < 0x300; o += 0x100) {
            char hex[0x100 * 2 + 1];
            for (size_t i = 0; i < 0x100; ++i) snprintf(hex + 2 * i, 3, "%02X", p.last[k][o + i]);
            LOGD("lineprobe DUMP %.4f %llX %s +%03zX %s", now, (unsigned long long)sound, kProbeNames[k], o, hex);
        }
    }
}

void Dialogue::probe_tick(double now) {
    std::vector<uint8_t> cur(0x300);
    for (auto it = probes_.begin(); it != probes_.end();) {
        Probe& p = it->second;
        if (now - p.t0 > 4.0) { it = probes_.erase(it); continue; }
        for (int k = 0; k < 6; ++k) {
            if (p.last[k].empty() || !gamemem::read(p.addr[k], cur.data(), cur.size())) continue;
            for (size_t o = 0; o + 4 <= cur.size(); o += 4)
                if (std::memcmp(&cur[o], &p.last[k][o], 4)) {
                    uint32_t a, b;
                    std::memcpy(&a, &p.last[k][o], 4);
                    std::memcpy(&b, &cur[o], 4);
                    LOGD("lineprobe CHG %.4f %llX %s +%03zX %08X -> %08X", now, (unsigned long long)it->first, kProbeNames[k], o, a, b);
                }
            p.last[k] = cur;
        }
        ++it;
    }
}

}  // namespace dsr2
