// dsr2_test.exe - runs the whole mod without the game: real controller, triggers, haptics,
// game-audio layer, whistle detector, gyro. Usage: dsr2_test [WEAPON_NAME] [seconds]
// Data is read from <exe dir>/DualSenseRDR2/, log goes to the console.
#include "audio.h"
#include "awc.h"
#include "dialogue.h"
#include "dsp.h"
#include "common.h"
#include "core.h"
#include "log.h"
#include "world.h"

#include <cstdio>

namespace dsr2 {
int run_selftests(const fs::path& data);
fs::path module_dir() {
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(nullptr, path, MAX_PATH);
    return fs::path(path).parent_path();
}
}  // namespace dsr2

// --awc <game dir> line|cut <id hex> <out.wav>: decode a spoken line (stream id) or a whole cutscene file (any of
// its channel ids) from the game's archives with the mod's own index + decoder, for checking against recordings
static int awc_tool(int argc, char** argv) {
    using namespace dsr2;
    if (argc < 6) return 2;
    log::set_debug(true);
    awc::Index& ix = awc::index();
    ix.build(argv[2]);
    if (std::string(argv[3]) == "cutall") {          // decode every cutscene file: how many fail
        int ok = 0, bad = 0;
        std::vector<uint64_t> seen;
        for (const awc::Entry& e : ix.all(awc::Cutscene)) {
            if (std::find(seen.begin(), seen.end(), e.file) != seen.end()) continue;
            seen.push_back(e.file);
            std::vector<std::vector<float>> ch;
            std::vector<uint32_t> ids;
            int rate = 0;
            if (awc::decode_cutscene(ix, e, ch, ids, rate)) ++ok;
            else { ++bad; printf("  failed: file at 0x%llX (channel %08X)\n", (unsigned long long)e.file, e.id); }
        }
        printf("cutscenes decoded: %d ok, %d failed\n", ok, bad);
        return 0;
    }
    if (std::string(argv[3]) == "pickwav" && argc > 6) {   // pickwav <id> <voice> <out.wav>: the speaker's own take, decoded
        awc::Entry e;
        if (!ix.find_line(uint32_t(strtoul(argv[4], nullptr, 16)), uint32_t(strtoul(argv[5], nullptr, 16)), e)) return 1;
        std::vector<float> v;
        int rate = 0;
        if (!awc::decode_line(ix, e, v, rate)) return 1;
        FILE* o = fopen(argv[6], "wb");
        if (!o) return 1;
        uint32_t bytes = uint32_t(v.size() * 4), rr = uint32_t(rate);
        uint32_t hdr[] = {0x46464952, 36 + bytes, 0x45564157, 0x20746D66, 16, 3 | (1u << 16), rr, rr * 4, 4 | (32u << 16), 0x61746164, bytes};
        fwrite(hdr, 4, 11, o);
        fwrite(v.data(), 4, v.size(), o);
        fclose(o);
        return 0;
    }
    if (std::string(argv[3]) == "pick") {            // which file a line comes from for this voice: pick <id> <voice>
        awc::Entry e;
        uint32_t id = uint32_t(strtoul(argv[4], nullptr, 16)), voice = uint32_t(strtoul(argv[5], nullptr, 16));
        size_t n = ix.find(id, awc::Speech).size();
        if (!ix.find_line(id, voice, e)) { printf("line %08X voice %08X: no sure file (%zu candidates)\n", id, voice, n); return 1; }
        printf("line %08X voice %08X: %s at 0x%llX (fingerprint %016llX), out of %zu candidates\n", id, voice,
               ix.archive_path(e.archive).filename().string().c_str(), (unsigned long long)e.file,
               (unsigned long long)e.fingerprint, n);
        return 0;
    }
    if (std::string(argv[3]) == "linehap") {         // a spoken line and its speech vibration: L voice, R haptic
        auto f = ix.find(uint32_t(strtoul(argv[4], nullptr, 16)), awc::Speech);
        std::vector<float> v;
        int rate = 0;
        if (f.empty() || !awc::decode_line(ix, f[0], v, rate)) { printf("line not found / not decoded\n"); return 1; }
        if (rate != 48000) v = dsp::resample(v.data(), v.size(), rate);
        auto h = speech_haptic(v);
        size_t on = 0;
        for (float x : h) on += std::fabs(x) > 0.05f;
        FILE* o = fopen(argv[5], "wb");
        if (!o) return 1;
        size_t n = v.size();
        uint32_t bytes = uint32_t(n * 8), rr = 48000;
        uint32_t hdr[] = {0x46464952, 36 + bytes, 0x45564157, 0x20746D66, 16, 3 | (2u << 16), rr, rr * 8, 8 | (32u << 16), 0x61746164, bytes};
        fwrite(hdr, 4, 11, o);
        for (size_t i = 0; i < n; ++i) { fwrite(&v[i], 4, 1, o); fwrite(&h[i], 4, 1, o); }
        fclose(o);
        printf("%s: %.2f s, haptic on %.0f %% of the time\n", argv[5], n / 48000.0, 100.0 * on / std::max<size_t>(1, n));
        return 0;
    }
    bool cut = std::string(argv[3]) == "cut";
    uint32_t id = uint32_t(strtoul(argv[4], nullptr, 16));
    auto found = ix.find(id, cut ? awc::Cutscene : awc::Speech);
    if (found.empty()) { printf("id %08X not found\n", id); return 1; }
    std::vector<std::vector<float>> ch;
    std::vector<uint32_t> ids;
    int rate = 0;
    double t0 = now_s();
    if (cut) {
        if (!awc::decode_cutscene(ix, found[0], ch, ids, rate)) { printf("decode failed\n"); return 1; }
    } else {
        ch.resize(1);
        if (!awc::decode_line(ix, found[0], ch[0], rate)) { printf("decode failed\n"); return 1; }
    }
    double dt = now_s() - t0;
    size_t n = ch[0].size();
    for (auto& c : ch) n = std::min(n, c.size());
    FILE* f = fopen(argv[5], "wb");
    if (!f) return 1;
    uint32_t nch = uint32_t(ch.size()), bytes = uint32_t(n * nch * 4), rr = uint32_t(rate);
    uint32_t hdr[] = {0x46464952, 36 + bytes, 0x45564157, 0x20746D66, 16, 0x00030000u | 0, rr, rr * nch * 4, 0, 0x61746164, bytes};
    hdr[5] = 3 | (nch << 16);                       // IEEE float, channels
    hdr[8] = (nch * 4) | (32u << 16);               // block align, bits
    fwrite(hdr, 4, 11, f);
    for (size_t i = 0; i < n; ++i)
        for (auto& c : ch) fwrite(&c[i], 4, 1, f);
    fclose(f);
    printf("%s: %u ch, %zu samples (%.2f s) at %d Hz, %zu matches, decoded in %.0f ms\n", argv[5], nch, n,
           double(n) / rate, rate, found.size(), dt * 1000);
    return 0;
}

int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--selftest") return dsr2::run_selftests(dsr2::data_dir());
    if (argc > 1 && std::string(argv[1]) == "--awc") return awc_tool(argc, argv);
    if (argc > 1 && std::string(argv[1]) == "--outputs") {
        printf("%s", dsr2::describe_outputs().c_str());
        return 0;
    }
    if (argc > 1 && std::string(argv[1]) == "--mic") {
        // mic test: whistle and voice detection only, results printed as they happen
        dsr2::log::set_debug(true);
        printf("\n  DualSense mic test\n  ------------------\n"
               "  Whistle at the controller, or say \"chao\".\n"
               "  Every detection prints here and you feel two knocks in the controller.\n"
               "  Lines marked DEBUG show near-misses and words heard but ignored.\n"
               "  The mute button pauses listening. Close this window to stop.\n\n");
        fflush(stdout);
        if (!dsr2::core().init(false, "WEAPON_UNARMED")) return 1;
        dsr2::log::set_debug(true);
        double next = 0;
        while (true) {
            dsr2::core().script_tick();
            Sleep(16);
            if (dsr2::now_s() >= next) {        // live mic level, so you can see sound arrives
                next = dsr2::now_s() + 0.25;
                float lv = dsr2::core().audio().mic_level();
                float db = 20.0f * std::log10(std::max(lv, 1e-5f));          // -100 .. 0 dBFS
                int bars = std::clamp(int((db + 70.0f) / 70.0f * 40.0f), 0, 40);  // -70 dB .. 0 dB
                printf("\r  mic %-40s %6.1f dB  %s ", std::string(bars, '#').c_str(), db,
                       dsr2::core().audio().mic_listening() ? "listening" : "MUTED    ");
                fflush(stdout);
            }
        }
    }
    std::string weapon = argc > 1 ? argv[1] : "WEAPON_REVOLVER_CATTLEMAN";
    double seconds = argc > 2 ? atof(argv[2]) : 1e9;
    LOGI("standalone test: %s", weapon.c_str());
    if (!dsr2::core().init(false, weapon)) return 1;
    double t0 = dsr2::now_s(), next = t0 + 1;
    while (dsr2::now_s() - t0 < seconds) {
        dsr2::core().script_tick();
        Sleep(16);
        if (dsr2::now_s() >= next) {
            next += 1;
            printf("%s\n", dsr2::core().status().c_str());
            fflush(stdout);
        }
    }
    dsr2::core().shutdown();
    return 0;
}
