// DualSenseRDR2.ini - every feature can be switched and tuned without rebuilding.
#pragma once

#include <map>
#include <shared_mutex>
#include <string>

namespace dsr2 {

class Config {
public:
    // Loads the file; writes the documented default file first if it does not exist.
    bool load(const std::wstring& path);

    std::string str(const std::string& section, const std::string& key, const std::string& def) const;
    float num(const std::string& section, const std::string& key, float def) const;
    int integer(const std::string& section, const std::string& key, int def) const;
    bool flag(const std::string& section, const std::string& key, bool def) const;

    static const char* default_text();
    // Writes one value into the ini file in place (keeps comments, order and everything else), then reloads.
    // Adds the key (and its section) when missing. Call from the thread that reads the config.
    bool set(const std::string& section, const std::string& key, const std::string& value);

private:
    void migrate();                                // older defaults still untouched -> the current ones
    bool migrating_ = false;
    mutable std::shared_mutex mu_;                 // the settings page writes while other threads read
    std::map<std::string, std::string> values_;
    std::wstring path_;   // "section.key" lowercase -> value
};

Config& config();

}  // namespace dsr2
