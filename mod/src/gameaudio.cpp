#include "gameaudio.h"

#include "log.h"

#include <fstream>
#include <set>

#include "../third_party/json.hpp"

namespace dsr2 {

static const std::set<uint32_t> kSharedSlots = {0x002683EB, 0x06CEA918, 0x0A888160, 0x0EB5B890, 0x0F3C0AF7, 0x1D24BDE6};

static bool is_weapon_bank(const std::string& b) {
    for (const char* p : {"REV_", "PTL_", "RPT_", "RFL_", "SNP_", "SHT_"})
        if (b.rfind(p, 0) == 0) return true;
    return false;
}

std::vector<float> GameSound::mono() const {
    if (right.empty()) return left;
    std::vector<float> m(left.size());
    for (size_t i = 0; i < m.size(); ++i) m[i] = 0.5f * (left[i] + right[i]);
    return m;
}

void GameAudio::discover(const fs::path& game_dir, const fs::path& labels_json) {
    std::lock_guard<std::mutex> l(mu_);
    paths_.clear();
    cache_.clear();
    std::error_code ec;
    fs::path lml = game_dir / "lml";
    if (fs::is_directory(lml, ec)) {
        for (auto& mod : fs::directory_iterator(lml, ec)) {
            if (!mod.is_directory()) continue;
            for (auto it = fs::recursive_directory_iterator(mod.path(), ec); it != fs::recursive_directory_iterator(); it.increment(ec)) {
                if (ec) break;
                if (!it->is_regular_file() || it->path().extension() != ".awc") continue;
                std::string bank = it->path().stem().string();
                std::string parent = it->path().parent_path().filename().string();
                bool preferred = parent == "WEAPONS_PLAYER" || parent == "RDR3.Resident" || parent == "RESIDENT";
                if (!paths_.count(bank) || preferred) paths_[bank] = it->path();
            }
        }
    }
    labels_.clear();
    std::ifstream in(labels_json);
    if (in) {
        try {
            nlohmann::json j = nlohmann::json::parse(in);
            for (auto& [k, v] : j.items()) labels_[k] = v.get<std::string>();
        } catch (const std::exception& e) {
            LOGW("sound_labels.json: %s", e.what());
        }
    }
    LOGI("game audio: %zu banks (%zu weapon banks), %zu labels", paths_.size(), bank_count(true), labels_.size());
}

size_t GameAudio::bank_count(bool weapons_only) const {
    if (!weapons_only) return paths_.size();
    size_t n = 0;
    for (auto& [b, _] : paths_) n += is_weapon_bank(b);
    return n;
}

const std::vector<GameSound>& GameAudio::sounds(const std::string& bank) {
    std::lock_guard<std::mutex> l(mu_);
    auto it = cache_.find(bank);
    if (it != cache_.end()) return it->second;
    return cache_[bank] = load(bank);
}

std::string GameAudio::role(const GameSound& s) const {
    auto it = labels_.find(s.bank + "/" + s.key);
    if (it != labels_.end()) return it->second;
    for (uint32_t id : s.ids) {                 // a label may name any of the sound's streams
        char key[16];
        snprintf(key, sizeof key, "0x%08X", id);
        it = labels_.find(s.bank + "/" + key);
        if (it != labels_.end()) return it->second;
    }
    return s.auto_role;
}

std::vector<const GameSound*> GameAudio::variants(const std::string& bank, const std::string& role_name) {
    std::vector<const GameSound*> out;
    if (!has_bank(bank)) return out;
    for (auto& s : sounds(bank))
        if (role(s) == role_name) out.push_back(&s);
    return out;
}

struct RawStream {
    uint32_t id;
    int rate;
    const int16_t* pcm;
    size_t n;
};

std::vector<GameSound> GameAudio::load(const std::string& bank) {
    std::vector<GameSound> out;
    auto pit = paths_.find(bank);
    if (pit == paths_.end()) return out;
    std::ifstream f(pit->second, std::ios::binary);
    std::vector<uint8_t> d((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    auto u16 = [&](size_t o) { return uint16_t(d[o] | (d[o + 1] << 8)); };
    auto u32 = [&](size_t o) { return uint32_t(d[o] | (d[o + 1] << 8) | (d[o + 2] << 16) | (uint32_t(d[o + 3]) << 24)); };
    if (d.size() < 16 || std::memcmp(d.data(), "ADAT", 4) != 0) {
        LOGW("%s: not a little-endian AWC", bank.c_str());
        return out;
    }
    uint16_t flags = u16(6);
    uint32_t count = u32(8);
    size_t off = 16 + ((flags & 1) ? 2 * count : 0);
    std::vector<uint32_t> infos(count);
    for (uint32_t i = 0; i < count; ++i) infos[i] = u32(off + 4 * i);
    off += 4 * count;
    std::vector<RawStream> streams;
    for (uint32_t info : infos) {
        size_t fmt_size = 0, fmt_off = 0, data_size = 0, data_off = 0;
        bool has_fmt = false, has_data = false;
        for (uint32_t c = 0; c < (info >> 29); ++c) {
            uint64_t v = uint64_t(u32(off)) | (uint64_t(u32(off + 4)) << 32);
            off += 8;
            uint32_t type = uint32_t(v >> 56);
            size_t size = size_t((v >> 28) & 0x0FFFFFFF), o = size_t(v & 0x0FFFFFFF);
            if (type == 0x76) { has_fmt = true; fmt_size = size; fmt_off = o; }
            if (type == 0x55) { has_data = true; data_size = size; data_off = o; }
        }
        (void)fmt_size;
        if (!has_fmt || !has_data || fmt_off + 10 > d.size()) continue;
        uint32_t samples = u32(fmt_off);
        int rate = u16(fmt_off + 8);
        if (data_size != size_t(samples) * 2 || data_off + data_size > d.size() || !samples) continue;  // PCM16 only
        streams.push_back({info & 0x1FFFFFFF, rate, reinterpret_cast<const int16_t*>(d.data() + data_off), samples});
    }
    // de-duplicate identical recordings in several slots
    auto fnv = [](const int16_t* p, size_t n) {
        uint64_t h = 1469598103934665603ull;
        auto* b = reinterpret_cast<const uint8_t*>(p);
        for (size_t i = 0; i < n * 2; ++i) h = (h ^ b[i]) * 1099511628211ull;
        return h;
    };
    std::map<uint64_t, size_t> seen;
    std::vector<std::pair<RawStream, std::vector<uint32_t>>> uniq;
    for (auto& s : streams) {
        uint64_t h = fnv(s.pcm, s.n) ^ s.n;
        auto it = seen.find(h);
        if (it != seen.end()) {
            uniq[it->second].second.push_back(s.id);
            continue;
        }
        seen[h] = uniq.size();
        uniq.push_back({s, {s.id}});
    }
    // pair the left/right halves of stereo recordings
    auto rms = [](const RawStream& s) {
        double a = 0;
        for (size_t i = 0; i < s.n; ++i) a += double(s.pcm[i]) * s.pcm[i];
        return std::sqrt(a / s.n);
    };
    auto corr = [](const RawStream& a, const RawStream& b) {
        double ma = 0, mb = 0;
        for (size_t i = 0; i < a.n; ++i) { ma += a.pcm[i]; mb += b.pcm[i]; }
        ma /= a.n; mb /= b.n;
        double sab = 0, saa = 0, sbb = 0;
        for (size_t i = 0; i < a.n; ++i) {
            double x = a.pcm[i] - ma, y = b.pcm[i] - mb;
            sab += x * y; saa += x * x; sbb += y * y;
        }
        return saa > 0 && sbb > 0 ? sab / std::sqrt(saa * sbb) : 0.0;
    };
    std::vector<double> r(uniq.size());
    for (size_t i = 0; i < uniq.size(); ++i) r[i] = rms(uniq[i].first);
    struct Pair { double c; size_t a, b; };
    std::vector<Pair> pairs;
    for (size_t a = 0; a < uniq.size(); ++a)
        for (size_t b = a + 1; b < uniq.size(); ++b) {
            if (uniq[a].first.n != uniq[b].first.n) continue;
            if (std::fabs(r[a] - r[b]) > 0.04 * std::max({r[a], r[b], 1e-6})) continue;
            double c = corr(uniq[a].first, uniq[b].first);
            if (c > 0.3) pairs.push_back({c, a, b});
        }
    std::sort(pairs.begin(), pairs.end(), [](const Pair& x, const Pair& y) { return x.c > y.c; });
    std::vector<int> partner(uniq.size(), -1);
    for (auto& p : pairs)
        if (partner[p.a] < 0 && partner[p.b] < 0) { partner[p.a] = int(p.b); partner[p.b] = int(p.a); }
    std::vector<bool> done(uniq.size(), false);
    bool weapon = is_weapon_bank(bank);
    for (size_t i = 0; i < uniq.size(); ++i) {
        if (done[i]) continue;
        GameSound gs;
        gs.bank = bank;
        char key[16];
        snprintf(key, sizeof key, "0x%08X", uniq[i].first.id);
        gs.key = key;
        gs.rate = uniq[i].first.rate;
        gs.ids = uniq[i].second;
        gs.left.resize(uniq[i].first.n);
        for (size_t k = 0; k < gs.left.size(); ++k) gs.left[k] = uniq[i].first.pcm[k] / 32768.0f;
        if (partner[i] >= 0) {
            size_t j = size_t(partner[i]);
            done[j] = true;
            gs.ids.insert(gs.ids.end(), uniq[j].second.begin(), uniq[j].second.end());
            gs.right.resize(uniq[j].first.n);
            for (size_t k = 0; k < gs.right.size(); ++k) gs.right[k] = uniq[j].first.pcm[k] / 32768.0f;
        }
        bool shared = false;
        for (uint32_t id : gs.ids) shared |= kSharedSlots.count(id) != 0;
        if (weapon) gs.auto_role = shared ? "shared" : "shot";
        else if (bank == "EXPLOSIONS") gs.auto_role = gs.seconds() > 0.8f ? "explosion" : "other";
        else gs.auto_role = "unknown";
        out.push_back(std::move(gs));
    }
    LOGD("bank %s: %zu streams -> %zu sounds", bank.c_str(), streams.size(), out.size());
    return out;
}

}  // namespace dsr2
