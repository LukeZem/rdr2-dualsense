// Files from the game's own archives (mounted and decrypted by the game), through its file device layer:
// e.g. "audio:/sfx/RDR3.Resident/weapons.awc" - works with or without LML, no keys needed. See game_files.cpp.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace dsr2::game_files {

// SCRIPT THREAD ONLY, at the first script tick (the archives are mounted by then): reads these files into memory.
// The game's file layer needs a game thread - called from one of our own threads it crashes the game.
void preload(const std::vector<std::string>& paths);
bool ready();
// any thread: hands over a preloaded file (once); empty = not there / not preloaded yet
std::vector<uint8_t> take(const std::string& path);

}  // namespace dsr2::game_files
