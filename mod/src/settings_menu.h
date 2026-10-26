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

    // The in-game page. Each row's data store value: toggles 0/1, levels a whole percent (0 .. page_max), choices
    // the index into option_labels (text labels shown by the option stepper; none for levels).
    static constexpr int kPercentStep = 5;                  // one d-pad press on a level (the stick goes by 1%)
    static std::vector<std::string> option_labels(const MenuEntry& e);
    static int page_max(const MenuEntry& e);
    static int page_value(const MenuEntry& e, const Config& c);
    static std::string page_ini(const MenuEntry& e, int v);   // the ini value for a page value; "" = invalid
};

}  // namespace dsr2
