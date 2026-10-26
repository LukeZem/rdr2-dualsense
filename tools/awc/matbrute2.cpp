// Material-name brute force, "<first>_<second>_<index>" and "<line>_<index>":
// usage: matbrute2 <first.txt> <second.txt|-> <max index> <hex target>...
// With second = "-" every line of first.txt is tried as a whole name.
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>

static inline uint32_t step(uint32_t h, const char* s, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        h += uint8_t(s[i]);
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
        if (!w.empty()) v.push_back(w);
    }
    return v;
}

int main(int argc, char** argv) {
    if (argc < 5) return 1;
    auto first = load(argv[1]);
    bool whole = std::string(argv[2]) == "-";
    auto second = whole ? std::vector<std::string>{""} : load(argv[2]);
    int max_index = atoi(argv[3]);
    std::unordered_set<uint32_t> targets;
    for (int i = 4; i < argc; ++i) targets.insert(uint32_t(strtoul(argv[i], nullptr, 16)));
    std::vector<std::string> suffixes;
    for (int i = 0; i <= max_index; ++i) suffixes.push_back("_" + std::to_string(i));
    fprintf(stderr, "%zu x %zu names, index 0..%d\n", first.size(), second.size(), max_index);
    std::mutex out;
    std::atomic<size_t> next{0};
    auto worker = [&]() {
        for (size_t a; (a = next++) < first.size();) {
            uint32_t ha = step(0, first[a].data(), first[a].size());
            if (!whole) ha = step(ha, "_", 1);
            for (const auto& b : second) {
                uint32_t hb = step(ha, b.data(), b.size());
                for (const auto& s : suffixes) {
                    uint32_t x = fin(step(hb, s.data(), s.size()));
                    if (targets.count(x)) {
                        std::lock_guard<std::mutex> l(out);
                        printf("%08X %s%s%s%s\n", x, first[a].c_str(), whole ? "" : "_", b.c_str(), s.c_str());
                        fflush(stdout);
                    }
                }
            }
        }
    };
    std::vector<std::thread> ts;
    for (unsigned i = 0; i < std::max(1u, std::thread::hardware_concurrency()); ++i) ts.emplace_back(worker);
    for (auto& t : ts) t.join();
    fprintf(stderr, "done\n");
}
