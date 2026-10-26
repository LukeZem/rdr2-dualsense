// Our texts (the Settings row, the DualSense page) in the game's own string table, whatever the game language.
//
// The game keeps its always-loaded menu texts in global.yldb: a hash map of nodes
//     node  {u64 label hash, value*, next*}        bucket = hash % bucket count
//     value {16 bytes, const char* text, u64 length incl. the 0}
// We find that map in memory (the nodes of a few labels every language has -> the bucket array holding
// them -> its size), then link one node per text at the head of its bucket: a single 8-byte write each, so
// the game always sees a whole chain. A thread re-checks now and then and repeats this if the game loaded
// the table again (other language, reload).
// No game function is called, so this works on the title screen too (Script Hook scripts don't run there).
#include "text_inject.h"

#include "common.h"
#include "log.h"

#include <algorithm>
#include <cstring>
#include <thread>
#include <vector>

namespace dsr2 {

namespace {

struct Text {
    const char* key;
    const char* text;
};
const Text kTexts[] = {
#include "settings_texts.inc"
};

// labels in global.yldb of every language: used to find the table and to prove we found the right one
const char* const kProbes[] = {"MO_ON", "MO_OFF", "IB_BACK", "IB_SELECT"};
constexpr int kProbeCount = int(sizeof kProbes / sizeof kProbes[0]);
constexpr uint32_t kMaxBuckets = 1u << 22;

bool readm(uintptr_t a, void* out, size_t n) {
    SIZE_T got = 0;
    return a && ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(a), out, n, &got) && got == n;
}

struct Region {
    uintptr_t base;
    size_t size;
};

// the game's heap: committed private read-write memory (resources live there); `skip` = our scan buffer
std::vector<Region> regions(uintptr_t skip) {
    std::vector<Region> out;
    MEMORY_BASIC_INFORMATION m;
    uintptr_t a = 0x10000;
    while (a < 0x7FFFFFFF0000ull && VirtualQuery(reinterpret_cast<void*>(a), &m, sizeof m) == sizeof m) {
        uintptr_t base = reinterpret_cast<uintptr_t>(m.BaseAddress);
        if (m.State == MEM_COMMIT && m.Type == MEM_PRIVATE && (m.Protect & PAGE_READWRITE) &&
            !(m.Protect & PAGE_GUARD) && base != skip)
            out.push_back({base, m.RegionSize});
        a = base + m.RegionSize;
    }
    return out;
}

// calls fn(address, value) for every aligned 8-byte word of the game's heap
template <class F>
void scan(F&& fn) {
    constexpr size_t kChunk = 4u << 20;
    auto* buf = static_cast<uint64_t*>(VirtualAlloc(nullptr, kChunk, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!buf) return;
    for (const Region& r : regions(reinterpret_cast<uintptr_t>(buf))) {
        for (size_t off = 0; off < r.size; off += kChunk) {
            size_t n = std::min(kChunk, r.size - off);
            if (!readm(r.base + off, buf, n)) continue;
            for (size_t i = 0; i < n / 8; ++i) fn(r.base + off + i * 8, buf[i]);
        }
    }
    VirtualFree(buf, 0, MEM_RELEASE);
}

// a string table node of `key` at a (value block -> a 0-terminated text of the stored length)
bool is_node(uintptr_t a, uint32_t key) {
    uint64_t n[3], v[4];
    if (!readm(a, n, sizeof n) || n[0] != key || !readm(n[1], v, sizeof v)) return false;
    uint64_t len = v[3];
    if (len < 2 || len > 1024) return false;
    char s[1024];
    return readm(v[2], s, len) && s[len - 1] == 0 && std::strlen(s) == len - 1;
}

struct Table {
    uintptr_t buckets = 0;
    uint32_t count = 0;
    uint8_t value_head[16] = {};    // the first 16 bytes of a real value block (copied into ours)
};

// is `key` in the table (walking its bucket's chain)?
uintptr_t find_in(const Table& t, uint32_t key) {
    uint64_t p = 0;
    if (!readm(t.buckets + 8ull * (key % t.count), &p, 8)) return 0;
    for (int i = 0; p && i < 64; ++i) {
        uint64_t n[3];
        if (!readm(p, n, sizeof n)) return 0;
        if (n[0] == key) return uintptr_t(p);
        p = n[2];
    }
    return 0;
}

bool take(Table& t, Table& out) {
    for (const char* k : kProbes)
        if (!find_in(t, joaat(k))) return false;
    uint64_t n[3];
    if (!readm(find_in(t, joaat(kProbes[0])), n, sizeof n) || !readm(n[1], t.value_head, 16)) return false;
    out = t;
    return true;
}

// Fast: a loaded table sits at the start of a page exactly as in the file - its header points at the
// bucket array right behind it (+0x10 = header + 0x30, +0x18 = bucket count). Reads 40 bytes per page.
bool locate_fast(Table& out) {
    double t0 = now_s();
    size_t pages = 0;
    for (const Region& r : regions(0)) {
        for (uintptr_t a = r.base; a + 0x1000 <= r.base + r.size; a += 0x1000) {
            ++pages;
            uint64_t h[4];
            if (!readm(a, h, sizeof h) || h[2] != a + 0x30) continue;
            uint32_t c = uint32_t(h[3]);
            if (c < 16 || c >= kMaxBuckets) continue;
            Table t;
            t.buckets = a + 0x30;
            t.count = c;
            if (!take(t, out)) continue;
            LOGI("texts: string table at %p, %u buckets (%zu pages, %.2f s)", reinterpret_cast<void*>(t.buckets), c,
                 pages, now_s() - t0);
            return true;
        }
    }
    LOGD("texts: no string table yet (%zu pages, %.2f s)", pages, now_s() - t0);
    return false;
}

// Slow fallback (other layout): the nodes of the probe labels, what points at them, the bucket array that
// fits all of them. Reads all of the game's memory twice (about a minute).
bool locate_slow(Table& out) {
    double t0 = now_s();
    uint32_t keys[kProbeCount];
    for (int i = 0; i < kProbeCount; ++i) keys[i] = joaat(kProbes[i]);

    // 1. nodes of the probe labels
    std::vector<std::pair<uintptr_t, int>> cands;
    scan([&](uintptr_t a, uint64_t v) {
        if (v >> 32) return;
        for (int i = 0; i < kProbeCount; ++i)
            if (v == keys[i]) cands.push_back({a, i});
    });
    std::vector<std::pair<uintptr_t, int>> nodes;
    for (auto& [a, i] : cands)
        if (is_node(a, keys[i])) nodes.push_back({a, i});
    if (nodes.empty()) {
        LOGD("texts: no string table nodes yet (%zu candidates, %.1f s)", cands.size(), now_s() - t0);
        return false;
    }

    // 2. what points at them: bucket slots (or the node before them in a chain)
    uintptr_t lo = UINTPTR_MAX, hi = 0;
    for (auto& [a, i] : nodes) lo = std::min(lo, a), hi = std::max(hi, a);
    std::vector<uintptr_t> holders[kProbeCount];
    scan([&](uintptr_t a, uint64_t v) {
        if (v < lo || v > hi) return;
        for (auto& [n, i] : nodes)
            if (v == n) holders[i].push_back(a);
    });

    // 3. the bucket array: slot(key) = buckets + 8 * (key % count) for every probe label
    for (int i = 0; i < kProbeCount; ++i) {
        for (uintptr_t e : holders[i]) {
            for (uint32_t c = 16; c < kMaxBuckets; ++c) {
                uintptr_t b = e - 8ull * (keys[i] % c);
                int agree = 0;
                for (int j = 0; j < kProbeCount; ++j) {
                    if (j == i) continue;
                    uintptr_t want = b + 8ull * (keys[j] % c);
                    if (std::find(holders[j].begin(), holders[j].end(), want) != holders[j].end()) ++agree;
                }
                if (!agree) continue;
                Table t;
                t.buckets = b;
                t.count = c;
                if (!take(t, out)) continue;
                LOGI("texts: string table at %p, %u buckets (slow search: %zu nodes, %.1f s)",
                     reinterpret_cast<void*>(b), c, nodes.size(), now_s() - t0);
                return true;
            }
        }
    }
    LOGW("texts: found %zu label nodes but no table around them (%.1f s)", nodes.size(), now_s() - t0);
    return false;
}

struct Node {
    uint64_t hash;
    uint64_t value;
    uint64_t next;
};

// our nodes, strings and value blocks in one block (kept for the life of the game)
uintptr_t inject(const Table& t) {
    size_t size = 0;
    for (const Text& x : kTexts) size += ((std::strlen(x.text) + 16) & ~size_t(15)) + 32 + 32;
    auto* mem = static_cast<uint8_t*>(VirtualAlloc(nullptr, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
    if (!mem) return 0;
    uint8_t* p = mem;
    uintptr_t first = 0;
    for (const Text& x : kTexts) {
        size_t len = std::strlen(x.text) + 1;
        auto* str = reinterpret_cast<char*>(p);
        std::memcpy(str, x.text, len);
        p += (len + 15) & ~size_t(15);
        uint8_t* value = p;
        std::memcpy(value, t.value_head, 16);
        uint64_t sv[2] = {reinterpret_cast<uint64_t>(str), len};
        std::memcpy(value + 16, sv, 16);
        p += 32;
        auto* node = reinterpret_cast<Node*>(p);
        p += 32;
        uint32_t key = joaat(x.key);
        auto* slot = reinterpret_cast<volatile uint64_t*>(t.buckets + 8ull * (key % t.count));
        node->hash = key;
        node->value = reinterpret_cast<uint64_t>(value);
        node->next = *slot;
        InterlockedExchange64(reinterpret_cast<volatile LONG64*>(slot), LONG64(reinterpret_cast<uint64_t>(node)));
        if (!first) first = reinterpret_cast<uintptr_t>(node);
    }
    return first;
}

void run() {
    Table table;
    uintptr_t ours = 0;                           // our first node
    int misses = 0;
    for (;;) {
        std::this_thread::sleep_for(std::chrono::seconds(ours ? 5 : 2));
        if (ours && find_in(table, joaat(kTexts[0].key)) == ours) continue;     // still linked
        if (ours) LOGI("texts: the game reloaded its string table - adding ours again");
        ours = 0;
        // the table loads during boot; if the quick look keeps failing well after that, search the long way
        bool found = locate_fast(table) || (++misses % 30 == 0 && locate_slow(table));
        if (!found) continue;
        misses = 0;
        ours = inject(table);
        LOGI("texts: %zu texts added", sizeof kTexts / sizeof kTexts[0]);
    }
}

}  // namespace

void text_inject_start() {
    std::thread(run).detach();
}

}  // namespace dsr2
