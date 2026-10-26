#include "settings_menu.h"

#include "config.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace dsr2 {

namespace {

MenuEntry header(const char* label_key, const char* label) {
    MenuEntry e;
    e.kind = MenuEntry::Header;
    e.label_key = label_key, e.label = label;
    return e;
}
MenuEntry toggle(const char* id, const char* s, const char* k, const char* label_key, const char* label, bool def,
                 const char* help) {
    MenuEntry e;
    e.kind = MenuEntry::Toggle;
    e.id = id, e.section = s, e.key = k, e.label_key = label_key, e.label = label, e.help = help;
    e.def = def ? 1.0f : 0.0f;
    return e;
}
MenuEntry level(const char* id, const char* s, const char* k, const char* label_key, const char* label, float def,
                float max, const char* help) {
    MenuEntry e;
    e.kind = MenuEntry::Number;
    e.id = id, e.section = s, e.key = k, e.label_key = label_key, e.label = label, e.help = help;
    e.def = def, e.min = 0, e.max = max, e.step = 0.1f, e.percent = true;
    return e;
}
MenuEntry choice(const char* id, const char* s, const char* k, const char* label_key, const char* label,
                 const char* def, std::vector<MenuOption> ch, const char* help) {
    MenuEntry e;
    e.kind = MenuEntry::Choice;
    e.id = id, e.section = s, e.key = k, e.label_key = label_key, e.label = label, e.help = help;
    e.choices = std::move(ch);
    for (size_t i = 0; i < e.choices.size(); ++i)
        if (e.choices[i].value == def) e.def = float(i);
    return e;
}

std::string fmt(float v) {
    char b[32];
    snprintf(b, sizeof b, "%.2f", double(v));
    std::string s = b;
    for (auto& c : s) if (c == ',') c = '.';             // whatever the locale says
    while (s.size() > 1 && s.back() == '0') s.pop_back();
    if (!s.empty() && s.back() == '.') s.pop_back();
    return s;
}

}  // namespace

const std::vector<MenuEntry>& SettingsMenu::entries() {
    static const std::vector<MenuEntry> list = {
#include "settings_rows.inc"
    };
    return list;
}

std::string SettingsMenu::value_text(const MenuEntry& e, const Config& c) {
    switch (e.kind) {
    case MenuEntry::Header:
        return "";
    case MenuEntry::Toggle:
        return c.flag(e.section, e.key, e.def > 0.5f) ? "On" : "Off";
    case MenuEntry::Number: {
        float v = c.num(e.section, e.key, e.def);
        if (e.percent) {
            if (v <= 0.001f) return "Off";
            return std::to_string(int(std::lround(v * 100))) + "%";
        }
        return fmt(v);
    }
    case MenuEntry::Choice: {
        std::string v = c.str(e.section, e.key, e.choices.empty() ? "" : e.choices[size_t(e.def)].value);
        for (auto& o : e.choices)
            if (o.value == v) return o.text;
        return v;
    }
    }
    return "";
}

std::string SettingsMenu::stepped(const MenuEntry& e, const Config& c, int dir) {
    switch (e.kind) {
    case MenuEntry::Header:
        return "";
    case MenuEntry::Toggle:
        return c.flag(e.section, e.key, e.def > 0.5f) ? "0" : "1";       // either way flips it
    case MenuEntry::Number: {
        float v = c.num(e.section, e.key, e.def);
        float n = std::round((v + dir * e.step) / e.step) * e.step;
        n = clampv(n, e.min, e.max);
        if (std::fabs(n - v) < 1e-4f) return "";
        return fmt(n);
    }
    case MenuEntry::Choice: {
        if (e.choices.empty()) return "";
        size_t i = size_t(option_index(e, c));
        size_t n = e.choices.size();
        return e.choices[(i + n + (dir < 0 ? n - 1 : 1)) % n].value;
    }
    }
    return "";
}

std::vector<std::string> SettingsMenu::option_labels(const MenuEntry& e) {
    std::vector<std::string> out;
    switch (e.kind) {
    case MenuEntry::Header:
        break;
    case MenuEntry::Toggle:
        out = {"MO_OFF", "MO_ON"};                          // the game's own Off / On
        break;
    case MenuEntry::Number:
        for (int n = 0; n <= int(std::lround(e.max / e.step)); ++n)
            out.push_back("DS_PCT_" + std::to_string(n * 10));
        break;
    case MenuEntry::Choice:
        for (auto& o : e.choices) out.push_back(o.label);
        break;
    }
    return out;
}

int SettingsMenu::option_index(const MenuEntry& e, const Config& c) {
    switch (e.kind) {
    case MenuEntry::Header:
        return 0;
    case MenuEntry::Toggle:
        return c.flag(e.section, e.key, e.def > 0.5f) ? 1 : 0;
    case MenuEntry::Number: {
        int i = int(std::lround(c.num(e.section, e.key, e.def) / e.step));
        return std::clamp(i, 0, int(std::lround(e.max / e.step)));
    }
    case MenuEntry::Choice: {
        if (e.choices.empty()) return 0;
        std::string v = c.str(e.section, e.key, e.choices[size_t(e.def)].value);
        for (size_t k = 0; k < e.choices.size(); ++k)
            if (e.choices[k].value == v) return int(k);
        return int(e.def);
    }
    }
    return 0;
}

std::string SettingsMenu::option_value(const MenuEntry& e, int index) {
    if (index < 0 || index >= int(option_labels(e).size())) return "";
    switch (e.kind) {
    case MenuEntry::Header:
        return "";
    case MenuEntry::Toggle:
        return index ? "1" : "0";
    case MenuEntry::Number:
        return fmt(float(index) * e.step);
    case MenuEntry::Choice:
        return e.choices[size_t(index)].value;
    }
    return "";
}

}  // namespace dsr2
