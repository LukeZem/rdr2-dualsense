// What Arthur (or his horse) is standing on.
// RAGE names a ground material by joaat("<name>_<its line in materials.dat>"), e.g. "mud_soft_39" (found by
// matching GTA V's published material hashes: "default_0", "concrete_1"...). So the material hash the game
// gives us is identified by trying known material names with every line number, then mapped to a surface:
//   1. wading = water
//   2. labels you taught in game (F10 cycles the label of the ground under you) -> DualSenseRDR2/materials.json
//   3. the identified material name (mud_soft -> mud, pine_needles -> grass, wood_roof -> wood...)
//   4. context: indoors = wooden floor, snow on the ground = snow
//   5. otherwise plain ground
#pragma once

#include "common.h"

#include <map>
#include <memory>
#include <mutex>
#include <set>

namespace dsr2 {

class Surfaces {
public:
    static const std::vector<std::string>& labels();   // ground grass mud stone gravel wood snow sand water
    void load(const fs::path& json);
    // a material seen for the first time is identified in the background (a few ms); until then: context
    std::string classify(uint32_t material, bool indoors, float submerged, float snow_level);
    // the label after `current` for this material (back to the identified one = untaught), saves, returns it
    std::string teach(uint32_t material, const std::string& current);
    bool taught(uint32_t material) const { return taught_.count(material) != 0; }
    std::string name_of(uint32_t material) const;       // "mud_soft_39", "" = unknown / not identified yet

    static std::string identify(uint32_t material);     // blocking search: "mud_soft_39" or ""
    static std::string label_for(const std::string& name);

private:
    void save() const;
    fs::path path_;
    std::map<uint32_t, std::string> taught_;
    struct Found {
        std::mutex mu;
        std::map<uint32_t, std::string> names;           // "" = searched, no match
    };
    std::shared_ptr<Found> found_ = std::make_shared<Found>();
    std::set<uint32_t> asked_;
};

}  // namespace dsr2
