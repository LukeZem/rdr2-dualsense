// Weapon catalog (weapons.json): classes + every weapon; resolved profiles keyed by the game's weapon hash.
#pragma once

#include "common.h"

#include <map>

#include "../third_party/json.hpp"

namespace dsr2 {

class Catalog {
public:
    bool load(const fs::path& weapons_json);
    // Profile for a weapon the game reports. Unknown hashes fall back to the weapon group.
    nlohmann::json resolve(uint32_t weapon_hash, uint32_t group_hash, std::string& name_out) const;
    nlohmann::json resolve_name(const std::string& name) const;

private:
    nlohmann::json raw_;
    std::map<uint32_t, std::string> by_hash_;
};

nlohmann::json deep_merge(nlohmann::json base, const nlohmann::json& over);

}  // namespace dsr2
