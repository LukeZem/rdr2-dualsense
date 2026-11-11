#include "input.h"

#include "config.h"
#include "log.h"
#include "world.h"

#include <cctype>
#include <cstdlib>

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

// ---- keyboard keys for other mods -------------------------------------------------------------------

static std::string upper_trim(const std::string& s0) {
    std::string s;
    for (char c : s0)
        if (!isspace((unsigned char)c)) s += char(toupper((unsigned char)c));
    return s;
}

WORD vk_from_name(const std::string& n0) {
    std::string n = upper_trim(n0);
    if (n.rfind("VK_", 0) == 0) n = n.substr(3);
    if (n.empty() || n == "OFF") return 0;
    if (n.size() == 1 && ((n[0] >= 'A' && n[0] <= 'Z') || (n[0] >= '0' && n[0] <= '9'))) return WORD(n[0]);
    if (n.size() == 1) {                           // a symbol: the key it is printed on (US layout names)
        switch (n[0]) {
        case '~': case '`': return VK_OEM_3;
        case '-': case '_': return VK_OEM_MINUS;
        case '=': case '+': return VK_OEM_PLUS;
        case '[': case '{': return VK_OEM_4;
        case ']': case '}': return VK_OEM_6;
        case '\\': case '|': return VK_OEM_5;
        case ';': case ':': return VK_OEM_1;
        case '\'': case '"': return VK_OEM_7;
        case ',': case '<': return VK_OEM_COMMA;
        case '.': case '>': return VK_OEM_PERIOD;
        case '/': case '?': return VK_OEM_2;
        default: break;
        }
        SHORT r = VkKeyScanW(wchar_t((unsigned char)n[0]));   // anything else: ask the keyboard layout
        if (r != -1) return WORD(LOBYTE(r));
    }
    if (n.size() > 2 && n[0] == '0' && n[1] == 'X') {
        unsigned long v = strtoul(n.c_str() + 2, nullptr, 16);
        return v > 0 && v < 256 ? WORD(v) : 0;
    }
    if (std::all_of(n.begin(), n.end(), [](char c) { return c >= '0' && c <= '9'; })) {
        unsigned long v = strtoul(n.c_str(), nullptr, 10);
        return v > 0 && v < 256 ? WORD(v) : 0;
    }
    if (n[0] == 'F' && n.size() <= 3) {
        int f = atoi(n.c_str() + 1);
        if (f >= 1 && f <= 24) return WORD(VK_F1 + f - 1);
    }
    if (n.rfind("NUMPAD", 0) == 0 && n.size() == 7 && n[6] >= '0' && n[6] <= '9') return WORD(VK_NUMPAD0 + n[6] - '0');
    static const std::pair<const char*, WORD> map[] = {
        {"SPACE", VK_SPACE}, {"ENTER", VK_RETURN}, {"RETURN", VK_RETURN}, {"TAB", VK_TAB}, {"ESC", VK_ESCAPE},
        {"ESCAPE", VK_ESCAPE}, {"BACKSPACE", VK_BACK}, {"BACK", VK_BACK}, {"SHIFT", VK_SHIFT}, {"LSHIFT", VK_LSHIFT},
        {"RSHIFT", VK_RSHIFT}, {"CTRL", VK_CONTROL}, {"CONTROL", VK_CONTROL}, {"LCTRL", VK_LCONTROL},
        {"LCONTROL", VK_LCONTROL}, {"RCTRL", VK_RCONTROL}, {"RCONTROL", VK_RCONTROL}, {"ALT", VK_MENU},
        {"MENU", VK_MENU}, {"LALT", VK_LMENU}, {"RALT", VK_RMENU}, {"UP", VK_UP}, {"DOWN", VK_DOWN},
        {"LEFT", VK_LEFT}, {"RIGHT", VK_RIGHT}, {"INSERT", VK_INSERT}, {"DELETE", VK_DELETE}, {"HOME", VK_HOME},
        {"END", VK_END}, {"PAGEUP", VK_PRIOR}, {"PRIOR", VK_PRIOR}, {"PAGEDOWN", VK_NEXT}, {"NEXT", VK_NEXT},
        {"CAPSLOCK", VK_CAPITAL}, {"MULTIPLY", VK_MULTIPLY}, {"ADD", VK_ADD}, {"SUBTRACT", VK_SUBTRACT},
        {"DECIMAL", VK_DECIMAL}, {"DIVIDE", VK_DIVIDE}, {"MINUS", VK_OEM_MINUS}, {"PLUS", VK_OEM_PLUS},
        {"NUMPADPLUS", VK_ADD}, {"NUMPAD+", VK_ADD}, {"NUMPADADD", VK_ADD}, {"NUMPADMINUS", VK_SUBTRACT},
        {"NUMPAD-", VK_SUBTRACT}, {"NUMPADSUBTRACT", VK_SUBTRACT}, {"NUMPADMULTIPLY", VK_MULTIPLY},
        {"NUMPAD*", VK_MULTIPLY}, {"NUMPADDIVIDE", VK_DIVIDE}, {"NUMPAD/", VK_DIVIDE},
        {"COMMA", VK_OEM_COMMA}, {"PERIOD", VK_OEM_PERIOD}, {"TILDE", VK_OEM_3}, {"GRAVE", VK_OEM_3},
        {"BACKTICK", VK_OEM_3}, {"SEMICOLON", VK_OEM_1}, {"QUOTE", VK_OEM_7}, {"SLASH", VK_OEM_2},
        {"BACKSLASH", VK_OEM_5}, {"LBRACKET", VK_OEM_4}, {"RBRACKET", VK_OEM_6}, {"EQUALS", VK_OEM_PLUS},
        {"PAUSE", VK_PAUSE}, {"SCROLLLOCK", VK_SCROLL}, {"NUMLOCK", VK_NUMLOCK}, {"PRINTSCREEN", VK_SNAPSHOT}, {"LBUTTON", VK_LBUTTON}, {"RBUTTON", VK_RBUTTON},
        {"MBUTTON", VK_MBUTTON}, {"XBUTTON1", VK_XBUTTON1}, {"XBUTTON2", VK_XBUTTON2},
    };
    for (auto& [k, v] : map) if (n == k) return v;
    return 0;
}

// Touchpad values: a game button (BACK, UP ...) or KEY:<key> for a keyboard key.
static bool parse_touch(const std::string& v, WORD& xbutton, WORD& vk) {
    std::string u = upper_trim(v);
    xbutton = 0;
    vk = 0;
    if (u.rfind("KEY:", 0) == 0) vk = vk_from_name(u.substr(4));
    else xbutton = xbutton_from_name(u);
    return xbutton || vk;
}

// Method=hook: the keys exist only for code inside the game process that asks GetAsyncKeyState /
// GetKeyState (most script mods). No keyboard event reaches Windows, so the game never switches its
// prompts to keyboard & mouse. The real state comes from win32u (what user32's versions call).
static std::atomic<uint8_t> g_vdown[256];
static std::atomic<uint8_t> g_vpressed[256];
static SHORT (WINAPI* g_real_async)(int) = nullptr;
static SHORT (WINAPI* g_real_keystate)(int) = nullptr;

static SHORT WINAPI hk_async_key(int vk) {
    SHORT r = g_real_async ? g_real_async(vk) : 0;
    if (vk > 0 && vk < 256) {
        if (g_vdown[vk].load()) r = SHORT(r | 0x8000);
        if (g_vpressed[vk].exchange(0)) r = SHORT(r | 1);
    }
    return r;
}

static SHORT WINAPI hk_key_state(int vk) {
    SHORT r = g_real_keystate ? g_real_keystate(vk) : 0;
    if (vk > 0 && vk < 256 && g_vdown[vk].load()) r = SHORT(r | 0x8000);
    return r;
}

static bool install_key_hooks() {
    static int done = 0;                      // 0 = not tried, 1 = ok, -1 = failed
    if (done) return done > 0;
    HMODULE w32u = LoadLibraryW(L"win32u.dll");
    HMODULE u32 = LoadLibraryW(L"user32.dll");
    if (w32u) {
        g_real_async = reinterpret_cast<decltype(g_real_async)>(GetProcAddress(w32u, "NtUserGetAsyncKeyState"));
        g_real_keystate = reinterpret_cast<decltype(g_real_keystate)>(GetProcAddress(w32u, "NtUserGetKeyState"));
    }
    bool ok = u32 && g_real_async && g_real_keystate &&
              hook(reinterpret_cast<void*>(GetProcAddress(u32, "GetAsyncKeyState")), reinterpret_cast<void*>(&hk_async_key)) &&
              hook(reinterpret_cast<void*>(GetProcAddress(u32, "GetKeyState")), reinterpret_cast<void*>(&hk_key_state));
    LOGI("keys: in-process key hook %s", ok ? "ok" : "FAILED - using real key presses instead");
    done = ok ? 1 : -1;
    return ok;
}

static bool game_in_front() {
    DWORD pid = 0;
    GetWindowThreadProcessId(GetForegroundWindow(), &pid);
    return pid == GetCurrentProcessId();
}

static bool is_extended(WORD vk) {
    switch (vk) {
    case VK_UP: case VK_DOWN: case VK_LEFT: case VK_RIGHT: case VK_INSERT: case VK_DELETE: case VK_HOME:
    case VK_END: case VK_PRIOR: case VK_NEXT: case VK_DIVIDE: case VK_RCONTROL: case VK_RMENU: return true;
    default: return false;
    }
}

void Input::key(WORD vk, bool down) {
    if (!vk) return;
    if (key_hook_mode_) {
        g_vdown[vk] = down ? 1 : 0;
        if (down) g_vpressed[vk] = 1;
        return;
    }
    if (down && !game_in_front()) return;     // alt-tabbed: never type into another program
    INPUT in{};
    if (vk == VK_LBUTTON || vk == VK_RBUTTON || vk == VK_MBUTTON || vk == VK_XBUTTON1 || vk == VK_XBUTTON2) {
        in.type = INPUT_MOUSE;
        if (vk == VK_LBUTTON) in.mi.dwFlags = down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
        else if (vk == VK_RBUTTON) in.mi.dwFlags = down ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_RIGHTUP;
        else if (vk == VK_MBUTTON) in.mi.dwFlags = down ? MOUSEEVENTF_MIDDLEDOWN : MOUSEEVENTF_MIDDLEUP;
        else {
            in.mi.dwFlags = down ? MOUSEEVENTF_XDOWN : MOUSEEVENTF_XUP;
            in.mi.mouseData = vk == VK_XBUTTON1 ? XBUTTON1 : XBUTTON2;
        }
    } else {
        in.type = INPUT_KEYBOARD;
        in.ki.wVk = vk;
        in.ki.wScan = WORD(MapVirtualKeyW(vk, MAPVK_VK_TO_VSC));
        in.ki.dwFlags = (down ? 0 : KEYEVENTF_KEYUP) | (is_extended(vk) ? KEYEVENTF_EXTENDEDKEY : 0);
    }
    SendInput(1, &in, sizeof in);
}

void Input::release_all_keys() {
    for (int i = 0; i < 4; ++i)
        if (chord_key_down_[i]) { key(chord_vk_[i], false); chord_key_down_[i] = false; }
    chord_active_ = 0;
    cstate_ = CornerState::idle;
    for (auto& p : pulses_) key(p.vk, false);
    pulses_.clear();
}

void Input::pulse_key(WORD vk, double seconds) {
    if (!vk) return;
    std::lock_guard<std::mutex> l(keys_mu_);
    key(vk, true);
    pulses_.push_back({vk, now_s() + seconds});
}

// Touchpad corners (full clicks, not touches). The quarter the finger is in at the first click picks the corner.
// Exactly one of the three fires per gesture:
//   click               = Click key, DoubleClickWindow seconds after you let go (if no second click came)
//   click, click        = DoubleClick key, when the second click is let go before HoldTime
//   click, click (held) = DoubleClickHold key, once the second click has been held for HoldTime
void Input::update_corners(const InputState& s, double t) {
    bool click = (s.buttons & TOUCHPAD) != 0;
    bool pressed = click && !cprev_click_, released = !click && cprev_click_;
    cprev_click_ = click;
    auto fire = [&](WORD vk) {
        if (!vk) return;
        key(vk, true);
        pulses_.push_back({vk, t + 0.1});
    };
    switch (cstate_) {
    case CornerState::idle:
        if (pressed) {
            const TouchPoint& p = s.touch[0].active ? s.touch[0] : s.touch[1];
            if (!p.active) break;                          // a click with no finger seen: ignore
            ccorner_ = (p.y >= 540 ? 2 : 0) + (p.x >= 960 ? 1 : 0);
            cstate_ = CornerState::press1;
        }
        break;
    case CornerState::press1:                              // first click down
        if (released) { ct0_ = t; cstate_ = CornerState::wait; }
        break;
    case CornerState::wait:                                // first click let go: a second one?
        if (pressed) { ct0_ = t; cstate_ = CornerState::press2; }
        else if (t - ct0_ >= corner_window_) { fire(corner_vk_[ccorner_][0]); cstate_ = CornerState::idle; }
        break;
    case CornerState::press2:                              // second click down
        if (released) { fire(corner_vk_[ccorner_][1]); cstate_ = CornerState::idle; }
        else if (t - ct0_ >= corner_hold_) { fire(corner_vk_[ccorner_][2]); cstate_ = CornerState::done; }
        break;
    case CornerState::done:                                // held double click already fired: wait for let go
        if (!click) cstate_ = CornerState::idle;
        break;
    }
}

// Every controller tick: the hold button + D-pad chord, touchpad click as a held key, pulse releases.
void Input::update_keys(const InputState& s, bool connected) {
    static const uint32_t dbits[4] = {DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT};
    const uint32_t all = DPAD_UP | DPAD_DOWN | DPAD_LEFT | DPAD_RIGHT;
    double t = s.t > 0 ? s.t : now_s();
    std::lock_guard<std::mutex> l(keys_mu_);
    if (!connected) {
        release_all_keys();
        chord_hidden_ = 0;
        prev_dpad_ = 0;
        return;
    }
    bool hold = chord_hold_trigger_ == 1 ? s.l2 >= chord_threshold_
              : chord_hold_trigger_ == 2 ? s.r2 >= chord_threshold_
              : chord_hold_ != 0 && (s.buttons & chord_hold_) != 0;
    static const WORD xdpad[4] = {XINPUT_GAMEPAD_DPAD_UP, XINPUT_GAMEPAD_DPAD_DOWN, XINPUT_GAMEPAD_DPAD_LEFT,
                                  XINPUT_GAMEPAD_DPAD_RIGHT};
    uint32_t hidden = chord_hidden_.load();
    for (int i = 0; i < 4; ++i) {
        uint32_t bit = dbits[i];
        bool now = (s.buttons & bit) != 0;
        bool fresh_press = now && !(prev_dpad_ & bit);    // a D-pad already held before the chord stays the game's
        bool want_key = false;
        if (tap_mode_ == 0) {
            want_key = hold && chord_vk_[i] && fresh_press;   // single press sends the key
        } else if (tap_mode_ == 3) {
            // quick tap (released within TapTime) = the key; held longer = the game's own D-pad action
            if (tap_pending_[i]) {
                if (!now) {
                    tap_pending_[i] = false;
                    pulses_.push_back({chord_vk_[i], t + 0.1});   // keys_mu_ is held: no pulse_key()
                    key(chord_vk_[i], true);
                } else if (!hold || t >= tap_until_[i]) {
                    tap_pending_[i] = false;
                    hidden &= ~bit;                        // a long press: the game sees the held D-pad from now
                }
            } else if (fresh_press && hold && chord_vk_[i]) {
                tap_pending_[i] = true;
                tap_until_[i] = t + tap_time_;
                hidden |= bit;
            }
        } else if (tap_mode_ == 2) {
            // tap = the game's own D-pad action (given on release), hold past HoldTime = the key
            if (tap_pending_[i]) {
                if (!now) {
                    tap_pending_[i] = false;
                    inject(xdpad[i], 0.1);                 // short press: the game gets its tap
                } else if (!hold) {
                    tap_pending_[i] = false;
                    hidden &= ~bit;                        // aim let go first: the game sees the held press
                } else if (t >= tap_until_[i]) {
                    tap_pending_[i] = false;
                    want_key = true;
                }
            } else if (fresh_press && hold && chord_vk_[i]) {
                tap_pending_[i] = true;
                tap_until_[i] = t + hold_time_;
                hidden |= bit;
            }
        } else if (tap_pending_[i]) {
            // first tap held back from the game: a second press in time = the key, otherwise give the game its tap
            if (fresh_press && hold && t < tap_until_[i]) {
                tap_pending_[i] = false;
                want_key = true;
            } else if (t >= tap_until_[i] || !hold) {
                tap_pending_[i] = false;
                if (now) hidden &= ~bit;                   // still held: the game sees the real (held) press from now
                else inject(xdpad[i], 0.1);                // tapped and let go: replay the tap
            }
        } else if (fresh_press && hold && chord_vk_[i]) {
            if (pass_first_tap_) {
                if (t < tap_until_[i]) want_key = true;    // second tap (the first already went to the game)
                else tap_until_[i] = t + double_tap_;
            } else {
                tap_pending_[i] = true;                    // hold the first tap back
                tap_until_[i] = t + double_tap_;
                hidden |= bit;
            }
        }
        if (!now) {                                        // released: key up, the game may see it again
            if (chord_key_down_[i]) key(chord_vk_[i], false);
            chord_key_down_[i] = false;
            chord_active_ &= ~bit;
            if (!tap_pending_[i]) hidden &= ~bit;
            continue;
        }
        if (want_key) {
            tap_until_[i] = 0;                             // a third tap starts a new double tap
            key(chord_vk_[i], true);
            chord_key_down_[i] = true;
            chord_active_ |= bit;
            hidden |= bit;
            chord_next_[i] = t + repeat_delay_;
        } else if (chord_active_ & bit) {
            if (!hold) {                                   // hold button let go first: stop, stay hidden
                if (chord_key_down_[i]) key(chord_vk_[i], false);
                chord_key_down_[i] = false;
                chord_active_ &= ~bit;
            } else if (repeat_period_ > 0 && t >= chord_next_[i]) {
                // held: repeat as up / down halves, so a game polling once per frame sees every click
                chord_key_down_[i] = !chord_key_down_[i];
                key(chord_vk_[i], chord_key_down_[i]);
                chord_next_[i] = t + repeat_period_ * 0.5;
            }
        }
    }
    prev_dpad_ = s.buttons & all;
    chord_hidden_ = hidden;
    update_corners(s, t);
    for (auto it = pulses_.begin(); it != pulses_.end();) {
        if (t >= it->up_at) { key(it->vk, false); it = pulses_.erase(it); }
        else ++it;
    }
}

void Input::configure() {
    Config& c = config();
    {
        std::lock_guard<std::mutex> l(keys_mu_);
        release_all_keys();                       // bindings may change under held keys
        static const char* half_names[8] = {"LeftSwipeUp", "LeftSwipeDown", "RightSwipeUp", "RightSwipeDown",
                                            "TopSwipeLeft", "TopSwipeRight", "BottomSwipeLeft", "BottomSwipeRight"};
        for (int i = 0; i < 8; ++i) parse_touch(c.str("Touchpad", half_names[i], ""), half_[i], half_vk_[i]);
        static const char* twof_names[5] = {"TwoFingerTap", "TwoFingerSwipeUp", "TwoFingerSwipeDown",
                                            "TwoFingerSwipeLeft", "TwoFingerSwipeRight"};
        for (int i = 0; i < 5; ++i) parse_touch(c.str("Touchpad", twof_names[i], ""), twof_[i], twof_vk_[i]);
        static const char* corner_names[4] = {"TopLeft", "TopRight", "BottomLeft", "BottomRight"};
        static const char* action_names[3] = {"Click", "DoubleClick", "DoubleClickHold"};
        for (int k = 0; k < 4; ++k)
            for (int a = 0; a < 3; ++a) {
                corner_vk_[k][a] = vk_from_name(c.str("TouchpadCorners", std::string(corner_names[k]) + action_names[a], ""));
            }
        corner_window_ = clampv(c.num("TouchpadCorners", "DoubleClickWindow", 0.35f), 0.05f, 1.0f);
        corner_hold_ = clampv(c.num("TouchpadCorners", "HoldTime", 0.35f), 0.1f, 2.0f);
        cprev_click_ = false;

        std::string hold = upper_trim(c.str("Keys", "Hold", "L2"));
        chord_hold_trigger_ = hold == "L2" || hold == "LT" ? 1 : hold == "R2" || hold == "RT" ? 2 : 0;
        static const std::pair<const char*, uint32_t> holds[] = {
            {"L1", L1}, {"LB", L1}, {"R1", R1}, {"RB", R1}, {"L3", L3}, {"LS", L3}, {"R3", R3}, {"RS", R3},
            {"CREATE", CREATE}, {"OPTIONS", OPTIONS}, {"TOUCHPAD", TOUCHPAD}, {"SQUARE", SQUARE}, {"CROSS", CROSS},
            {"CIRCLE", CIRCLE}, {"TRIANGLE", TRIANGLE},
        };
        chord_hold_ = 0;
        for (auto& [k, m] : holds) if (hold == k) chord_hold_ = m;
        chord_threshold_ = clampv(c.integer("Keys", "TriggerThreshold", 64), 1, 255);
        chord_vk_[0] = vk_from_name(c.str("Keys", "DpadUp", "Z"));
        chord_vk_[1] = vk_from_name(c.str("Keys", "DpadDown", "T"));
        chord_vk_[2] = vk_from_name(c.str("Keys", "DpadLeft", "G"));
        chord_vk_[3] = vk_from_name(c.str("Keys", "DpadRight", "H"));
        std::string mode = upper_trim(c.str("Keys", "Mode", "doubletap"));
        tap_mode_ = mode == "PRESS" ? 0 : mode == "DOUBLETAP" ? 1 : mode == "HOLD" ? 2 : 3;
        tap_time_ = clampv(c.num("Keys", "TapTime", 0.35f), 0.05f, 2.0f);
        hold_time_ = clampv(c.num("Keys", "HoldTime", 0.3f), 0.05f, 2.0f);
        double_tap_ = clampv(c.num("Keys", "DoubleTap", 0.35f), 0.05f, 1.0f);
        pass_first_tap_ = c.flag("Keys", "PassFirstTap", false);
        for (int i = 0; i < 4; ++i) { tap_pending_[i] = false; tap_until_[i] = 0; }
        chord_hidden_ = 0;
        repeat_delay_ = std::max(0.05f, c.num("Keys", "RepeatDelay", 0.4f));
        float rate = c.num("Keys", "RepeatRate", 0.0f);
        repeat_period_ = rate > 0.1f ? 1.0 / rate : 0;
        bool want_hook = upper_trim(c.str("Keys", "Method", "input")) == "HOOK";
        key_hook_mode_ = want_hook && install_key_hooks();
        LOGI("keys: hold %s, D-pad up/down/left/right -> vk %u/%u/%u/%u, method %s", hold.c_str(), chord_vk_[0],
             chord_vk_[1], chord_vk_[2], chord_vk_[3], key_hook_mode_ ? "hook" : "input");
    }
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

void Input::probe_lt(int value) {
    std::lock_guard<std::mutex> l(mu_);
    lt_probe_ = value;
}

static SHORT stick(int v, bool invert) {
    int s = (v - 128) * 256;
    if (invert) s = -s;
    return SHORT(clampv(s, -32768, 32767));
}

void Input::publish(const InputState& s, int game_rt, bool connected) {
    update_keys(s, connected);
    const uint32_t hidden = chord_hidden_.load();      // D-pad presses that went to the keyboard instead
    XINPUT_GAMEPAD g{};
    auto map = [&](uint32_t m, WORD x) { if ((s.buttons & ~hidden) & m) g.wButtons |= x; };
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
    if (lt_probe_ >= 0) g.bLeftTrigger = BYTE(lt_probe_);   // aim threshold measurement (world.cpp, F11)
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
            if (state_.Gamepad.bRightTrigger >= 128) rt_press_read_t_ = now_s();   // debug: the game saw R2 pressed
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
        clicked_ = false;
    }
    if (touching_ && a.active) {
        lx_ = a.x;
        ly_ = a.y;
        if (both) two_ = true;
        if (s.buttons & TOUCHPAD) clicked_ = true;         // a click-and-drag is not a swipe
    }
    if (touching_ && !a.active) {
        touching_ = false;
        double dt = s.t - touch_t_;
        int dx = lx_ - sx_, dy = ly_ - sy_;
        // direction of the swipe (-1 none, 0 up, 1 down, 2 left, 3 right); touchpad is 1920 x 1080
        int dir = -1;
        if (dt < 0.5) {
            if (std::abs(dy) > 300 && std::abs(dy) > std::abs(dx)) dir = dy < 0 ? 0 : 1;
            else if (std::abs(dx) > 450) dir = dx < 0 ? 2 : 3;
        }
        if (clicked_) {                                    // clicks belong to [TouchpadCorners]
        } else if (two_) {                                 // two fingers: the whole pad
            int g = -1;
            if (dir >= 0) g = dir + 1;
            else if (dt < 0.35 && std::abs(dx) < 150 && std::abs(dy) < 150) g = 0;
            if (g >= 0) { inject(twof_[g], 0.12); pulse_key(twof_vk_[g], 0.12); }
        } else if (dir == 0 || dir == 1) {                 // up / down: the left or right half it started on
            int h = (sx_ >= 960 ? 2 : 0) + dir;
            inject(half_[h], 0.12);
            pulse_key(half_vk_[h], 0.12);
        } else if (dir == 2 || dir == 3) {                 // left / right: the top or bottom half it started on
            int h = 4 + (sy_ >= 540 ? 2 : 0) + (dir - 2);
            inject(half_[h], 0.12);
            pulse_key(half_vk_[h], 0.12);
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
