#include "ds5.h"

#include "log.h"

#include <setupapi.h>
extern "C" {
#include <hidsdi.h>
#include <hidpi.h>
}

namespace dsr2 {

static constexpr uint16_t kSony = 0x054C;
static constexpr uint16_t kDualSense = 0x0CE6, kDualSenseEdge = 0x0DF2;

static uint32_t crc32_table[256];
static void crc_init() {
    for (uint32_t i = 0; i < 256; ++i) {
        uint32_t c = i;
        for (int k = 0; k < 8; ++k) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        crc32_table[i] = c;
    }
}
static uint32_t crc32(const uint8_t* d, size_t n, uint32_t crc = 0xFFFFFFFFu) {
    for (size_t i = 0; i < n; ++i) crc = crc32_table[(crc ^ d[i]) & 0xFF] ^ (crc >> 8);
    return crc;
}

std::string DualSense::name() const { return name_; }

bool DualSense::start(Handler h) {
    crc_init();
    handler_ = std::move(h);
    running_ = true;
    read_ev_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    write_ev_ = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    thread_ = std::thread([this] { loop(); });
    return true;
}

void DualSense::stop() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
    if (read_ev_) CloseHandle(read_ev_);
    if (write_ev_) CloseHandle(write_ev_);
    read_ev_ = write_ev_ = nullptr;
}

bool DualSense::open() {
    GUID hid;
    HidD_GetHidGuid(&hid);
    HDEVINFO set = SetupDiGetClassDevsW(&hid, nullptr, nullptr, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) return false;
    struct Cand { std::wstring path; bool usb; size_t in, out; };
    std::vector<Cand> cands;
    SP_DEVICE_INTERFACE_DATA ifd{sizeof(ifd)};
    for (DWORD i = 0; SetupDiEnumDeviceInterfaces(set, nullptr, &hid, i, &ifd); ++i) {
        DWORD need = 0;
        SetupDiGetDeviceInterfaceDetailW(set, &ifd, nullptr, 0, &need, nullptr);
        std::vector<uint8_t> buf(need);
        auto* det = reinterpret_cast<SP_DEVICE_INTERFACE_DETAIL_DATA_W*>(buf.data());
        det->cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_W);
        if (!SetupDiGetDeviceInterfaceDetailW(set, &ifd, det, need, nullptr, nullptr)) continue;
        HANDLE h = CreateFileW(det->DevicePath, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, 0, nullptr);
        if (h == INVALID_HANDLE_VALUE) continue;
        HIDD_ATTRIBUTES a{sizeof(a)};
        bool ok = HidD_GetAttributes(h, &a) && a.VendorID == kSony && (a.ProductID == kDualSense || a.ProductID == kDualSenseEdge);
        PHIDP_PREPARSED_DATA pp = nullptr;
        HIDP_CAPS caps{};
        if (ok && HidD_GetPreparsedData(h, &pp)) {
            HidP_GetCaps(pp, &caps);
            HidD_FreePreparsedData(pp);
            ok = caps.UsagePage == 1 && caps.Usage == 5;
        } else {
            ok = false;
        }
        CloseHandle(h);
        if (ok) cands.push_back({det->DevicePath, caps.InputReportByteLength == 64, caps.InputReportByteLength,
                                 caps.OutputReportByteLength});
    }
    SetupDiDestroyDeviceInfoList(set);
    std::stable_sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) { return a.usb > b.usb; });
    for (auto& c : cands) {
        HANDLE h = CreateFileW(c.path.c_str(), GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                               OPEN_EXISTING, FILE_FLAG_OVERLAPPED, nullptr);
        if (h == INVALID_HANDLE_VALUE) continue;
        dev_ = h;
        usb_ = c.usb;
        in_len_ = c.in;
        out_len_ = c.out;
        name_ = std::string("DualSense ") + (c.usb ? "USB" : "Bluetooth");
        if (!c.usb) {
            uint8_t feat[64] = {0x05};          // calibration report switches BT to full 0x31 reports
            HidD_GetFeature(dev_, feat, 41);
        }
        lightbar_released_ = false;
        last_payload_.clear();
        LOGI("controller: %s (in %zu, out %zu bytes)", name_.c_str(), in_len_, out_len_);
        return true;
    }
    return false;
}

void DualSense::close() {
    if (dev_ != INVALID_HANDLE_VALUE) {
        OutputState off;
        write(off, true);
        CancelIo(dev_);
        CloseHandle(dev_);
    }
    dev_ = INVALID_HANDLE_VALUE;
    connected_ = false;
}

static void parse(const uint8_t* d, InputState& s) {
    s.lx = d[0]; s.ly = d[1]; s.rx = d[2]; s.ry = d[3]; s.l2 = d[4]; s.r2 = d[5];
    uint8_t b0 = d[7], b1 = d[8], b2 = d[9];
    static const uint32_t hat[8] = {DPAD_UP, DPAD_UP | DPAD_RIGHT, DPAD_RIGHT, DPAD_RIGHT | DPAD_DOWN, DPAD_DOWN,
                                    DPAD_DOWN | DPAD_LEFT, DPAD_LEFT, DPAD_LEFT | DPAD_UP};
    uint32_t m = (b0 & 0x0F) < 8 ? hat[b0 & 0x0F] : 0;
    if (b0 & 0x10) m |= SQUARE;
    if (b0 & 0x20) m |= CROSS;
    if (b0 & 0x40) m |= CIRCLE;
    if (b0 & 0x80) m |= TRIANGLE;
    static const uint32_t row1[8] = {L1, R1, L2_BTN, R2_BTN, CREATE, OPTIONS, L3, R3};
    for (int i = 0; i < 8; ++i) if (b1 & (1 << i)) m |= row1[i];
    if (b2 & 1) m |= PS;
    if (b2 & 2) m |= TOUCHPAD;
    if (b2 & 4) m |= MUTE;
    s.buttons = m;
    for (int i = 0; i < 3; ++i) {
        s.gyro[i] = int16_t(d[15 + 2 * i] | (d[16 + 2 * i] << 8));
        s.accel[i] = int16_t(d[21 + 2 * i] | (d[22 + 2 * i] << 8));
    }
    s.sensor_ts = d[27] | (d[28] << 8) | (d[29] << 16) | (uint32_t(d[30]) << 24);
    for (int i = 0; i < 2; ++i) {
        const uint8_t* p = d + 32 + 4 * i;
        s.touch[i].active = !(p[0] & 0x80);
        s.touch[i].id = p[0] & 0x7F;
        s.touch[i].x = p[1] | ((p[2] & 0x0F) << 8);
        s.touch[i].y = (p[2] >> 4) | (p[3] << 4);
    }
    s.r2_feedback = d[41];
    s.l2_feedback = d[42];
    s.effect_state = d[47];
    s.battery = std::min(10, d[52] & 0x0F);
}

void DualSense::build_payload(const OutputState& o, uint8_t* p) {
    std::memset(p, 0, 47);
    p[0] = 0x04 | 0x08;                       // both trigger effects
    p[1] = 0x40;                              // motor power level
    if (o.has_rumble) {
        p[0] |= 0x01 | 0x02;
        p[38] |= 0x04;
        p[3] = o.rumble_left;
        p[2] = o.rumble_right;
    }
    std::memcpy(p + 10, o.r2.data(), 11);
    std::memcpy(p + 21, o.l2.data(), 11);
    p[36] = uint8_t(o.trigger_power_reduction & 7);
    if (o.mute_led >= 0) {
        p[1] |= 0x01;
        p[8] = uint8_t(o.mute_led);
    }
    if (o.has_lightbar) {
        p[1] |= 0x04;
        if (!lightbar_released_) {
            p[38] |= 0x02;
            p[41] = 0x02;
        }
        p[44] = o.r; p[45] = o.g; p[46] = o.b;
    }
    if (o.player_leds >= 0) {
        p[1] |= 0x10;
        p[43] = uint8_t(o.player_leds & 0x1F);
    }
}

bool DualSense::write(const OutputState& o, bool force) {
    if (dev_ == INVALID_HANDLE_VALUE) return false;
    uint8_t payload[47];
    build_payload(o, payload);
    if (!force && last_payload_.size() == 47 && std::memcmp(last_payload_.data(), payload, 47) == 0) return true;
    std::vector<uint8_t> rep(std::max<size_t>(out_len_, usb_ ? 48 : 78), 0);
    if (usb_) {
        rep[0] = 0x02;
        std::memcpy(rep.data() + 1, payload, 47);
    } else {
        rep[0] = 0x31;
        rep[1] = uint8_t((bt_seq_ & 0x0F) << 4);
        rep[2] = 0x10;
        std::memcpy(rep.data() + 3, payload, 47);
        bt_seq_ = uint8_t((bt_seq_ + 1) & 0x0F);
        uint8_t seed = 0xA2;
        uint32_t crc = crc32(&seed, 1);
        crc = ~crc32(rep.data(), 74, crc);
        std::memcpy(rep.data() + 74, &crc, 4);
    }
    OVERLAPPED ov{};
    ov.hEvent = write_ev_;
    ResetEvent(write_ev_);
    DWORD n = 0;
    BOOL ok = WriteFile(dev_, rep.data(), DWORD(rep.size()), &n, &ov);
    if (!ok && GetLastError() == ERROR_IO_PENDING) {
        if (WaitForSingleObject(write_ev_, 50) != WAIT_OBJECT_0) {
            CancelIo(dev_);
            return false;
        }
        ok = GetOverlappedResult(dev_, &ov, &n, FALSE);
    }
    if (!ok) return false;
    if (o.has_lightbar) lightbar_released_ = true;
    last_payload_.assign(payload, payload + 47);
    return true;
}

void DualSense::loop() {
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_ABOVE_NORMAL);
    std::vector<uint8_t> buf(128);
    while (running_) {
        if (!open()) {
            for (int i = 0; i < 20 && running_; ++i) Sleep(100);
            continue;
        }
        connected_ = true;
        int count = 0;
        double rate_t = now_s();
        bool pending = false;
        OVERLAPPED ov{};
        while (running_) {
            if (!pending) {
                ov = OVERLAPPED{};
                ov.hEvent = read_ev_;
                ResetEvent(read_ev_);
                DWORD n = 0;
                if (!ReadFile(dev_, buf.data(), DWORD(std::max<size_t>(in_len_, 78)), &n, &ov) &&
                    GetLastError() != ERROR_IO_PENDING) {
                    LOGW("controller read failed (%lu) - reconnecting", GetLastError());
                    break;
                }
                pending = true;
            }
            DWORD w = WaitForSingleObject(read_ev_, 10);
            InputState s = last_;
            s.t = now_s();
            s.fresh = false;
            if (w == WAIT_OBJECT_0) {
                DWORD n = 0;
                pending = false;
                if (!GetOverlappedResult(dev_, &ov, &n, FALSE)) {
                    LOGW("controller disconnected");
                    break;
                }
                if (buf[0] == 0x01 && n >= 64) {
                    parse(buf.data() + 1, s);
                    s.fresh = true;
                } else if (buf[0] == 0x31 && n >= 64) {
                    parse(buf.data() + 2, s);
                    s.fresh = true;
                } else {
                    continue;
                }
                last_ = s;
                ++count;
            }
            double t = now_s();
            if (t - rate_t >= 1.0) {
                rate_ = float(count / (t - rate_t));
                count = 0;
                rate_t = t;
            }
            OutputState out;
            try {
                if (handler_ && handler_(s, out)) write(out, false);
            } catch (const std::exception& e) {
                LOGE("controller handler: %s", e.what());
            }
        }
        close();
    }
}

}  // namespace dsr2
