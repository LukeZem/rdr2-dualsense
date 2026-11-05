"""Read-only, from outside the game: when does a spoken line REALLY start? The speech sound (vtable rva 0x37FE9C8,
voice/partial/variation at +0x110) has a child wave player at +0xC0 (the game's IsPlaying checks its byte +0xF2).
Finds every speech sound in the pool every 10 ms; on first sight logs its line id and dumps the sound and its children
(+0xC0, +0xC8, +0xD0, +0x08, +0x10); afterwards logs every u32 that changes in those objects (for 4 s).
Output lines:
  NEW  time obj sid voice child0 child1 child2 c8 c10
  DUMP time obj which hex
  CHG  time obj which offset old new
Usage: speech_child_watch.py <seconds> > out.txt
"""
import ctypes
import struct
import sys
import time
from datetime import datetime

import numpy as np

from livemem import h, k32, EXE, q, rd  # noqa: E402

VT = 0x37FE9C8
SPAN = 0x300


def part(s, x):
    for c in s.encode():
        x = (x + c) & 0xFFFFFFFF
        x = (x + (x << 10)) & 0xFFFFFFFF
        x ^= x >> 6
    return x


def fin(x):
    x = (x + (x << 3)) & 0xFFFFFFFF
    x ^= x >> 11
    return (x + (x << 15)) & 0xFFFFFFFF


def main(seconds):
    base, size = q(EXE + 0x53588E8), q(EXE + 0x53588E0)
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t()
    u64 = np.frombuffer(buf, dtype=np.uint64)
    vt_abs = np.uint64(EXE + VT)
    seen = {}       # obj -> (first time, {which: (addr, last bytes)})
    end = time.time() + seconds
    while time.time() < end:
        if not k32.ReadProcessMemory(h, ctypes.c_void_p(base), buf, size, ctypes.byref(got)):
            time.sleep(0.5)
            continue
        now = time.time()
        stamp = datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3]
        for i in np.flatnonzero(u64 == vt_abs):
            obj = base + 8 * int(i)
            o = 8 * int(i)
            raw = bytes(buf[o:o + SPAN]) if o + SPAN <= size else rd(obj, SPAN)
            if not raw:
                continue
            voice, partial, var = struct.unpack_from("<III", raw, 0x110)
            if not partial:
                continue
            sid = fin(part("_%02d" % var, partial)) & 0x1FFFFFFF
            key = (obj, sid)
            kids = {"c0": struct.unpack_from("<Q", raw, 0xC0)[0], "c8": struct.unpack_from("<Q", raw, 0xC8)[0],
                    "d0": struct.unpack_from("<Q", raw, 0xD0)[0], "o8": struct.unpack_from("<Q", raw, 0x08)[0],
                    "o10": struct.unpack_from("<Q", raw, 0x10)[0]}
            if key not in seen:
                seen[key] = (now, {})
                print("NEW", stamp, "%X" % obj, "%08X" % sid, "%08X" % voice,
                      " ".join("%s=%X" % (k, v) for k, v in kids.items()), flush=True)
            first, last = seen[key]
            if now - first > 4.0:
                continue
            objs = {"snd": (obj, raw)}
            for k, a in kids.items():
                if 0x10000000000 <= a < 0x7FF000000000:
                    b = rd(a, SPAN)
                    if b:
                        objs[k] = (a, b)
            for which, (addr, data) in objs.items():
                prev = last.get(which)
                if prev is None or prev[0] != addr:
                    print("DUMP", stamp, "%X" % obj, which, "%X" % addr, data.hex(), flush=True)
                else:
                    for off in range(0, min(len(data), len(prev[1])) - 3, 4):
                        a_, b_ = prev[1][off:off + 4], data[off:off + 4]
                        if a_ != b_:
                            print("CHG", stamp, "%X" % obj, which, "%03X" % off, a_[::-1].hex(), b_[::-1].hex(), flush=True)
                last[which] = (addr, data)
        time.sleep(0.008)


if __name__ == "__main__":
    main(float(sys.argv[1]))
