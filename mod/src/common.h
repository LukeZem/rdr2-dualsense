// Shared helpers for the DualSense RDR2 mod.
#pragma once

#include <windows.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace dsr2 {

namespace fs = std::filesystem;

constexpr const char* kVersion = "1.2.1";
constexpr float kPi = 3.14159265358979f;

inline double now_s() {
    static const double inv = [] {
        LARGE_INTEGER f;
        QueryPerformanceFrequency(&f);
        return 1.0 / double(f.QuadPart);
    }();
    LARGE_INTEGER c;
    QueryPerformanceCounter(&c);
    return double(c.QuadPart) * inv;
}

// The game's fishing task, read every frame while the rod is out (fields of the 30-slot struct
// TASK::_GET_TASK_FISHING fills - layout from Rockstar's fishing_core script).
struct FishingState {
    bool active = false;
    int state = 0;          // 1 idle, 2 grip, 3 pulling back, 4 casting, 6 line in the water, 7 hooked, 12 in hand
    float tension = 0;      // 0..1, the line snaps at 1
    float struggle = 0;     // 1 = the hooked fish is fighting, 0 = tired
    float reel = 0;         // > 0 = reeling in
    float side = -1;        // hooked fish left (< 0.5) / right (> 0.5), -1 = n/a
    float weight_lb = 0;    // > 0 while waiting = a fish has taken the bait
    float distance = 0;     // rod to hook, metres
    int cmd = 0;            // script bits: 2 fish lost, 512 nibble
    uint32_t fish = 0;      // hooked fish entity
};

template <typename T>
inline T clampv(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Jenkins one-at-a-time hash, lowercase - how RAGE names weapons, sounds, materials.
inline uint32_t joaat(const std::string& s) {
    uint32_t h = 0;
    for (unsigned char c : s) {
        if (c >= 'A' && c <= 'Z') c = char(c - 'A' + 'a');
        h += c;
        h += h << 10;
        h ^= h >> 6;
    }
    h += h << 3;
    h ^= h >> 11;
    h += h << 15;
    return h;
}

// Folder of the .asi (the game directory).
fs::path module_dir();
// <game>/DualSenseRDR2/
inline fs::path data_dir() { return module_dir() / "DualSenseRDR2"; }

// Small deterministic RNG (xorshift) - std::random is heavy for the audio thread.
struct Rng {
    uint64_t s;
    explicit Rng(uint64_t seed = 0x9E3779B97F4A7C15ull) : s(seed ? seed : 1) {}
    uint64_t next() { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return s; }
    float uniform() { return float(next() >> 40) / float(1ull << 24); }               // [0,1)
    float range(float a, float b) { return a + (b - a) * uniform(); }
    int below(int n) { return n > 0 ? int(next() % uint64_t(n)) : 0; }
    float gauss() { float u = std::max(1e-7f, uniform()), v = uniform(); return std::sqrt(-2 * std::log(u)) * std::cos(2 * kPi * v); }
};

}  // namespace dsr2
