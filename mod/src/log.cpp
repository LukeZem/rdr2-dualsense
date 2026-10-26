#include "log.h"

#include <windows.h>

#include <cstdio>
#include <mutex>

namespace dsr2::log {

static std::mutex g_mu;
static FILE* g_file = nullptr;
static bool g_debug = false;

void open(const std::wstring& path) {
    std::lock_guard<std::mutex> l(g_mu);
    if (g_file) return;
    g_file = _wfopen(path.c_str(), L"w");
}

void close() {
    std::lock_guard<std::mutex> l(g_mu);
    if (g_file) fclose(g_file);
    g_file = nullptr;
}

void set_debug(bool on) { g_debug = on; }
bool debug_enabled() { return g_debug; }

void write(const char* level, const char* fmt, ...) {
    char msg[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    SYSTEMTIME st;
    GetLocalTime(&st);
    std::lock_guard<std::mutex> l(g_mu);
    FILE* out = g_file ? g_file : stderr;
    fprintf(out, "%02d:%02d:%02d.%03d [%s] %s\n", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, level, msg);
    fflush(out);
}

}  // namespace dsr2::log
