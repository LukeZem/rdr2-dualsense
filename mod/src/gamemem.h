// Read-only views into the game's audio state, found by disassembling RDR2.exe (2026-11, see
// tools/awc/*.py and the research notes in world.cpp). Every root is found by a code signature at start-up (never
// a hard-coded address); every read goes through ReadProcessMemory (fails instead of crashing); a root that is
// not found turns its feature off.
//
// Speech (what a ped is saying, exactly): ped object +0x9C (& 0x1FFFF) minus u32 [lo] indexes the audio entity
// table [tab] (0x148 bytes each); entry +comp -> object A (low bit is a flag); A+flag & 2; [A+0x98]+mgr -> the
// ped's speech manager: +0x78 array of speech requests, +0x80 their count (u16). Request: +0x214 type
// (1 ambient, 2 scripted, 3 vocalization, 4 animal), +0x234 state (5 playing), +0x1D8 the sound. Sound: +0x110 voice
// hash, +0x114 the context hash before joaat's last mixing step, +0x118 variation -> the recording
// (awc::line_stream_id). Signature: the IS_*_SPEECH_PLAYING helpers (11 copies, all must agree).
//
// Cutscene audio (which file, where it is): RAGE's sound pool, [G+0x10] base / [G+0x8] size, G from the sound base
// class destructor's pool lookup (3 copies, must agree). A cutscene stem's sound has its play position (u32 ms)
// at +0x114 and its channel id (low 29 bits; top bits = a mixer slot) at +0x118. The position runs ~60 ms ahead of
// what leaves the PC (measured against loopback recordings).
#pragma once

#include "common.h"

#include <vector>

namespace dsr2::gamemem {

bool init();                     // once; true if anything was found
bool speech_ok();
bool pool_ok();

bool read(uintptr_t a, void* out, size_t n);
template <class T> bool read(uintptr_t a, T& v) { return a && read(a, &v, sizeof v); }

struct Request {
    uintptr_t addr = 0, sound = 0;
    uint32_t type = 0, state = 0;
    uint32_t voice = 0, partial = 0, variation = 0;
};
// the speech requests of a ped (its game object, from the script handle); false = none / not readable
bool ped_requests(const void* ped_object, std::vector<Request>& out);

struct Stem {
    uintptr_t field = 0;          // address of the u32 play position (ms)
    uint32_t ms = 0, id = 0;      // id: the channel id (29 bits)
};
// every sound in the pool whose channel id passes `known` (cutscene stems, live or finished)
void pool_stems(const std::function<bool(uint32_t)>& known, std::vector<Stem>& out);

// The game's XInput pad slots (4 pads, 0x180 bytes each): byte +0x11C = "a pad is in this slot". The game polls
// only marked slots, and checks the empty ones (one XInputGetState each) only when Windows reports a device change
// - which comes when the cable goes in, before our controller is open: a late controller stayed unseen. So the mod
// marks the slot itself, as that check would have (the one write into the game). Signatures: that check (window
// procedure, WM_DEVICECHANGE / DBT_DEVNODES_CHANGED) and the per-frame update of the marked slots - must agree.
int pad_slot_marked(int slot);   // 1 / 0, -1 = slots not found
bool mark_pad_slot(int slot);

}  // namespace dsr2::gamemem
