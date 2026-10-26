// DualSenseRDR2.ini - every feature can be switched and tuned without rebuilding.
#pragma once

#include <map>
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

private:
    std::map<std::string, std::string> values_;   // "section.key" lowercase -> value
};

Config& config();

}  // namespace dsr2
