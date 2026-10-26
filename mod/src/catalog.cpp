#include "catalog.h"

#include "log.h"

#include <fstream>

namespace dsr2 {

using nlohmann::json;

json deep_merge(json base, const json& over) {
    if (!over.is_object()) return base;
    for (auto& [k, v] : over.items()) {
        if (v.is_object() && base.contains(k) && base[k].is_object()) base[k] = deep_merge(base[k], v);
        else base[k] = v;
    }
    return base;
}

bool Catalog::load(const fs::path& path) {
    std::ifstream in(path);
    try {
        raw_ = json::parse(in);
    } catch (const std::exception& e) {
        LOGE("weapons.json: %s", e.what());
        raw_ = json::object();
        return false;
    }
    by_hash_.clear();
    for (auto& w : raw_.value("weapons", json::array())) {
        std::string name = w.value("name", "");
        if (!name.empty()) by_hash_[joaat(name)] = name;
    }
    LOGI("catalog: %zu weapons, %zu classes", by_hash_.size(), raw_.value("classes", json::object()).size());
    return true;
}

json Catalog::resolve_name(const std::string& name) const {
    for (auto& w : raw_.value("weapons", json::array())) {
        if (w.value("name", "") != name) continue;
        std::string cls = w.value("class", "");
        json prof = raw_["classes"].value(cls, json::object());
        json meta = w;
        meta.erase("tune");
        prof = deep_merge(prof, meta);
        prof = deep_merge(prof, w.value("tune", json::object()));
        prof["id"] = name;
        return prof;
    }
    return json();
}

json Catalog::resolve(uint32_t hash, uint32_t group, std::string& name_out) const {
    auto it = by_hash_.find(hash);
    if (it != by_hash_.end()) {
        name_out = it->second;
        return resolve_name(it->second);
    }
    // unknown weapon: behave like a typical member of its group
    static const std::pair<const char*, const char*> groups[] = {
        {"GROUP_REVOLVER", "WEAPON_REVOLVER_CATTLEMAN"}, {"GROUP_PISTOL", "WEAPON_PISTOL_SEMIAUTO"},
        {"GROUP_REPEATER", "WEAPON_REPEATER_CARBINE"}, {"GROUP_RIFLE", "WEAPON_RIFLE_BOLTACTION"},
        {"GROUP_SNIPER", "WEAPON_SNIPERRIFLE_ROLLINGBLOCK"}, {"GROUP_SHOTGUN", "WEAPON_SHOTGUN_PUMP"},
        {"GROUP_BOW", "WEAPON_BOW"}, {"GROUP_THROWN", "WEAPON_THROWN_TOMAHAWK"}, {"GROUP_MELEE", "WEAPON_MELEE_KNIFE"},
        {"GROUP_UNARMED", "WEAPON_UNARMED"}, {"GROUP_LASSO", "WEAPON_LASSO"}, {"GROUP_FISHINGROD", "WEAPON_FISHINGROD"},
        {"GROUP_HEAVY", "WEAPON_TURRET_GATLING"}, {"GROUP_MG", "WEAPON_TURRET_GATLING"},
    };
    for (auto& [g, w] : groups) {
        if (joaat(g) == group) {
            name_out = std::string(w) + " (group fallback)";
            json p = resolve_name(w);
            if (!p.is_null()) p["id"] = name_out;
            return p;
        }
    }
    name_out = "";
    return json();
}

}  // namespace dsr2
