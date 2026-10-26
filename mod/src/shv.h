// ScriptHookRDR2 binding (imports resolved through scripthook/ScriptHookRDR2.def) and native calls.
#pragma once

#include <windows.h>

#include <cstdint>
#include <cstring>
#include <type_traits>

extern "C" {
void shv_scriptRegister(HMODULE module, void (*main)());
void shv_scriptRegisterAdditionalThread(HMODULE module, void (*main)());
void shv_scriptUnregister(HMODULE module);
void shv_scriptWait(DWORD ms);
void shv_nativeInit(uint64_t hash);
void shv_nativePush64(uint64_t value);
uint64_t* shv_nativeCall();
int shv_worldGetAllPeds(int* arr, int size);
}

namespace dsr2::shv {

using Ped = int;
using Player = int;
using Entity = int;
using Hash = uint32_t;

#pragma pack(push, 1)
struct Vector3 {
    float x; DWORD _px;
    float y; DWORD _py;
    float z; DWORD _pz;
};
#pragma pack(pop)

template <typename T>
inline void push(T v) {
    static_assert(sizeof(T) <= 8, "native args are at most 64 bit");
    uint64_t raw = 0;
    std::memcpy(&raw, &v, sizeof(T));
    shv_nativePush64(raw);
}

template <typename R, typename... Args>
inline R invoke(uint64_t hash, Args... args) {
    shv_nativeInit(hash);
    (push(args), ...);
    uint64_t* result = shv_nativeCall();
    if constexpr (std::is_void_v<R>) {
        (void)result;
    } else {
        R out;
        std::memcpy(&out, result, sizeof(R));
        return out;
    }
}

}  // namespace dsr2::shv
