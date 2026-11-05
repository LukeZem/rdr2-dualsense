// I/O probe (debug log only, read only): which parts of the game's audio archives (x64\audio\sfx\*.rpf) the game
// reads, when - to find out whether each spoken line / cutscene is streamed from disk and can be identified
// exactly (archive + offset -> file -> stream). Hooks ntdll!NtReadFile with a small trampoline; the original call
// always runs unchanged, the hook only records (handle, offset, size, time) for audio archives.
#include "io_probe.h"

#include "common.h"
#include "log.h"

#include <atomic>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>

namespace dsr2 {

namespace {

using NtReadFileFn = LONG(NTAPI*)(HANDLE, HANDLE, PVOID, PVOID, PVOID, PVOID, ULONG, PLARGE_INTEGER, PULONG);
NtReadFileFn g_orig = nullptr;

struct Rec { uint64_t ft; HANDLE h; int64_t off; uint32_t len; };
constexpr size_t kRing = 1 << 14;
Rec g_ring[kRing];
std::atomic<uint64_t> g_head{0}, g_tail{0};

std::mutex g_mu;                                   // guards the handle map
std::unordered_map<HANDLE, int> g_kind;            // 1 = audio archive, 0 = other
std::unordered_map<HANDLE, std::string> g_name;
thread_local bool t_busy = false;

int kind_of(HANDLE h) {
    {
        std::lock_guard<std::mutex> l(g_mu);
        auto it = g_kind.find(h);
        if (it != g_kind.end()) return it->second;
    }
    wchar_t buf[1024];
    DWORD n = GetFinalPathNameByHandleW(h, buf, 1023, FILE_NAME_NORMALIZED);
    int k = 0;
    std::string name;
    if (n > 0 && n < 1023) {
        std::wstring p(buf, n);
        size_t i = p.find(L"\\x64\\audio\\");
        if (i != std::wstring::npos) {
            k = 1;
            for (wchar_t c : p.substr(i + 1)) name += char(c < 128 ? c : '?');
        }
    }
    std::lock_guard<std::mutex> l(g_mu);
    g_kind[h] = k;
    if (k) g_name[h] = name;
    return k;
}

LONG NTAPI hk_read(HANDLE h, HANDLE ev, PVOID apc, PVOID ctx, PVOID iosb, PVOID buf, ULONG len, PLARGE_INTEGER off,
                   PULONG key) {
    if (!t_busy && off) {
        t_busy = true;
        if (kind_of(h) == 1) {
            FILETIME ft;
            GetSystemTimePreciseAsFileTime(&ft);
            uint64_t i = g_head.fetch_add(1);
            if (i - g_tail.load() < kRing)
                g_ring[i % kRing] = {(uint64_t(ft.dwHighDateTime) << 32) | ft.dwLowDateTime, h, off->QuadPart, len};
        }
        t_busy = false;
    }
    return g_orig(h, ev, apc, ctx, iosb, buf, len, off, key);
}

void* alloc_near(void* target) {
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    uintptr_t t = uintptr_t(target), gran = si.dwAllocationGranularity;
    for (uintptr_t d = gran; d < 0x70000000; d += gran)
        for (uintptr_t cand : {t - d, t + d}) {
            void* p = VirtualAlloc(reinterpret_cast<void*>(cand & ~(gran - 1)), 4096, MEM_COMMIT | MEM_RESERVE,
                                   PAGE_EXECUTE_READWRITE);
            if (p) return p;
        }
    return nullptr;
}

void drain() {
    t_busy = true;                                 // our own log writes must not be recorded
    std::unordered_map<HANDLE, bool> named;
    while (true) {
        Sleep(25);
        uint64_t head = g_head.load(), tail = g_tail.load();
        if (head - tail > kRing) {
            LOGD("io: %llu reads lost (ring full)", (unsigned long long)(head - tail - kRing));
            tail = head - kRing;
        }
        for (; tail < head; ++tail) {
            const Rec r = g_ring[tail % kRing];
            std::string name;
            {
                std::lock_guard<std::mutex> l(g_mu);
                auto it = g_name.find(r.h);
                if (it != g_name.end()) name = it->second;
            }
            FILETIME ft{DWORD(r.ft), DWORD(r.ft >> 32)}, lt;
            SYSTEMTIME st;
            FileTimeToLocalFileTime(&ft, &lt);
            FileTimeToSystemTime(&lt, &st);
            LOGD("io: %02d:%02d:%02d.%03d %s off 0x%llX len %u", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds,
                 name.c_str(), (unsigned long long)r.off, r.len);
        }
        g_tail.store(tail);
    }
}

}  // namespace

void io_probe_start() {
    HMODULE nt = GetModuleHandleW(L"ntdll.dll");
    auto* f = reinterpret_cast<uint8_t*>(nt ? GetProcAddress(nt, "NtReadFile") : nullptr);
    // x64 syscall stub: 4C 8B D1 (mov r10, rcx)  B8 xx xx xx xx (mov eax, number) - 8 self-contained bytes
    if (!f || !(f[0] == 0x4C && f[1] == 0x8B && f[2] == 0xD1 && f[3] == 0xB8)) {
        LOGW("io probe: NtReadFile has an unexpected start - not hooked");
        return;
    }
    auto* tramp = static_cast<uint8_t*>(alloc_near(f));
    if (!tramp) { LOGW("io probe: no memory near ntdll"); return; }
    std::memcpy(tramp, f, 8);                                     // the two original instructions
    tramp[8] = 0xFF; tramp[9] = 0x25; std::memset(tramp + 10, 0, 4);  // jmp [rip+0] -> back to NtReadFile+8
    uint64_t back = uint64_t(f + 8);
    std::memcpy(tramp + 14, &back, 8);
    uint8_t* relay = tramp + 32;                                  // jmp [rip+0] -> our hook
    relay[0] = 0xFF; relay[1] = 0x25; std::memset(relay + 2, 0, 4);
    uint64_t hk = uint64_t(&hk_read);
    std::memcpy(relay + 6, &hk, 8);
    FlushInstructionCache(GetCurrentProcess(), tramp, 64);
    g_orig = reinterpret_cast<NtReadFileFn>(tramp);
    std::thread(drain).detach();
    // replace the first 8 bytes in one atomic write: jmp rel32 to the relay + 3 nops
    uint8_t patch[8] = {0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90};
    int32_t rel = int32_t(intptr_t(relay) - (intptr_t(f) + 5));
    std::memcpy(patch + 1, &rel, 4);
    DWORD old;
    if (!VirtualProtect(f, 8, PAGE_EXECUTE_READWRITE, &old)) { LOGW("io probe: cannot patch ntdll"); return; }
    uint64_t v;
    std::memcpy(&v, patch, 8);
    InterlockedExchange64(reinterpret_cast<volatile LONG64*>(f), LONG64(v));
    VirtualProtect(f, 8, old, &old);
    FlushInstructionCache(GetCurrentProcess(), f, 8);
    LOGI("io probe: logging reads of the game's audio archives (debug)");
}

}  // namespace dsr2
