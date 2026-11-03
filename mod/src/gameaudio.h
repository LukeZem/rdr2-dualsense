// The game's own sounds (AWC banks from lml sound mods) - port of tools/trigger_lab/gameaudio.
#pragma once

#include "common.h"

#include <map>

namespace dsr2 {

struct GameSound {
    std::string bank;
    std::string key;                 // "0x0123ABCD" of the first stream (matches the lab's labels)
    std::vector<uint32_t> ids;
    int rate = 48000;
    std::vector<float> left, right;  // right empty = mono
    std::string auto_role;
    float seconds() const { return left.empty() ? 0.f : float(left.size()) / rate; }
    std::vector<float> mono() const;
};

class GameAudio {
public:
    void discover(const fs::path& game_dir, const fs::path& labels_json);
    bool has_bank(const std::string& bank) const { return paths_.count(bank) != 0 || game_paths_.count(bank) != 0; }
    size_t bank_count(bool weapons_only) const;
    std::vector<std::string> game_files() const;     // what to preload from the game's archives
    const std::vector<GameSound>& sounds(const std::string& bank);
    std::vector<const GameSound*> variants(const std::string& bank, const std::string& role);
    std::string role(const GameSound& s) const;

private:
    std::vector<GameSound> load(const std::string& bank);
    std::map<std::string, fs::path> paths_;          // loose banks of LML sound mods: what the game plays then
    std::map<std::string, std::vector<std::string>> game_paths_;   // the rest: the game's own archives (game_files)
    std::map<std::string, std::vector<GameSound>> cache_;
    std::map<std::string, std::string> labels_;
    std::mutex mu_;
};

}  // namespace dsr2
