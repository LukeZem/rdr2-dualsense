// Material-name brute force: RAGE material hashes are joaat("<name>_<index in materials.dat>").
// usage: matbrute <vocab.txt> <max words> <max index> <hex target>...
// Prints every "<w1>_<w2>..._<index>" whose hash is a target.
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

int main(int argc, char** argv) {
    if (argc < 5) return 1;
    std::vector<std::string> words;
    std::ifstream f(argv[1]);
    for (std::string w; f >> w;) words.push_back(w);
    int max_words = atoi(argv[2]), max_index = atoi(argv[3]);
    std::unordered_set<uint32_t> targets;
    for (int i = 4; i < argc; ++i) targets.insert(uint32_t(strtoul(argv[i], nullptr, 16)));
    std::vector<std::string> suffixes;
    for (int i = 0; i <= max_index; ++i) suffixes.push_back("_" + std::to_string(i));
    size_t W = words.size();
    fprintf(stderr, "%zu words, up to %d words, index 0..%d, %zu targets\n", W, max_words, max_index, targets.size());

    std::mutex out;
    auto finish = [&](uint32_t h, const std::string& name) {
        for (size_t i = 0; i < suffixes.size(); ++i) {
            uint32_t x = fin(step(h, suffixes[i].data(), suffixes[i].size()));
            if (targets.count(x)) {
                std::lock_guard<std::mutex> l(out);
                printf("%08X %s%s\n", x, name.c_str(), suffixes[i].c_str());
                fflush(stdout);
            }
        }
    };
    std::atomic<size_t> next{0};
    auto worker = [&]() {
        for (size_t a; (a = next++) < W;) {
            const std::string& wa = words[a];
            uint32_t ha = step(0, wa.data(), wa.size());
            finish(ha, wa);
            if (max_words < 2) continue;
            for (size_t b = 0; b < W; ++b) {
                std::string nb = wa + "_" + words[b];
                uint32_t hb = step(step(ha, "_", 1), words[b].data(), words[b].size());
                finish(hb, nb);
                if (max_words < 3) continue;
                uint32_t hb_ = step(hb, "_", 1);
                for (size_t c = 0; c < W; ++c) {
                    uint32_t hc = step(hb_, words[c].data(), words[c].size());
                    // cheap pre-check is not possible with joaat, so test all suffixes
                    for (size_t i = 0; i < suffixes.size(); ++i) {
                        uint32_t x = fin(step(hc, suffixes[i].data(), suffixes[i].size()));
                        if (targets.count(x)) {
                            std::lock_guard<std::mutex> l(out);
                            printf("%08X %s_%s%s\n", x, nb.c_str(), words[c].c_str(), suffixes[i].c_str());
                            fflush(stdout);
                        }
                    }
                }
            }
        }
    };
    std::vector<std::thread> ts;
    unsigned n = std::max(1u, std::thread::hardware_concurrency());
    for (unsigned i = 0; i < n; ++i) ts.emplace_back(worker);
    for (auto& t : ts) t.join();
    fprintf(stderr, "done\n");
}
