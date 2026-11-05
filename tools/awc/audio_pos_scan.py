"""Read-only memory scan (from outside the game) for the cutscene audio's play position.
Ground truth from the loopback recordings: in the utp2 intro cutscene (anim scene dict 99916C79) the audio file
position = scene time + 14.13 s. Waits for that scene (via the mod's debug log), then scans all of the game's
private read-write memory for the live position as f32/f64 seconds, u32 milliseconds, u32/u64 samples (48 kHz),
re-checks the candidates twice ~12 s apart, and reports the survivors with the object around them.
Usage: audio_pos_scan.py <out.pkl> [dict] [offset]
"""
import ctypes
import ctypes.wintypes as W
import os
import pickle
import re
import struct
import sys
import time

import numpy as np

from livemem import pid_of, psapi, k32, MBI  # noqa: E402

LOG = r"C:\Steam\steamapps\common\Red Dead Redemption 2\DualSenseRDR2.log"
KINDS = {  # name: (dtype, step, scale from seconds, tolerance)
    "f32 s": (np.float32, 4, 1.0, 0.12),
    "f64 s": (np.float64, 8, 1.0, 0.12),
    "u32 ms": (np.uint32, 4, 1000.0, 120),
    "u32 smp48": (np.uint32, 4, 48000.0, 6000),
    "u64 smp48": (np.uint64, 8, 48000.0, 6000),
}


def main(out, dict_hex="99916C79", offset=14.13):
    pid, h = pid_of("RDR2.exe")
    mods = (ctypes.c_void_p * 1024)()
    need = W.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    exe = mods[0]
    big = ctypes.create_string_buffer(1 << 24)
    got = ctypes.c_size_t()

    def rd(addr, n, buf=big):
        ok = k32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
        return buf.raw[:got.value] if ok else None

    # 1. wait for the scene in the log (only lines written after we started)
    start_size = os.path.getsize(LOG)
    print("waiting for scene dict", dict_hex, flush=True)
    obj = None
    while obj is None:
        with open(LOG, "rb") as f:
            f.seek(start_size)
            for l in f.read().decode("utf-8", "replace").splitlines():
                m = re.search(r"scene: new (\d+) obj ([0-9A-F]+) dict " + dict_hex, l)
                if m:
                    obj = int(m.group(2), 16)
        time.sleep(0.5)

    def scene_t():
        b = rd(obj + 0x180, 4)
        return struct.unpack("<f", b)[0] if b else -1.0

    while scene_t() < 2.0:
        time.sleep(0.1)
    print("scene running, obj %X" % obj, flush=True)

    # 2. full scan
    def regions():
        a, mbi = 0, MBI()
        while a < 0x7FFFFFFF0000:
            if not k32.VirtualQueryEx(h, ctypes.c_void_p(a), ctypes.byref(mbi), ctypes.sizeof(mbi)):
                break
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == 0x1000 and mbi.Type == 0x20000 and mbi.Protect in (0x04, 0x08) :
                yield base, size
            a = base + size

    t_scan = time.time()
    cand = {k: [] for k in KINDS}
    total = 0
    u8 = np.frombuffer(big, dtype=np.uint8)              # no copies: compare straight in the read buffer
    for base, size in list(regions()):
        for off in range(0, size, 1 << 24):
            n = min(1 << 24, size - off)
            p = scene_t() + offset
            if not k32.ReadProcessMemory(h, ctypes.c_void_p(base + off), big, n, ctypes.byref(got)):
                continue
            m = got.value // 8 * 8
            total += m
            for k, (dt, step, sc, tol) in KINDS.items():
                arr = u8[:m].view(dt)
                lo, hi = p * sc - tol, p * sc + tol
                idx = np.flatnonzero((arr > lo) & (arr < hi))
                if len(idx):
                    cand[k].append(base + off + idx.astype(np.int64) * step)
    cand = {k: (np.concatenate(v) if v else np.zeros(0, np.int64)) for k, v in cand.items()}
    print("scanned %.1f GB in %.1f s; candidates: %s" % (total / 1e9, time.time() - t_scan,
          {k: len(v) for k, v in cand.items()}), flush=True)

    # 3. re-check twice
    small = ctypes.create_string_buffer(8)
    hist = {k: [] for k in KINDS}
    for rnd in range(2):
        time.sleep(10)
        for k, (dt, step, sc, tol) in KINDS.items():
            keep, vals = [], []
            for i, a in enumerate(cand[k]):
                if i % 2000 == 0:
                    p = scene_t() + offset
                b = rd(int(a), step, small)
                if not b:
                    continue
                v = struct.unpack("<f" if dt == np.float32 else "<d" if dt == np.float64 else
                                  "<I" if dt == np.uint32 else "<Q", b)[0]
                ok = abs(v - p) < tol if dt in (np.float32, np.float64) else abs(int(v) - int(p * sc)) < tol
                if ok:
                    keep.append(a)
                    vals.append((v, p))
            cand[k] = np.array(keep, dtype=np.int64)
            hist[k].append(vals)
        print("re-check %d: %s" % (rnd + 1, {k: len(v) for k, v in cand.items()}), flush=True)

    # 4. report survivors with the surrounding memory
    res = []
    for k, arr in cand.items():
        for a in arr[:50]:
            a = int(a)
            ctx = rd(a - 0x400, 0x800, ctypes.create_string_buffer(0x800))
            vt = None
            if ctx:                                   # nearest pointer into the exe before the field = object start?
                for o in range(0x400, -1, -8):
                    q = struct.unpack_from("<Q", ctx, o)[0]
                    if exe <= q < exe + 0x8000000:
                        vt = (a - 0x400 + o, q - exe)
                        break
            b = rd(a, 8, small)
            p = scene_t() + offset
            print(f"  {k:10} at {a:X}  value now {b.hex() if b else '?'}  expected {p:.3f}"
                  + (f"  exe pointer at {vt[0]:X} (field +0x{a - vt[0]:X}), rva {vt[1]:X}" if vt else ""), flush=True)
            res.append({"kind": k, "addr": a, "ctx": ctx, "vt": vt})
    pickle.dump({"exe": exe, "obj": obj, "res": res, "cand": cand}, open(out, "wb"))
    print("saved", out)


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3] or []), *([float(sys.argv[3])] if len(sys.argv) > 3 else []))
