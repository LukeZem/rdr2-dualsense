// DualSense adaptive trigger effect encoders (port of tools/trigger_lab/ds5/effects.py).
// Each returns the 11-byte trigger block of the output report. 10 zones: 0 = rest, 9 = full.
#pragma once

#include <array>
#include <cstdint>

namespace dsr2::fx {

using Block = std::array<uint8_t, 11>;
constexpr int kZones = 10;

enum Mode : uint8_t {
    OFF = 0x05, FEEDBACK = 0x21, BOW = 0x22, GALLOPING = 0x23, WEAPON = 0x25, VIBRATION = 0x26, MACHINE = 0x27,
};

inline Block off() { Block b{}; b[0] = OFF; return b; }

inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

inline Block multi_feedback(const std::array<int, kZones>& zones) {
    uint32_t active = 0, packed = 0;
    for (int i = 0; i < kZones; ++i) {
        int v = clampi(zones[i], 0, 8);
        if (v > 0) {
            active |= 1u << i;
            packed |= uint32_t((v - 1) & 7) << (3 * i);
        }
    }
    if (!active) return off();
    Block b{};
    b[0] = FEEDBACK;
    b[1] = uint8_t(active);
    b[2] = uint8_t(active >> 8);
    for (int i = 0; i < 4; ++i) b[3 + i] = uint8_t(packed >> (8 * i));
    return b;
}

inline Block feedback(int position, int strength) {
    std::array<int, kZones> z{};
    for (int i = clampi(position, 0, 9); i < kZones; ++i) z[i] = strength;
    return multi_feedback(z);
}

inline Block multi_vibration(int frequency, const std::array<int, kZones>& amps) {
    uint32_t active = 0, packed = 0;
    for (int i = 0; i < kZones; ++i) {
        int v = clampi(amps[i], 0, 8);
        if (v > 0) {
            active |= 1u << i;
            packed |= uint32_t((v - 1) & 7) << (3 * i);
        }
    }
    frequency = clampi(frequency, 0, 255);
    if (!active || !frequency) return off();
    Block b{};
    b[0] = VIBRATION;
    b[1] = uint8_t(active);
    b[2] = uint8_t(active >> 8);
    for (int i = 0; i < 4; ++i) b[3 + i] = uint8_t(packed >> (8 * i));
    b[9] = uint8_t(frequency);
    return b;
}

inline Block vibration(int position, int amplitude, int frequency) {
    std::array<int, kZones> z{};
    for (int i = clampi(position, 0, 9); i < kZones; ++i) z[i] = amplitude;
    return multi_vibration(frequency, z);
}

inline Block weapon(int start, int end, int strength) {
    start = clampi(start, 2, 7);
    end = clampi(end, start + 1, 8);
    strength = clampi(strength, 0, 8);
    if (!strength) return off();
    uint32_t zones = (1u << start) | (1u << end);
    Block b{};
    b[0] = WEAPON;
    b[1] = uint8_t(zones);
    b[2] = uint8_t(zones >> 8);
    b[3] = uint8_t(strength - 1);
    return b;
}

inline Block galloping(int start, int end, int first_foot, int second_foot, int frequency) {
    start = clampi(start, 0, 8);
    end = clampi(end, start + 1, 9);
    first_foot = clampi(first_foot, 0, 6);
    second_foot = clampi(second_foot, first_foot + 1, 7);
    frequency = clampi(frequency, 0, 255);
    if (!frequency) return off();
    uint32_t zones = (1u << start) | (1u << end);
    Block b{};
    b[0] = GALLOPING;
    b[1] = uint8_t(zones);
    b[2] = uint8_t(zones >> 8);
    b[3] = uint8_t((second_foot & 7) | ((first_foot & 7) << 3));
    b[4] = uint8_t(frequency);
    return b;
}

inline Block simple_weapon(int start, int end, int strength) {
    Block b{};
    b[0] = 0x02;
    b[1] = uint8_t(clampi(start, 0, 255));
    b[2] = uint8_t(clampi(end, 0, 255));
    b[3] = uint8_t(clampi(strength, 0, 255));
    return b;
}

// Per-zone strengths of a feedback block (for texture edits).
inline std::array<int, kZones> zones_of(const Block& b) {
    std::array<int, kZones> z{};
    if (b[0] != FEEDBACK && b[0] != VIBRATION) return z;
    uint32_t active = b[1] | (uint32_t(b[2]) << 8);
    uint32_t packed = b[3] | (uint32_t(b[4]) << 8) | (uint32_t(b[5]) << 16) | (uint32_t(b[6]) << 24);
    for (int i = 0; i < kZones; ++i)
        if (active & (1u << i)) z[i] = int((packed >> (3 * i)) & 7) + 1;
    return z;
}

}  // namespace dsr2::fx
