// DualSenseRDR2.asi - loaded by the ASI loader, runs a ScriptHookRDR2 script for game state.
#include "common.h"
#include "core.h"
#include "log.h"
#include "shv.h"
#include "text_inject.h"

#include <thread>

static HMODULE g_module = nullptr;

namespace dsr2 {
fs::path module_dir() {
    wchar_t path[MAX_PATH];
    GetModuleFileNameW(g_module, path, MAX_PATH);
    return fs::path(path).parent_path();
}
}  // namespace dsr2

static void script_main() {
    while (true) {
        try {
            dsr2::core().script_tick();
        } catch (const std::exception& e) {
            LOGE("script tick: %s", e.what());
        }
        shv_scriptWait(0);
    }
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_module = module;
        DisableThreadLibraryCalls(module);
        dsr2::log::open((dsr2::module_dir() / "DualSenseRDR2.log").wstring());
        LOGI("DualSense for RDR2 %s - loading", dsr2::kVersion);
        // Controller, audio and the XInput hook start right away (menus work too);
        // game state comes from the ScriptHook script once a save is loaded.
        std::thread([] { dsr2::core().init(true); }).detach();
        dsr2::text_inject_start();       // our Settings texts, in the game's own string table
        shv_scriptRegister(module, script_main);
    } else if (reason == DLL_PROCESS_DETACH) {
        shv_scriptUnregister(module);
    }
    return TRUE;
}
