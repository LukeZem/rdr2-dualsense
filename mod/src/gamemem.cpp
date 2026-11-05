#include "gamemem.h"

#include "log.h"

namespace dsr2::gamemem {

namespace {

struct SpeechRoots {
    uintptr_t lo = 0, tab = 0;          // globals: u32 index base, table pointer
    uint32_t comp = 0, flag = 0, a98 = 0, mgr = 0;
    bool ok = false;
} g_sp;

struct PoolRoots {
    uintptr_t global = 0;
    bool ok = false;
} g_pool;

std::once_flag g_once;
bool g_any = false;

struct Pattern {
    std::vector<int> bytes;      // -1 = any
    explicit Pattern(const char* s) {
        for (const char* p = s; *p;) {
            while (*p == ' ') ++p;
            if (!*p) break;
            if (p[0] == '?') { bytes.push_back(-1); p += 2; continue; }
            bytes.push_back(int(strtol(std::string(p, 2).c_str(), nullptr, 16)));
            p += 2;
        }
    }
};

std::vector<uintptr_t> scan(const Pattern& pat) {
    std::vector<uintptr_t> hits;
    auto base = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    auto dos = reinterpret_cast<const IMAGE_DOS_HEADER*>(base);
    auto nt = reinterpret_cast<const IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    auto sec = IMAGE_FIRST_SECTION(nt);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        // only .text: the same range game_files.cpp scans (other executable sections may hold guard pages)
        if (std::memcmp(sec->Name, ".text", 5) != 0) continue;
        auto lo = reinterpret_cast<const uint8_t*>(base + sec->VirtualAddress);
        size_t n = sec->Misc.VirtualSize, m = pat.bytes.size();
        if (n < m) continue;
        const int first = pat.bytes[0];
        for (size_t k = 0; k + m <= n; ++k) {
            if (lo[k] != first) continue;
            size_t j = 1;
            for (; j < m; ++j)
                if (pat.bytes[j] >= 0 && lo[k + j] != uint8_t(pat.bytes[j])) break;
            if (j == m) hits.push_back(reinterpret_cast<uintptr_t>(lo + k));
        }
    }
    return hits;
}

uintptr_t rip(uintptr_t at_disp, uintptr_t insn_end) {
    int32_t d;
    std::memcpy(&d, reinterpret_cast<const void*>(at_disp), 4);
    return insn_end + intptr_t(d);
}
uint32_t u32_at(uintptr_t a) {
    uint32_t v;
    std::memcpy(&v, reinterpret_cast<const void*>(a), 4);
    return v;
}

void find_roots() {
    double t0 = now_s();
    // speech: the IS_*_SPEECH_PLAYING helpers
    static const Pattern sp(
        "8B 81 9C 00 00 00 25 FF FF 01 00 2B 05 ?? ?? ?? ?? 48 69 C8 48 01 00 00 48 8B 05 ?? ?? ?? ?? 48 8B 54 01 ?? "
        "48 8B C2 48 83 E0 FE 48 F7 DA 48 1B C9 48 23 C8 74 ?? F6 81 ?? ?? 00 00 02 74 ?? 48 8B 81 ?? ?? 00 00 48 8B 88 ?? ?? 00 00");
    auto hs = scan(sp);
    bool agree = !hs.empty();
    for (uintptr_t a : hs) {
        SpeechRoots r;
        r.lo = rip(a + 13, a + 17);
        r.tab = rip(a + 27, a + 31);
        r.comp = *reinterpret_cast<const uint8_t*>(a + 35);
        r.flag = u32_at(a + 56);
        r.a98 = u32_at(a + 66);
        r.mgr = u32_at(a + 73);
        if (a == hs[0]) g_sp = r;
        else if (r.lo != g_sp.lo || r.tab != g_sp.tab || r.comp != g_sp.comp || r.flag != g_sp.flag || r.a98 != g_sp.a98 ||
                 r.mgr != g_sp.mgr)
            agree = false;
    }
    g_sp.ok = agree && g_sp.mgr > 0 && g_sp.mgr < 0x100000;
    // sound pool: the sound base class destructor
    static const Pattern pl("0F AF 15 ?? ?? ?? ?? 48 8B 05 ?? ?? ?? ?? 49 69 C9 60 A8 02 00 48 03 94 01 48 A8 02 00");
    auto hp = scan(pl);
    agree = !hp.empty();
    for (uintptr_t a : hp) {
        uintptr_t g = rip(a + 10, a + 14);
        if (a == hp[0]) g_pool.global = g;
        else if (g != g_pool.global) agree = false;
    }
    g_pool.ok = agree;
    uintptr_t exe = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    LOGI("game audio state: speech %s (%zu signatures), sound pool %s (%zu) - %.0f ms", g_sp.ok ? "found" : "NOT found",
         hs.size(), g_pool.ok ? "found" : "NOT found", hp.size(), (now_s() - t0) * 1000);
    if (g_sp.ok)
        LOGD("speech roots: exe+0x%llX / exe+0x%llX, +0x%X +0x%X +0x%X +0x%X", (unsigned long long)(g_sp.lo - exe),
             (unsigned long long)(g_sp.tab - exe), g_sp.comp, g_sp.flag, g_sp.a98, g_sp.mgr);
    if (g_pool.ok) LOGD("sound pool root: exe+0x%llX", (unsigned long long)(g_pool.global - exe));
    g_any = g_sp.ok || g_pool.ok;
}

}  // namespace

bool init() {
    std::call_once(g_once, find_roots);
    return g_any;
}
bool speech_ok() { return g_sp.ok; }
bool pool_ok() { return g_pool.ok; }

bool read(uintptr_t a, void* out, size_t n) {
    SIZE_T got = 0;
    return a && ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(a), out, n, &got) && got == n;
}

namespace {

std::mutex g_pad_mu;
uintptr_t g_pad_slot0 = 0;             // slot 0's "a pad is here" byte
int g_pad_tries = 0;
double g_pad_next_try = 0;

// found on first use (the controller thread), retried a few times in case the code is not unpacked yet
uintptr_t pad_slot0() {
    std::lock_guard<std::mutex> l(g_pad_mu);
    if (g_pad_slot0 || g_pad_tries >= 5 || now_s() < g_pad_next_try) return g_pad_slot0;
    ++g_pad_tries;
    g_pad_next_try = now_s() + 10;
    // the window procedure's check of the empty slots (WM_DEVICECHANGE, DBT_DEVNODES_CHANGED)
    static const Pattern chk("33 FF 48 8D 1D ?? ?? ?? ?? 80 3B 00 75 ?? 48 8D 54 24 ?? 8B CF E8 ?? ?? ?? ?? 85 C0 "
                             "0F 94 C0 88 03 FF C7 48 81 C3 80 01 00 00 83 FF 04 7C");
    // the per-frame update of the marked slots
    static const Pattern upd("48 8D 1D ?? ?? ?? ?? 44 8A F1 48 8D 3D ?? ?? ?? ?? BE 04 00 00 00 80 3B 00");
    auto a = scan(chk), b = scan(upd);
    uintptr_t x = a.size() == 1 ? rip(a[0] + 5, a[0] + 9) : 0, y = b.size() == 1 ? rip(b[0] + 3, b[0] + 7) : 0;
    if (x && x == y) g_pad_slot0 = x;
    uintptr_t exe = reinterpret_cast<uintptr_t>(GetModuleHandleW(nullptr));
    if (g_pad_slot0) LOGI("game pad slots found (exe+0x%llX)", (unsigned long long)(g_pad_slot0 - exe));
    else LOGW("game pad slots NOT found (%zu / %zu signatures) - a controller plugged in late may stay unseen",
              a.size(), b.size());
    return g_pad_slot0;
}

}  // namespace

int pad_slot_marked(int slot) {
    uintptr_t s0 = pad_slot0();
    uint8_t v = 0;
    if (!s0 || slot < 0 || slot > 3 || !read(s0 + uintptr_t(slot) * 0x180, v)) return -1;
    return v ? 1 : 0;
}

bool mark_pad_slot(int slot) {
    uintptr_t s0 = pad_slot0();
    if (!s0 || slot < 0 || slot > 3) return false;
    uint8_t one = 1;
    SIZE_T put = 0;
    return WriteProcessMemory(GetCurrentProcess(), reinterpret_cast<void*>(s0 + uintptr_t(slot) * 0x180), &one, 1, &put) &&
           put == 1;
}

bool ped_requests(const void* ped_object, std::vector<Request>& out) {
    out.clear();
    if (!g_sp.ok || !ped_object) return false;
    uint32_t idx = 0, lo = 0;
    uintptr_t tab = 0, a = 0, x = 0, mgr = 0, arr = 0;
    uint8_t flag = 0;
    uint16_t count = 0;
    if (!read(uintptr_t(ped_object) + 0x9C, idx) || !read(g_sp.lo, lo) || !read(g_sp.tab, tab) || !tab) return false;
    uintptr_t entry = tab + uintptr_t(uint32_t((idx & 0x1FFFF) - lo)) * 0x148;
    if (!read(entry + g_sp.comp, a)) return false;
    a &= ~uintptr_t(1);
    if (!a || !read(a + g_sp.flag, flag) || !(flag & 2) || !read(a + g_sp.a98, x) || !read(x + g_sp.mgr, mgr) || !mgr)
        return false;
    if (!read(mgr + 0x80, count) || !read(mgr + 0x78, arr) || !arr || count > 64) return false;
    for (uint16_t i = 0; i < count; ++i) {
        Request r;
        if (!read(arr + 8 * uintptr_t(i), r.addr) || !r.addr || !read(r.addr + 0x214, r.type) || !read(r.addr + 0x234, r.state))
            continue;
        read(r.addr + 0x1D8, r.sound);
        if (r.sound) {
            uint32_t f[3];
            if (read(r.sound + 0x110, f, sizeof f)) { r.voice = f[0]; r.partial = f[1]; r.variation = f[2]; }
        }
        out.push_back(r);
    }
    return true;
}

void pool_stems(const std::function<bool(uint32_t)>& known, std::vector<Stem>& out) {
    out.clear();
    if (!g_pool.ok) return;
    uintptr_t base = 0;
    uint64_t size = 0;
    if (!read(g_pool.global + 0x10, base) || !read(g_pool.global + 0x8, size) || !base || size < 0x1000 || size > (64u << 20))
        return;
    static std::vector<uint32_t> buf;
    buf.resize(size_t(size / 4));
    if (!read(base, buf.data(), buf.size() * 4)) return;
    for (size_t i = 1; i < buf.size(); ++i) {
        uint32_t id = buf[i] & 0x1FFFFFFF;
        if (!id || !known(id)) continue;
        out.push_back({base + 4 * (i - 1), buf[i - 1], id});
    }
}

}  // namespace dsr2::gamemem
