// Sound-name brute force for AWC banks (stream ids = joaat(name) & 0x1FFFFFFF).
// Names look like "revolver_draw2", "pistol_impact_01": <prefix><word><number>.
// usage: sndbrute <ids.txt> <prefixes.txt> <words.txt>
// Prints every base ("<prefix><word>") that hits two or more ids with different numbers - a real series,
// which random collisions practically never produce.
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>

static inline uint32_t step(uint32_t h, const char* s, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        uint8_t c = uint8_t(s[i]);
        if (c >= 'A' && c <= 'Z') c += 32;
        h += c;
        h += h << 10;
        h ^= h >> 6;
    }
    return h;
}
static inline uint32_t fin(uint32_t h) {
    h += h << 3;
    h ^= h >> 11;
    h += h << 15;
    return h;
}
static std::vector<std::string> load(const char* p) {
    std::vector<std::string> v;
    std::ifstream f(p);
    for (std::string w; std::getline(f, w);) {
        while (!w.empty() && (w.back() == '\r' || w.back() == ' ')) w.pop_back();
        v.push_back(w);     // empty line = empty prefix
    }
    return v;
}

int main(int argc, char** argv) {
    if (argc < 4) return 1;
    std::unordered_set<uint32_t> ids;
    {
        std::ifstream f(argv[1]);
        for (std::string w; f >> w;) ids.insert(uint32_t(std::stoul(w, nullptr, 16)) & 0x1FFFFFFF);
    }
    auto prefixes = load(argv[2]);
    auto words = load(argv[3]);
    std::vector<std::string> nums;
    for (int i = 0; i <= 30; ++i) {
        nums.push_back(std::to_string(i));
        nums.push_back("_" + std::to_string(i));
        char b[8];
        snprintf(b, sizeof b, "_%02d", i);
        nums.push_back(b);
        snprintf(b, sizeof b, "%02d", i);
        nums.push_back(b);
    }
    fprintf(stderr, "%zu ids, %zu prefixes x %zu words x %zu numbers\n", ids.size(), prefixes.size(), words.size(), nums.size());
    std::mutex mu;
    std::atomic<size_t> next{0};
    auto worker = [&]() {
        for (size_t a; (a = next++) < prefixes.size();) {
            uint32_t hp = step(0, prefixes[a].data(), prefixes[a].size());
            for (const auto& w : words) {
                if (w.empty()) continue;
                uint32_t hw = step(hp, w.data(), w.size());
                std::vector<std::string> hits;
                std::unordered_set<uint32_t> seen;
                for (const auto& n : nums) {
                    uint32_t x = fin(step(hw, n.data(), n.size())) & 0x1FFFFFFF;
                    if (ids.count(x) && seen.insert(x).second) hits.push_back(n);
                }
                if (hits.size() >= 2) {
                    std::lock_guard<std::mutex> l(mu);
                    printf("%s%s:", prefixes[a].c_str(), w.c_str());
                    for (auto& h : hits) printf(" %s", h.c_str());
                    printf("\n");
                    fflush(stdout);
                }
            }
        }
    };
    std::vector<std::thread> ts;
    for (unsigned i = 0; i < std::max(1u, std::thread::hardware_concurrency()); ++i) ts.emplace_back(worker);
    for (auto& t : ts) t.join();
    fprintf(stderr, "done\n");
}
