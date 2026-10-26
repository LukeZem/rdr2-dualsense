#include "input.h"

#include "config.h"
#include "log.h"
#include "world.h"

namespace dsr2 {

Input& input() {
    static Input i;
    return i;
}

static DWORD WINAPI hk_get_state(DWORD idx, XINPUT_STATE* s) { return input().get_state(idx, s); }
static DWORD WINAPI hk_set_state(DWORD idx, XINPUT_VIBRATION* v) { return input().set_state(idx, v); }

// Executable page within +-2 GB of `target` for a 14-byte absolute jump.
static void* alloc_near(void* target) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    uintptr_t t = uintptr_t(target), gran = si.dwAllocationGranularity;
    for (uintptr_t d = gran; d < 0x70000000; d += gran) {
        for (uintptr_t cand : {t - d, t + d}) {
            cand &= ~(gran - 1);
            void* p = VirtualAlloc(reinterpret_cast<void*>(cand), 4096, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
            if (p) return p;
        }
    }
    return nullptr;
}

// Redirect `target` to `detour` with a 5-byte relative jump to a relay. The original is never called
// (passthrough uses xinput1_4, a different module), so no trampoline is needed.
static bool hook(void* target, void* detour) {
    if (!target) return false;
    auto* relay = static_cast<uint8_t*>(alloc_near(target));
    if (!relay) return false;
    relay[0] = 0xFF; relay[1] = 0x25;
    std::memset(relay + 2, 0, 4);
    std::memcpy(relay + 6, &detour, 8);
    DWORD old;
    if (!VirtualProtect(target, 5, PAGE_EXECUTE_READWRITE, &old)) return false;
    auto* t = static_cast<uint8_t*>(target);
    int32_t rel = int32_t(intptr_t(relay) - (intptr_t(t) + 5));
    t[0] = 0xE9;
    std::memcpy(t + 1, &rel, 4);
    VirtualProtect(target, 5, old, &old);
    FlushInstructionCache(GetCurrentProcess(), target, 5);
    return true;
}

bool Input::install_hook() {
    HMODULE real = LoadLibraryW(L"xinput1_4.dll");
    if (real) {
        real_get_ = reinterpret_cast<decltype(real_get_)>(GetProcAddress(real, "XInputGetState"));
        real_set_ = reinterpret_cast<decltype(real_set_)>(GetProcAddress(real, "XInputSetState"));
    }
    HMODULE x = GetModuleHandleW(L"xinput9_1_0.dll");
    if (!x) x = LoadLibraryW(L"xinput9_1_0.dll");
    if (!x) {
        LOGE("xinput9_1_0.dll not loaded - cannot feed the game");
        return false;
    }
    bool a = hook(reinterpret_cast<void*>(GetProcAddress(x, "XInputGetState")), reinterpret_cast<void*>(&hk_get_state));
    bool b = hook(reinterpret_cast<void*>(GetProcAddress(x, "XInputSetState")), reinterpret_cast<void*>(&hk_set_state));
    LOGI("XInput hook: GetState %s, SetState %s", a ? "ok" : "FAILED", b ? "ok" : "FAILED");
    return a && b;
}

WORD xbutton_from_name(const std::string& n0) {
    std::string n;
    for (char c : n0) n += char(toupper((unsigned char)c));
    static const std::pair<const char*, WORD> map[] = {
        {"A", XINPUT_GAMEPAD_A}, {"B", XINPUT_GAMEPAD_B}, {"X", XINPUT_GAMEPAD_X}, {"Y", XINPUT_GAMEPAD_Y},
        {"LB", XINPUT_GAMEPAD_LEFT_SHOULDER}, {"RB", XINPUT_GAMEPAD_RIGHT_SHOULDER}, {"BACK", XINPUT_GAMEPAD_BACK},
        {"START", XINPUT_GAMEPAD_START}, {"LS", XINPUT_GAMEPAD_LEFT_THUMB}, {"RS", XINPUT_GAMEPAD_RIGHT_THUMB},
        {"UP", XINPUT_GAMEPAD_DPAD_UP}, {"DOWN", XINPUT_GAMEPAD_DPAD_DOWN}, {"LEFT", XINPUT_GAMEPAD_DPAD_LEFT},
        {"RIGHT", XINPUT_GAMEPAD_DPAD_RIGHT},
    };
    for (auto& [k, v] : map) if (n == k) return v;
    return 0;
}

void Input::configure() {
    Config& c = config();
    touch_click_ = xbutton_from_name(c.str("Touchpad", "Click", "BACK"));
    swipe_[0] = xbutton_from_name(c.str("Touchpad", "SwipeUp", ""));
    swipe_[1] = xbutton_from_name(c.str("Touchpad", "SwipeDown", ""));
    swipe_[2] = xbutton_from_name(c.str("Touchpad", "SwipeLeft", ""));
    swipe_[3] = xbutton_from_name(c.str("Touchpad", "SwipeRight", ""));
    two_finger_ = xbutton_from_name(c.str("Touchpad", "TwoFingerTap", ""));
    hide_other_ = c.flag("General", "HideOtherPads", true);
}

void Input::inject(WORD button, double seconds) {
    if (!button) return;
    std::lock_guard<std::mutex> l(mu_);
    injections_.push_back({button, now_s() + seconds});
}

void Input::hold_lt(double seconds) {
    std::lock_guard<std::mutex> l(mu_);
    lt_until_ = seconds > 0 ? now_s() + seconds : 0;
}

static SHORT stick(int v, bool invert) {
    int s = (v - 128) * 256;
    if (invert) s = -s;
    return SHORT(clampv(s, -32768, 32767));
}

void Input::publish(const InputState& s, int game_rt, bool connected) {
    XINPUT_GAMEPAD g{};
    auto map = [&](uint32_t m, WORD x) { if (s.buttons & m) g.wButtons |= x; };
    map(CROSS, XINPUT_GAMEPAD_A);
    map(CIRCLE, XINPUT_GAMEPAD_B);
    map(SQUARE, XINPUT_GAMEPAD_X);
    map(TRIANGLE, XINPUT_GAMEPAD_Y);
    map(L1, XINPUT_GAMEPAD_LEFT_SHOULDER);
    map(R1, XINPUT_GAMEPAD_RIGHT_SHOULDER);
    map(CREATE, XINPUT_GAMEPAD_BACK);
    map(OPTIONS, XINPUT_GAMEPAD_START);
    map(L3, XINPUT_GAMEPAD_LEFT_THUMB);
    map(R3, XINPUT_GAMEPAD_RIGHT_THUMB);
    map(DPAD_UP, XINPUT_GAMEPAD_DPAD_UP);
    map(DPAD_DOWN, XINPUT_GAMEPAD_DPAD_DOWN);
    map(DPAD_LEFT, XINPUT_GAMEPAD_DPAD_LEFT);
    map(DPAD_RIGHT, XINPUT_GAMEPAD_DPAD_RIGHT);
    if (s.buttons & TOUCHPAD) g.wButtons |= touch_click_;
    g.bLeftTrigger = BYTE(s.l2);
    g.bRightTrigger = BYTE(game_rt >= 0 ? game_rt : s.r2);
    g.sThumbLX = stick(s.lx, false);
    g.sThumbLY = stick(s.ly, true);
    g.sThumbRX = stick(s.rx, false);
    g.sThumbRY = stick(s.ry, true);
    // gyro rides on the right stick: it adds to your stick instead of fighting it (and the game ignores
    // scripted camera pitch while aiming)
    if (float gx = gyro_rx_.load(); gx != 0)
        g.sThumbRX = SHORT(clampv(int(g.sThumbRX) + int(gx * 32767.0f), -32768, 32767));
    if (float gy = gyro_ry_.load(); gy != 0)
        g.sThumbRY = SHORT(clampv(int(g.sThumbRY) + int(gy * 32767.0f), -32768, 32767));
    double t = now_s();
    std::lock_guard<std::mutex> l(mu_);
    for (auto it = injections_.begin(); it != injections_.end();) {
        if (t < it->until) { g.wButtons |= it->button; ++it; }
        else it = injections_.erase(it);
    }
    if (t < lt_until_) g.bLeftTrigger = 255;          // the mod is holding L2 (focus for a greeting)
    connected_ = connected;
    if (std::memcmp(&g, &state_.Gamepad, sizeof g) != 0) {
        state_.Gamepad = g;
        state_.dwPacketNumber = ++packet_;
    }
}

DWORD Input::get_state(DWORD idx, XINPUT_STATE* out) {
    if (!out) return ERROR_BAD_ARGUMENTS;
    {
        std::lock_guard<std::mutex> l(mu_);
        if (connected_) {
            if (idx != 0) {
                if (hide_other_) return ERROR_DEVICE_NOT_CONNECTED;
                return real_get_ ? real_get_(idx, out) : ERROR_DEVICE_NOT_CONNECTED;
            }
            *out = state_;
            return ERROR_SUCCESS;
        }
    }
    return real_get_ ? real_get_(idx, out) : ERROR_DEVICE_NOT_CONNECTED;   // no DualSense: other pads work
}

DWORD Input::set_state(DWORD idx, XINPUT_VIBRATION* v) {
    if (!v) return ERROR_BAD_ARGUMENTS;
    bool ours;
    {
        std::lock_guard<std::mutex> l(mu_);
        ours = connected_;
    }
    if (ours) {
        if (idx == 0) {
            rumble_low_ = v->wLeftMotorSpeed / 65535.0f;
            rumble_high_ = v->wRightMotorSpeed / 65535.0f;
            return ERROR_SUCCESS;
        }
        if (hide_other_) return ERROR_DEVICE_NOT_CONNECTED;
    }
    return real_set_ ? real_set_(idx, v) : ERROR_DEVICE_NOT_CONNECTED;
}

// Swipes (one finger, quick, long enough) and a two-finger tap become button presses.
void Input::track_touch(const InputState& s) {
    const TouchPoint& a = s.touch[0];
    bool both = s.touch[0].active && s.touch[1].active;
    if (a.active && !touching_) {
        touching_ = true;
        touch_id_ = a.id;
        sx_ = lx_ = a.x;
        sy_ = ly_ = a.y;
        touch_t_ = s.t;
        two_ = false;
    }
    if (touching_ && a.active) {
        lx_ = a.x;
        ly_ = a.y;
        if (both) two_ = true;
    }
    if (touching_ && !a.active) {
        touching_ = false;
        double dt = s.t - touch_t_;
        int dx = lx_ - sx_, dy = ly_ - sy_;
        if (two_ && dt < 0.35 && std::abs(dx) < 150 && std::abs(dy) < 150) {
            inject(two_finger_, 0.12);
        } else if (dt < 0.5) {
            if (std::abs(dy) > 300 && std::abs(dy) > std::abs(dx)) inject(swipe_[dy < 0 ? 0 : 1], 0.12);
            else if (std::abs(dx) > 450) inject(swipe_[dx < 0 ? 2 : 3], 0.12);
        }
    }
}

// Gyro aim: a fine-tuning aid on top of the right stick, only while free-aiming (never during the game's
// lock-on). Degrees the controller turns become degrees the camera turns (times Sensitivity).
//  - bias (drift) learned while the controller rests
//  - soft tiered smoothing: tiny movements (hand tremor) are averaged, deliberate ones pass straight through,
//    so there is no lag on real corrections and no jitter at rest
//  - fades in over ~0.2 s when aiming starts, so the view never jumps
void Input::track_gyro(const InputState& s, bool aiming) {
    Config& c = config();
    std::string mode = c.str("Gyro", "Mode", "off");
    world().gyro_enabled = mode != "off";
    world().gyro_wants_always = mode == "always";
    double dt = gyro_t_ > 0 ? s.t - gyro_t_ : 0;
    gyro_t_ = s.t;
    if (dt <= 0 || dt > 0.05) return;
    float r[3];
    float mag = 0;
    for (int i = 0; i < 3; ++i) {
        r[i] = float(s.gyro[i]) / 16.4f;           // deg/s
        mag += std::fabs(r[i] - bias_[i]);
    }
    if (mag < 4.0f) {                              // resting: slowly learn the drift
        still_time_ += float(dt);
        if (still_time_ > 0.5f)
            for (int i = 0; i < 3; ++i) bias_[i] += (r[i] - bias_[i]) * 0.02f;
    } else {
        still_time_ = 0;
    }
    bool active = mode == "always" || (mode != "off" && aiming);
    if (!active) {
        aim_since_ = -1;
        aim_fade_ = 0;
        gyro_rx_ = 0;
        gyro_ry_ = 0;
        smooth_yaw_ = smooth_pitch_ = 0;
        for (int i = 0; i < kSmoothN; ++i) hist_yaw_[i] = hist_pitch_[i] = 0;
        return;
    }
    // the game blends to its aim camera for a moment after L2: corrections then would land on the wrong camera
    // (the aim jumped, e.g. to the ground) - wait until it has settled, then fade in
    if (aim_since_ < 0) aim_since_ = s.t;
    if (s.t - aim_since_ < 0.35) return;
    aim_fade_ = std::min(1.0f, aim_fade_ + float(dt) / 0.2f);

    float yaw = r[1] - bias_[1], pitch = r[0] - bias_[0];
    // soft tiered smoothing (threshold in deg/s): below half of it fully smoothed, above it raw
    float th = std::max(0.1f, c.num("Gyro", "SmoothThreshold", 6.0f));
    auto split = [&](float v, float* hist, float& out) {
        float a = std::fabs(v);
        float direct = clampv((a - th * 0.5f) / (th * 0.5f), 0.0f, 1.0f);
        hist[hist_i_] = v * (1 - direct);
        float avg = 0;
        for (int i = 0; i < kSmoothN; ++i) avg += hist[i];
        out = v * direct + avg / kSmoothN;
    };
    float y = 0, pch = 0;
    split(yaw, hist_yaw_, y);
    split(pitch, hist_pitch_, pch);
    hist_i_ = (hist_i_ + 1) % kSmoothN;
    if (std::fabs(y) < 0.25f) y = 0;               // only true stillness, not a dead zone you can feel
    if (std::fabs(pch) < 0.25f) pch = 0;

    float sens = c.num("Gyro", "Sensitivity", 1.0f) * aim_fade_;
    float vert = c.num("Gyro", "VerticalRatio", 0.75f);
    // turning speed (deg/s) -> right-stick deflection, past the game's stick dead zone
    float full = std::max(10.0f, c.num("Gyro", "StickRate", 90.0f));      // deg/s the game turns at full stick
    float dz = clampv(c.num("Gyro", "StickDeadzone", 0.2f), 0.0f, 0.5f);
    auto to_stick = [&](float rate) {
        float v = std::min(1.0f, std::fabs(rate) / full);
        return v < 1e-3f ? 0.0f : std::copysign(dz + (1 - dz) * v, rate);
    };
    float ix = c.flag("Gyro", "InvertX", false) ? -1.f : 1.f, iy = c.flag("Gyro", "InvertY", false) ? -1.f : 1.f;
    bool stick_out = c.str("Gyro", "Output", "camera") == "stick";
    // the right stick in use: it drives the camera on its own, the gyro steps aside
    bool stick_busy = std::abs(int(s.rx) - 128) > 20 || std::abs(int(s.ry) - 128) > 20;
    world().gyro_stick_busy = stick_busy;
    if (stick_out) {
        // yaw: turning the controller left (positive yaw) turns the camera left = stick left (negative X)
        gyro_rx_ = to_stick(-y * sens * ix);
        gyro_ry_ = to_stick(pch * sens * vert * iy);
    } else {
        // camera: degrees turned = degrees the camera turns, instantly (no stick acceleration)
        gyro_rx_ = 0;
        gyro_ry_ = 0;
        if (!stick_busy) world().add_gyro(y * float(dt) * sens * ix, pch * float(dt) * sens * vert * iy);
    }
    if (s.t - gyro_log_t_ > 0.5) {
        gyro_log_t_ = s.t;
        LOGD("gyro: raw %+.1f %+.1f %+.1f deg/s, bias %+.1f %+.1f %+.1f -> yaw %+.1f pitch %+.1f -> stick x %+.2f y %+.2f",
             r[0], r[1], r[2], bias_[0], bias_[1], bias_[2], y, pch, gyro_rx_.load(), gyro_ry_.load());
    }
}

}  // namespace dsr2
