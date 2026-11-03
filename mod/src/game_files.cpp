// The game's file device layer (rage::fiDevice) - the same entry points RedM uses for RDR2 (citizenfx/fivem,
// code/components/rage-device-rdr3, which targets game build 1491 like the Steam/Rockstar release):
//   rage::fiDevice::GetDevice(path, allowRoot, bool, bool)   pattern "41 8A F0 40 8A EA 41 B8 07 00 00 00", -0x14
//   virtual methods (MSVC vtable slots from RedM's fiDevice.h): Open 4, Read 10, Close 18, GetFileLength 21.
// Nothing is called unless the pattern is found exactly once in the game's code and the device / vtable
// pointers it gives back are sane.
#include "game_files.h"

#include "common.h"
#include "log.h"

#include <algorithm>
#include <atomic>
#include <map>
#include <mutex>

namespace dsr2::game_files {

namespace {

using GetDeviceFn = void* (*)(const char* path, bool allow_root, bool, bool);
using OpenFn = uint64_t (*)(void* self, const char* path, bool read_only);
using ReadFn = uint32_t (*)(void* self, uint64_t handle, void* buffer, uint32_t size);
using CloseFn = int32_t (*)(void* self, uint64_t handle);
using LengthFn = int (*)(void* self, uint64_t handle);

constexpr uint64_t kBadHandle = ~0ull;

std::once_flag g_once;
GetDeviceFn g_get_device = nullptr;
uintptr_t g_image = 0, g_image_end = 0;
std::mutex g_mu;
std::map<std::string, std::vector<uint8_t>> g_files;   // preloaded, until the sound loader takes them
std::atomic<bool> g_ready{false};

// the game's code section (.text of the exe)
bool code_range(uintptr_t& lo, uintptr_t& hi) {
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    auto nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    g_image = base;
    g_image_end = base + nt->OptionalHeader.SizeOfImage;
    auto sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (std::memcmp(sec->Name, ".text", 5) == 0) {
            lo = base + sec->VirtualAddress;
            hi = lo + sec->Misc.VirtualSize;
            return true;
        }
    }
    return false;
}

void find_entry_points() {
    static const uint8_t pat[] = {0x41, 0x8A, 0xF0, 0x40, 0x8A, 0xEA, 0x41, 0xB8, 0x07, 0x00, 0x00, 0x00};
    uintptr_t lo = 0, hi = 0;
    if (!code_range(lo, hi)) {
        LOGW("game files: no code section");
        return;
    }
    uintptr_t hit = 0;
    int hits = 0;
    for (uintptr_t p = lo; p + sizeof pat <= hi; ++p) {
        if (*reinterpret_cast<const uint8_t*>(p) != pat[0] || std::memcmp(reinterpret_cast<const void*>(p), pat, sizeof pat))
            continue;
        hit = p;
        if (++hits > 1) break;
    }
    if (hits != 1) {
        LOGW("game files: device layer not found (%d matches) - game sounds only from LML mods", hits);
        return;
    }
    g_get_device = reinterpret_cast<GetDeviceFn>(hit - 0x14);
    LOGI("game files: device layer at RDR2.exe+0x%llX", (unsigned long long)(hit - 0x14 - g_image));
}

// code / tables of a loaded module: the game's own devices live in RDR2.exe, LML replaces the archive devices with
// its own (vfs.asi) - both are fine; a pointer into nowhere is not
bool in_image(const void* p) {
    auto a = reinterpret_cast<uintptr_t>(p);
    if (a >= g_image && a < g_image_end) return true;
    HMODULE m = nullptr;
    return p && GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                                   reinterpret_cast<LPCWSTR>(p), &m) && m;
}

// the device for a path and its vtable, checked
void** device(const char* path, void*& dev) {
    std::call_once(g_once, find_entry_points);
    if (!g_get_device) return nullptr;
    dev = g_get_device(path, true, true, true);
    if (!dev) return nullptr;
    auto vt = *reinterpret_cast<void***>(dev);
    if (!in_image(vt) || !in_image(vt[4]) || !in_image(vt[10]) || !in_image(vt[18]) || !in_image(vt[21])) return nullptr;
    return vt;
}

}  // namespace

bool ready() { return g_ready; }

static std::vector<uint8_t> read(const std::string& path) {
    std::vector<uint8_t> out;
    void* dev = nullptr;
    void** vt = device(path.c_str(), dev);
    if (!vt) return out;
    uint64_t h = reinterpret_cast<OpenFn>(vt[4])(dev, path.c_str(), true);
    if (h == kBadHandle) return out;
    int len = reinterpret_cast<LengthFn>(vt[21])(dev, h);
    if (len > 0 && len < (512 << 20)) {
        out.resize(size_t(len));
        size_t got = 0;
        while (got < out.size()) {
            uint32_t n = reinterpret_cast<ReadFn>(vt[10])(dev, h, out.data() + got, uint32_t(std::min<size_t>(out.size() - got, 1 << 20)));
            if (n == 0 || n == ~0u) break;
            got += n;
        }
        out.resize(got);
    }
    reinterpret_cast<CloseFn>(vt[18])(dev, h);
    return out;
}

void preload(const std::vector<std::string>& paths) {
    double t0 = now_s();
    size_t files = 0, bytes = 0;
    for (const std::string& p : paths) {
        std::vector<uint8_t> d = read(p);
        if (d.empty()) continue;
        ++files;
        bytes += d.size();
        std::lock_guard<std::mutex> l(g_mu);
        g_files[p] = std::move(d);
    }
    g_ready = true;
    LOGI("game files: %zu of %zu read, %.1f MB in %.2f s", files, paths.size(), double(bytes) / (1 << 20), now_s() - t0);
}

std::vector<uint8_t> take(const std::string& path) {
    std::lock_guard<std::mutex> l(g_mu);
    auto it = g_files.find(path);
    if (it == g_files.end()) return {};
    std::vector<uint8_t> d = std::move(it->second);
    g_files.erase(it);
    return d;
}

}  // namespace dsr2::game_files
