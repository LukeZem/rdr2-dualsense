#include "surfaces.h"

#include "log.h"

#include <fstream>
#include <thread>

#include "../third_party/json.hpp"

namespace dsr2 {

namespace {

// Material names: the ones seen in RDR2 so far (with their line: default 0, gravel_small 26, gravel_dirt 32,
// gravel_grass 33, dirt_track 34, dirt_grass 36, mud_hard 37, mud_soft 39, mud_deep 41, clay_hard 46,
// grass_dead 53, grass 56, grass_short 57, pine_needles 63, leaves_dry 64, wood_roof 91, wood_solid_medium 96),
// RDR2's material groups (from the game's exe) and GTA V's materials.dat.
const char* const kNames[] = {
    "default", "gravel_small", "gravel_dirt", "gravel_grass", "dirt_track", "dirt_grass", "mud_hard", "mud_soft",
    "mud_deep", "clay_hard", "grass_dead", "grass", "grass_short", "pine_needles", "leaves_dry", "wood_roof",
    "wood_solid_medium", "generic", "concrete", "tarmac", "stone", "stone_dirt", "brick", "marble", "paving",
    "sandstone", "sandstone_brittle", "sand_compact", "sand_dry_deep", "sand_wet", "sand_wet_deep", "quicksand",
    "tar_pit", "ice", "snow_loose", "snow_compact", "slush", "gravel", "gravel_large", "gravel_deep", "gravel_muddy",
    "gravel_muddy_deep", "dirt_dry", "dirt_dry_deep", "soil", "soil_deep", "mud_underwater", "clay", "manure",
    "marsh", "marsh_deep", "ash", "coal", "grass_lush", "hay", "bushes", "bushes_sparse", "bushes_dense",
    "tree_bark", "tree_pine", "tree_pine_snow", "leaves", "leaves_maple", "leaves_oak", "leaves_ficus",
    "leaves_tobacco", "crop_husk", "moss", "twigs", "cactus", "metal", "metal_thin", "metal_solid_small", "wood",
    "wood_dusty", "wood_polished", "wood_splinter", "wood_burning", "wood_burnt", "wood_shoot_through",
    "wood_rotten", "wood_solid_small", "ceramic", "terracotta", "cloth", "carpet_fabric", "carpet_fabric_dusty",
    "plastic", "plastic_hollow", "rubber", "plaster_brittle", "paper", "feathers", "wicker", "hemp_sack", "leather",
    "glass", "puddle", "liquid_water", "liquid_blood", "liquid_mud", "liquid_snow", "liquid_sand", "sand", "dirt",
    "water", "foliage", "snow", "stairs", "road_road", "road_path", "road_trail", "roof", "concrete_pothole",
    "concrete_dusty", "tarmac_painted", "tarmac_pothole", "rumble_strip", "breeze_block", "rock", "rock_mossy",
    "cobblestone", "paving_slab", "sandstone_solid", "sand_loose", "sand_track", "sand_underwater", "ice_tarmac",
    "snow_deep", "snow_tarmac", "gravel_train_track", "mud_pothole", "clay_soft", "grass_long", "woodchips",
    "metal_solid_medium", "metal_solid_large", "metal_hollow_small", "metal_hollow_medium", "metal_hollow_large",
    "metal_chain_link_small", "metal_chain_link_large", "metal_corrugated_iron", "metal_grille", "metal_railing",
    "metal_duct", "metal_garage_door", "metal_manhole", "wood_solid_large", "wood_solid_polished",
    "wood_floor_dusty", "wood_hollow_small", "wood_hollow_medium", "wood_hollow_large", "wood_chipboard",
    "wood_old_creaky", "wood_high_density", "wood_lattice", "roof_tile", "roof_felt", "tarpaulin", "linoleum",
    "laminate", "carpet_solid", "carpet_solid_dusty", "carpet_floorboard", "plaster_solid", "cardboard_sheet",
    "cardboard_box", "glass_opaque", "concrete_pavement", "brick_pavement", "wood_high_friction", "rock_noinst",
    "bushes_noinst",
};
// two-word names not listed above: "<base>_<modifier>" (pine_needles, leaves_dry, wood_roof are of this shape)
const char* const kBases[] = {
    "dirt", "mud", "gravel", "grass", "sand", "snow", "ice", "rock", "stone", "wood", "clay", "soil", "leaves",
    "pine", "moss", "bushes", "hay", "marsh", "water", "metal", "concrete", "brick", "cobblestone", "tarmac",
    "plaster", "carpet", "road", "tree", "twigs", "straw", "manure", "ash", "coal", "crop", "slush", "tar",
    "sandstone", "marble", "paving", "ceramic", "glass", "cloth", "roof", "stairs",
};
const char* const kMods[] = {
    "small", "medium", "large", "deep", "shallow", "dry", "wet", "dusty", "polished", "splinter", "burning",
    "burnt", "rotten", "solid", "hollow", "thin", "thick", "loose", "compact", "hard", "soft", "muddy", "sparse",
    "dense", "lush", "dead", "short", "long", "tall", "brittle", "fabric", "old", "creaky", "floor", "roof",
    "plank", "planks", "board", "boards", "beam", "deck", "porch", "bridge", "track", "road", "path", "trail",
    "rail", "pothole", "underwater", "snow", "frozen", "icy", "mossy", "grass", "dirt", "gravel", "mud", "sand",
    "rock", "stone", "wood", "metal", "painted", "rough", "smooth", "needles", "leaves", "twigs", "straw", "hay",
    "manure", "pebbles", "sheet", "tile", "tiles", "floorboard", "floorboards", "dirty", "clean", "fine", "coarse",
    "rocky", "sandy", "grassy", "snowy", "rutted", "packed", "fresh",
};
constexpr int kMaxLine = 400;

// joaat in two halves: the name once, then each "_<line>" ending
inline uint32_t oaat_add(uint32_t h, const char* s, size_t n) {
    for (size_t i = 0; i < n; ++i) {
        h += uint8_t(s[i]);
        h += h << 10;
        h ^= h >> 6;
    }
    return h;
}
inline uint32_t oaat_end(uint32_t h) {
    h += h << 3;
    h ^= h >> 11;
    h += h << 15;
    return h;
}

struct Endings {
    std::vector<std::string> s;
    Endings() {
        for (int i = 0; i <= kMaxLine; ++i) s.push_back("_" + std::to_string(i));
    }
};

int find_line(uint32_t target, uint32_t name_state, const Endings& e) {
    for (size_t i = 0; i < e.s.size(); ++i)
        if (oaat_end(oaat_add(name_state, e.s[i].data(), e.s[i].size())) == target) return int(i);
    return -1;
}

std::vector<std::string> tokens(const std::string& name) {
    std::vector<std::string> t;
    size_t a = 0;
    for (size_t b; (b = name.find('_', a)) != std::string::npos; a = b + 1) t.push_back(name.substr(a, b - a));
    t.push_back(name.substr(a));
    if (!t.empty() && !t.back().empty() && std::all_of(t.back().begin(), t.back().end(), ::isdigit)) t.pop_back();
    return t;
}

}  // namespace

std::string Surfaces::identify(uint32_t m) {
    static const Endings endings;
    for (const char* n : kNames) {
        int line = find_line(m, oaat_add(0, n, strlen(n)), endings);
        if (line >= 0) return std::string(n) + endings.s[line];
    }
    for (const char* b : kBases) {
        uint32_t hb = oaat_add(oaat_add(0, b, strlen(b)), "_", 1);
        for (const char* d : kMods) {
            int line = find_line(m, oaat_add(hb, d, strlen(d)), endings);
            if (line >= 0) return std::string(b) + "_" + d + endings.s[line];
        }
    }
    return "";
}

std::string Surfaces::label_for(const std::string& name) {
    auto t = tokens(name);
    if (t.empty() || t[0].empty()) return "ground";
    auto has = [&](const char* w) { return std::find(t.begin(), t.end(), w) != t.end(); };
    auto first = [&](std::initializer_list<const char*> ws) {
        for (const char* w : ws) if (t[0] == w) return true;
        return false;
    };
    if (has("underwater") || first({"water", "puddle"}) || (t[0] == "liquid" && t.size() > 1 && t[1] == "water"))
        return "water";
    if (first({"snow", "ice", "slush"}) || (t[0] == "liquid" && has("snow"))) return "snow";
    if (first({"mud", "marsh", "manure", "quicksand", "tar"}) || (t[0] == "liquid" && has("mud")) ||
        (t[0] == "clay" && has("soft"))) {
        return t[0] == "mud" && has("hard") ? "ground" : "mud";   // dried hard mud walks like dirt
    }
    if (first({"sand"}) || (t[0] == "liquid" && has("sand"))) return "sand";
    if (first({"gravel", "pebbles", "scree"})) return "gravel";
    if (first({"rock", "stone", "concrete", "tarmac", "brick", "marble", "paving", "sandstone", "cobblestone",
               "ceramic", "terracotta", "metal", "plaster", "glass", "breeze", "rumble"}) ||
        (t[0] == "roof" && has("tile")))
        return "stone";
    if (first({"wood", "woodchips", "plank", "planks", "stairs", "roof", "tree", "laminate"})) return "wood";
    if (first({"grass", "hay", "bushes", "moss", "leaves", "pine", "twigs", "crop", "foliage", "cactus", "straw"}))
        return "grass";
    return "ground";    // dirt, soil, clay, ash, coal, roads, carpet, cloth, default...
}

const std::vector<std::string>& Surfaces::labels() {
    static const std::vector<std::string> l = {"ground", "grass", "mud", "stone", "gravel", "wood", "snow", "sand", "water"};
    return l;
}

void Surfaces::load(const fs::path& json) {
    path_ = json;
    taught_.clear();
    std::ifstream in(json);
    if (!in) return;
    try {
        nlohmann::json j = nlohmann::json::parse(in);
        for (auto& [k, v] : j.items()) taught_[uint32_t(std::stoul(k, nullptr, 16))] = v.get<std::string>();
        LOGI("surfaces: %zu taught materials", taught_.size());
    } catch (const std::exception& e) {
        LOGW("materials.json: %s", e.what());
    }
}

void Surfaces::save() const {
    nlohmann::json j = nlohmann::json::object();
    for (auto& [h, l] : taught_) {
        char k[16];
        snprintf(k, sizeof k, "0x%08X", h);
        j[k] = l;
    }
    std::ofstream out(path_);
    out << j.dump(2);
}

std::string Surfaces::name_of(uint32_t m) const {
    std::lock_guard<std::mutex> l(found_->mu);
    auto it = found_->names.find(m);
    return it == found_->names.end() ? "" : it->second;
}

std::string Surfaces::classify(uint32_t m, bool indoors, float submerged, float snow) {
    if (submerged > 0.05f) return "water";
    auto it = taught_.find(m);
    if (it != taught_.end()) return it->second;
    std::string name;
    if (m) {
        if (asked_.insert(m).second) {
            std::thread([found = found_, m] {
                std::string n = identify(m);
                std::string label = n.empty() ? "" : label_for(n);
                LOGD("ground material 0x%08X = %s -> %s", m, n.empty() ? "(unknown)" : n.c_str(),
                     n.empty() ? "context / F10" : label.c_str());
                std::lock_guard<std::mutex> l(found->mu);
                found->names[m] = n;
            }).detach();
        }
        name = name_of(m);
    }
    bool generic = name.empty() || name.rfind("default_", 0) == 0 || name.rfind("generic_", 0) == 0;
    std::string label = generic ? "" : label_for(name);
    if (!indoors && snow > 0.3f && label != "wood" && label != "water") return "snow";
    if (!label.empty()) return label;
    if (indoors) return "wood";              // RDR2 interiors: almost always floorboards
    return "ground";
}

std::string Surfaces::teach(uint32_t m, const std::string& current) {
    const auto& l = labels();
    auto pos = std::find(l.begin(), l.end(), current);
    size_t i = pos == l.end() ? 0 : (size_t(pos - l.begin()) + 1) % l.size();
    std::string name = name_of(m);
    std::string automatic = name.empty() ? "ground" : label_for(name);
    if (l[i] == automatic) taught_.erase(m);
    else taught_[m] = l[i];
    save();
    LOGI("surface 0x%08X (%s) taught as %s", m, name.empty() ? "unknown" : name.c_str(), l[i].c_str());
    return l[i];
}

}  // namespace dsr2
