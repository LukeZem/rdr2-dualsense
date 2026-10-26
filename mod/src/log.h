// Thread-safe file logger: <game>/DualSenseRDR2.log
#pragma once

#include <cstdarg>
#include <string>

namespace dsr2::log {

void open(const std::wstring& path);
void close();
void write(const char* level, const char* fmt, ...);
void set_debug(bool on);
bool debug_enabled();

}  // namespace dsr2::log

#define LOGI(...) ::dsr2::log::write("INFO", __VA_ARGS__)
#define LOGW(...) ::dsr2::log::write("WARN", __VA_ARGS__)
#define LOGE(...) ::dsr2::log::write("ERROR", __VA_ARGS__)
#define LOGD(...) do { if (::dsr2::log::debug_enabled()) ::dsr2::log::write("DEBUG", __VA_ARGS__); } while (0)
