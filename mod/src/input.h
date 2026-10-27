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
    float rumble_high() const { return rumble_high_.load(); }

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
    WORD touch_click_ = XINPUT_GAMEPAD_BACK, swipe_[4] = {0, 0, 0, 0}, two_finger_ = 0;
    // touch tracking
    bool touching_ = false;
    int touch_id_ = -1, sx_ = 0, sy_ = 0, lx_ = 0, ly_ = 0;
    double touch_t_ = 0;
    bool two_ = false;
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
    // real XInput for passthrough when the DualSense is absent
    DWORD (WINAPI* real_get_)(DWORD, XINPUT_STATE*) = nullptr;
    DWORD (WINAPI* real_set_)(DWORD, XINPUT_VIBRATION*) = nullptr;
};

Input& input();
WORD xbutton_from_name(const std::string& name);

}  // namespace dsr2
