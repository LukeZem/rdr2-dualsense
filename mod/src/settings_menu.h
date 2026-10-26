// The mod's settings as the in-game "DualSense" page shows them: what it lists, how each value reads and how
// the page's option steppers map to ini values. Pure logic over the ini (Config); the list itself is generated
// (settings_rows.inc) from the same source as the page (tools/rpf8/dualsense_settings.py).
#pragma once

#include "common.h"

namespace dsr2 {

class Config;

struct MenuOption {
    std::string value;                                      // in the ini
    std::string text;                                       // shown
    std::string label;                                      // text label on the page
};

struct MenuEntry {
    enum Kind { Header, Toggle, Number, Choice };
    Kind kind = Toggle;
    const char* id = "";                                    // the page's data store name
    const char* section = "";
    const char* key = "";
    const char* label_key = "";                             // text label on the page
    const char* label = "";
    const char* help = "";
    float def = 0, min = 0, max = 1, step = 0.1f;
    bool percent = false;                                   // show 0.6 as "60%"
    std::vector<MenuOption> choices;
};

class SettingsMenu {
public:
    static const std::vector<MenuEntry>& entries();
    // text shown on the right of a row ("On", "60%", "Aim only")
    static std::string value_text(const MenuEntry& e, const Config& c);
    // the ini value after one press left (dir -1) or right (+1); empty = nothing changes
    static std::string stepped(const MenuEntry& e, const Config& c, int dir);

    // the page's option stepper: text labels of its options, the option the ini value is on
    // (numbers: the nearest 10% step), and the ini value for an option ("" = out of range)
    static std::vector<std::string> option_labels(const MenuEntry& e);
    static int option_index(const MenuEntry& e, const Config& c);
    static std::string option_value(const MenuEntry& e, int index);
};

}  // namespace dsr2
