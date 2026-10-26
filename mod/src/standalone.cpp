// dsr2_test.exe - runs the whole mod without the game: real controller, triggers, haptics,
// game-audio layer, whistle detector, gyro. Usage: dsr2_test [WEAPON_NAME] [seconds]
// Data is read from <exe dir>/DualSenseRDR2/, log goes to the console.
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

int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "--selftest") return dsr2::run_selftests(dsr2::data_dir());
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
