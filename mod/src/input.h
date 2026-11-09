// What the game reads as its gamepad: the DualSense mapped to XInput (via a hook on
// xinput9_1_0!XInputGetState), the shot moment decided by the trigger engine, injected presses
// (whistle, touchpad gestures), the game's rumble captured from XInputSetState, gyro integration.
#pragma once

#include "common.h"
#include "ds5.h"

#include <xinput.h>

namespace dsr2 {

class Input {
public:
    bool install_hook();                         // patch xinput9_1_0 in the game process
    // controller thread: publish the state the game will read
    void publish(const InputState& s, int game_rt, bool connected);
    void inject(WORD xbutton, double seconds);   // e.g. XINPUT_GAMEPAD_DPAD_UP for the whistle
    void hold_lt(double seconds);                // hold L2 fully for `seconds` (0 = release now)
    void probe_lt(int value);                    // the game sees this L2 value (0-255; -1 = the real one)
    void configure();                            // read touchpad mapping from the ini
    // gestures + gyro, called by the controller thread for each fresh report
    void track_touch(const InputState& s);
    void track_gyro(const InputState& s, bool aiming_hint);

    // game rumble (XInputSetState) 0..1
    float rumble_low() const { return rumble_low_.load(); }
    double rt_press_read_t() const { return rt_press_read_t_.load(); }   // when the game last read R2 pressed
    float rumble_high() const { return rumble_high_.load(); }

    // keyboard key for other mods (e.g. Realistic Ballistics zeroing): pressed now, released after `seconds`
    void pulse_key(WORD vk, double seconds);

    // hook targets
    DWORD get_state(DWORD idx, XINPUT_STATE* out);
    DWORD set_state(DWORD idx, XINPUT_VIBRATION* v);

private:
    std::mutex mu_;
    XINPUT_STATE state_{};
    bool connected_ = false;
    DWORD packet_ = 0;
    struct Injection { WORD button; double until; };
    std::vector<Injection> injections_;
    double lt_until_ = 0;
    int lt_probe_ = -1;
    std::atomic<float> rumble_low_{0}, rumble_high_{0};
    std::atomic<double> rt_press_read_t_{0};
    WORD touch_click_ = XINPUT_GAMEPAD_BACK, swipe_[4] = {0, 0, 0, 0}, two_finger_ = 0;
    // touch tracking
    bool touching_ = false;
    int touch_id_ = -1, sx_ = 0, sy_ = 0, lx_ = 0, ly_ = 0;
    double touch_t_ = 0;
    bool two_ = false;
    bool clicked_ = false;                     // the touchpad was clicked during this touch
    // per-half (0 left, 1 right) up / down swipes; set = overrides SwipeUp / SwipeDown on that half
    WORD half_swipe_[2][2] = {{0, 0}, {0, 0}}, half_swipe_vk_[2][2] = {{0, 0}, {0, 0}};
    bool half_set_[2][2] = {{false, false}, {false, false}};
    // gyro
    float bias_[3] = {0, 0, 0};
    float still_time_ = 0, smooth_yaw_ = 0, smooth_pitch_ = 0;
    float aim_fade_ = 0;
    double gyro_log_t_ = 0, aim_since_ = -1;
    std::atomic<float> gyro_rx_{0}, gyro_ry_{0};   // gyro, added to the right stick the game reads (-1..1)                       // 0 -> 1 over the first moments of aiming (no jump)
    static constexpr int kSmoothN = 16;        // ~64 ms of history for the soft smoothing
    float hist_yaw_[kSmoothN] = {}, hist_pitch_[kSmoothN] = {};
    int hist_i_ = 0;
    double gyro_t_ = 0;
    bool hide_other_ = true;
    // [Keys]: while the hold button is held, D-pad presses become keyboard keys (and the game never sees them)
    std::mutex keys_mu_;
    uint32_t chord_hold_ = 0;                  // Btn mask of the hold button (0 = off)
    int chord_hold_trigger_ = 0;               // 1 = L2, 2 = R2 (analog, past chord_threshold_)
    int chord_threshold_ = 64;
    WORD chord_vk_[4] = {0, 0, 0, 0};          // D-pad up, down, left, right
    double repeat_delay_ = 0.4, repeat_period_ = 0;
    int tap_mode_ = 1;                         // 0 press, 1 double tap, 2 tap = game / hold = key, 3 tap = key / hold = game
    double tap_time_ = 0.35;                   // Mode=tap: released within this = the key
    double hold_time_ = 0.3;                   // Mode=hold: press longer than this = the key
    double double_tap_ = 0.25;                 // Mode=doubletap: seconds between the two taps
    bool pass_first_tap_ = false;              // 1 = the first tap reaches the game at once
    bool tap_pending_[4] = {};
    double tap_until_[4] = {};
    uint32_t chord_active_ = 0;                // D-pad bits currently sending their key
    std::atomic<uint32_t> chord_hidden_{0};    // D-pad bits hidden from the game until released
    uint32_t prev_dpad_ = 0;
    bool chord_key_down_[4] = {};
    double chord_next_[4] = {};
    WORD click_vk_ = 0, swipe_vk_[4] = {0, 0, 0, 0}, two_finger_vk_ = 0;   // touchpad KEY: bindings
    bool click_key_down_ = false;
    struct Pulse { WORD vk; double up_at; };
    std::vector<Pulse> pulses_;
    bool key_hook_mode_ = false;               // Method=hook: keys only exist inside the game process
    void update_keys(const InputState& s, bool connected);
    void release_all_keys();                   // keys_mu_ held
    void key(WORD vk, bool down);
    // real XInput for passthrough when the DualSense is absent
    DWORD (WINAPI* real_get_)(DWORD, XINPUT_STATE*) = nullptr;
    DWORD (WINAPI* real_set_)(DWORD, XINPUT_VIBRATION*) = nullptr;
};

Input& input();
WORD xbutton_from_name(const std::string& name);
WORD vk_from_name(const std::string& name);    // T, F5, NUMPAD1, VK_T, 0x54, 84 ... (0 = none)

}  // namespace dsr2
