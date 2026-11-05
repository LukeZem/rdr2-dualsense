"""Read-only, from outside the game: is a spoken line's real play position in the sound pool (like cutscene stems:
u32 ms, then the stream id | flags)? Watches the pool for any speech stream id (from the keyless index of the speech
archives) and logs every change: time, field address, stream id, ms, the containing object's vtable.
Usage: speech_pool_watch.py <seconds> > out.csv
"""
import ctypes
import os
import struct
import sys
import time
from datetime import datetime

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import walk_index as W  # noqa: E402
from livemem import h, k32, EXE, q  # noqa: E402

S = r"C:\Steam\steamapps\common\Red Dead Redemption 2\x64\audio\sfx"
ARCS = ["PEDS_%02d" % i for i in range(11)] + ["S_MISC", "S_RE", "SS_AM", "SS_NZ"]


def main(seconds):
    sids = set()
    for a in ARCS:
        files, _ = W.walk(os.path.join(S, a + ".rpf"))
        for _, _, streams in files:
            for sid, ch in streams:
                if 0x55 in ch:
                    sids.add(sid)
    ids = np.array(sorted(sids), dtype=np.uint32)
    print("# speech ids:", len(ids), flush=True)
    base, size = q(EXE + 0x53588E8), q(EXE + 0x53588E0)
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    u32 = np.frombuffer(buf, dtype=np.uint32)
    last = {}
    print("time,addr,sid,ms,flags,vtable_rva,obj_off", flush=True)
    end = time.time() + seconds
    while time.time() < end:
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
            time.sleep(0.5)
            continue
        now = time.time()
        stamp = datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]
        key = u32 & np.uint32(0x1FFFFFFF)
        for i in np.flatnonzero(np.isin(key, ids)):
            if i == 0:
                continue
            ms = int(u32[i - 1])
            if ms > 120000:
                continue
            addr = base + 4 * (i - 1)
            if last.get(addr) == (ms, int(key[i])):
                continue
            last[addr] = (ms, int(key[i]))
            vt, oo = 0, 0
            for o in range(4 * (i - 1) // 8 * 8, max(0, 4 * (i - 1) - 0x800), -8):
                v = struct.unpack_from("<Q", buf, o)[0]
                if EXE <= v < EXE + 0x8000000:
                    vt, oo = v - EXE, 4 * (i - 1) - o
                    break
            print(f"{stamp},{addr:X},{int(key[i]):08X},{ms},{int(u32[i]) >> 29},{vt:X},{oo:X}", flush=True)
        time.sleep(0.01)


if __name__ == "__main__":
    main(float(sys.argv[1]))
