"""Read-only, from outside the game: dump RDR2's anim scene objects (and what they point to) while a cutscene runs,
to find where a scene keeps its audio start offset / the audio play position.
Scene map (from disassembling _GET_ANIM_SCENE_TIME, this game build): [exe+0x5BD41B8] -> +0x08 buckets, +0x10 count;
node = {u32 handle, +0x08 scene object, +0x10 next}; scene time = float at object+0x180.
Each running scene is dumped when first seen running past 1 s, then 2, 10 and 20 s later.
Usage: scene_dump.py <out.pkl> <seconds>
"""
import ctypes
import ctypes.wintypes as W
import os
import pickle
import struct
import sys
import time
from datetime import datetime

from livemem import pid_of, psapi, k32  # noqa: E402

MAP_RVA, OBJ, PTR_DUMP, MAX_PTRS = 0x5BD41B8, 0x800, 0x400, 160
AT = [0, 2, 10, 20]                 # dump times after the first dump (s)


def main(out, seconds):
    pid, h = pid_of("RDR2.exe")
    if not pid:
        sys.exit("RDR2.exe not running")
    mods = (ctypes.c_void_p * 1024)()
    need = W.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    base = mods[0]
    buf = ctypes.create_string_buffer(0x10000)
    got = ctypes.c_size_t()

    def rd(addr, n):
        if not addr or n > len(buf):
            return None
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
        return buf.raw[:n] if ok and got.value == n else None

    def q(addr):
        b = rd(addr, 8)
        return struct.unpack("<Q", b)[0] if b else 0

    seen = {}          # obj -> state: 0 none, 1 first dumped (time), 2 done
    dumps = []
    end = time.time() + seconds
    stop = out + ".stop"
    while time.time() < end and not os.path.exists(stop):
        m = q(base + MAP_RVA)
        bk, nb = q(m + 8), struct.unpack("<I", rd(m + 0x10, 4) or b"\0\0\0\0")[0]
        scenes = []
        for i in range(min(nb, 4096)):
            n = q(bk + 8 * i)
            for _ in range(64):
                if not n:
                    break
                hk = rd(n, 4)
                obj = q(n + 8)
                if hk and obj:
                    scenes.append((struct.unpack("<I", hk)[0], obj))
                n = q(n + 0x10)
        now = time.time()
        for hd, obj in scenes:
            ob = rd(obj, OBJ)
            if not ob:
                continue
            t = struct.unpack_from("<f", ob, 0x180)[0]
            st = seen.get(obj)                      # (first dump time, dumps so far)
            due = (st is None and t > 1.0) or (st is not None and st[1] < len(AT) and now - st[0] >= AT[st[1]])
            if not due:
                continue
            ptrs = {}
            for o in range(0, OBJ, 8):
                p = struct.unpack_from("<Q", ob, o)[0]
                if 0x10000000000 <= p < 0x7FF000000000 and not p & 7 and len(ptrs) < MAX_PTRS:
                    pb = rd(p, PTR_DUMP)
                    if pb:
                        ptrs[o] = (p, pb)
            dumps.append({"wall": now, "local": datetime.fromtimestamp(now).strftime("%H:%M:%S.%f")[:-3],
                          "handle": hd, "obj": obj, "t": t, "bytes": ob, "ptrs": ptrs})
            seen[obj] = (now, 1) if st is None else (st[0], st[1] + 1)
            print(f"{dumps[-1]['local']} scene {hd} obj {obj:X} t {t:.3f} ({len(ptrs)} pointers)", flush=True)
        time.sleep(0.1)
    pickle.dump({"base": base, "dumps": dumps}, open(out, "wb"))
    print("saved", len(dumps), "dumps to", out)


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]))
