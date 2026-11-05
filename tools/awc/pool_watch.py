"""Read-only, from outside the game: watch RAGE's sound pool for playing cutscene audio.
  pool: base u64 [exe+0x53588E8], size u64 [exe+0x53588E0] (8 buckets of sound slots; found from the audSound
  destructor). A cutscene stem's stream state = {u32 position ms, u32 channel id | flags in the top 3 bits, ...};
  channel ids come from the cutscene .awc files (cutscene_channels.json: id -> [file, stem, seconds]).
Polls the pool (~10 ms), logs every change of a stem's position with its object's vtable, plus the anim scene
clocks (scene map [exe+0x5BD41B8], time at scene+0x180). Output: CSV lines on stdout.
Usage: pool_watch.py <seconds> [channels.json]
"""
import ctypes
import json
import struct
import sys
import time
from datetime import datetime

import numpy as np

from livemem import h, k32, EXE, rd, q  # noqa: E402

BASE_VT = 0x360DC28


def scenes():
    m = q(EXE + 0x5BD41B8)
    bk, nb = q(m + 8), struct.unpack("<I", rd(m + 0x10, 4))[0]
    out = []
    for i in range(min(nb, 4096)):
        n = q(bk + 8 * i)
        for _ in range(64):
            if not n:
                break
            hd, obj = struct.unpack("<I", rd(n, 4))[0], q(n + 8)
            if obj:
                tb = rd(obj + 0x180, 4)
                out.append((hd, struct.unpack("<f", tb)[0] if tb else -1))
            n = q(n + 0x10)
    return out


def main(seconds, chans_path="cutscene_channels.json"):
    chans = json.load(open(chans_path))
    ids = np.array(sorted(int(k, 16) for k in chans), dtype=np.uint32)
    base, size = q(EXE + 0x53588E8), q(EXE + 0x53588E0)
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    u32 = np.frombuffer(buf, dtype=np.uint32)
    last = {}
    dumped = {}
    last_scene = 0
    print("time,kind,addr,file,stem,ms,flags,vtable_rva,obj_off,extra", flush=True)
    end = time.time() + seconds
    while time.time() < end:
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
            time.sleep(0.5)
            continue
        now = time.time()
        stamp = datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]
        key = u32 & np.uint32(0x1FFFFFFF)
        hit = np.flatnonzero(np.isin(key, ids))
        live = False
        for i in hit:
            if i == 0:
                continue
            cid = "%08X" % int(key[i])
            f, stem, total = chans[cid]
            ms = int(u32[i - 1])
            if ms > total * 1000 + 2000:
                continue
            addr = base + 4 * (i - 1)
            if last.get(addr) == ms:
                continue
            # containing object: nearest exe pointer before the field (vtable)
            vt, oo = 0, 0
            for o in range(4 * (i - 1) // 8 * 8, max(0, 4 * (i - 1) - 0x1000), -8):
                v = struct.unpack_from("<Q", buf, o)[0]
                if EXE <= v < EXE + 0x8000000:
                    vt, oo = v - EXE, 4 * (i - 1) - o
                    break
            # the stem's sound object (from its vtable): dumped when first seen moving and every 2 s, to find the
            # field that says which alternative take is audible
            obj_hex = ""
            if vt and vt != BASE_VT:
                prev = dumped.get(addr, 0)
                if now - prev >= 2.0:
                    o0 = 4 * (i - 1) - oo
                    obj_hex = bytes(buf[o0:o0 + 0x300]).hex()
                    dumped[addr] = now
            print(f"{stamp},stem,{addr:X},{f},{stem},{ms},{int(u32[i]) >> 29},{vt:X},{oo:X},{obj_hex}", flush=True)
            last[addr] = ms
            live = live or vt != BASE_VT
        if live and now - last_scene > 0.25:
            last_scene = now
            print(f"{stamp},scenes,,,,,,,," + " ".join(f"{hd}:{t:.3f}" for hd, t in scenes() if t > 0), flush=True)
        time.sleep(0.008)


if __name__ == "__main__":
    main(float(sys.argv[1]), *sys.argv[2:3])
