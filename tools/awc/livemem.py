"""Read-only access to the running game's memory, from outside (research tools; the game is never written).

  pid_of(name) -> (pid, handle)          a process by exe name, opened for query + read
  h, EXE                                 RDR2.exe's handle and image base (None if the game is not running)
  rd(a, n) / u32(a) / q(a)               read bytes / u32 / u64 (None if unreadable)
  region(a)                              VirtualQueryEx of an address
  python livemem.py <out.bin>            dump the whole RDR2.exe image (unpacked by then), laid out by RVA
"""
import ctypes
import ctypes.wintypes as W
import struct
import sys

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
PROCESS_QUERY_INFORMATION, PROCESS_VM_READ = 0x400, 0x10


class MBI(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p), ("AllocationProtect", W.DWORD),
                ("PartitionId", W.WORD), ("RegionSize", ctypes.c_size_t), ("State", W.DWORD), ("Protect", W.DWORD),
                ("Type", W.DWORD)]


def pid_of(name):
    arr = (W.DWORD * 4096)()
    got = W.DWORD()
    psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(got))
    for pid in arr[:got.value // 4]:
        h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            continue
        buf = ctypes.create_unicode_buffer(512)
        n = W.DWORD(512)
        ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        if ok and buf.value.lower().endswith("\\" + name.lower()):
            return pid, h
        k32.CloseHandle(h)
    return None, None


def image_base(h):
    mods = (ctypes.c_void_p * 1024)()
    need = W.DWORD()
    psapi.EnumProcessModulesEx(h, mods, ctypes.sizeof(mods), ctypes.byref(need), 3)
    return mods[0]


pid, h = pid_of("RDR2.exe")
EXE = image_base(h) if h else None
_b = ctypes.create_string_buffer(1 << 24)
_g = ctypes.c_size_t()


def rd(a, n):
    ok = k32.ReadProcessMemory(h, ctypes.c_void_p(a), _b, n, ctypes.byref(_g))
    return _b.raw[:_g.value] if ok else None


def u32(a):
    b = rd(a, 4)
    return struct.unpack("<I", b)[0] if b else None


def q(a):
    b = rd(a, 8)
    return struct.unpack("<Q", b)[0] if b else None


def region(a):
    m = MBI()
    k32.VirtualQueryEx(h, ctypes.c_void_p(a), ctypes.byref(m), ctypes.sizeof(m))
    return (m.AllocationBase or 0, m.BaseAddress or 0, m.RegionSize, hex(m.State), hex(m.Type), hex(m.Protect))


def dump(out):
    if not h:
        sys.exit("RDR2.exe not running")
    hdr = rd(EXE, 0x1000)
    e = int.from_bytes(hdr[0x3C:0x40], "little")
    size = int.from_bytes(hdr[e + 0x50:e + 0x54], "little")
    print(f"pid {pid} base 0x{EXE:X} image size 0x{size:X}")
    img = bytearray(size)
    bad = 0
    for off in range(0, size, 0x10000):
        n = min(0x10000, size - off)
        b = rd(EXE + off, n)
        if b and len(b) == n:
            img[off:off + n] = b
        else:                                           # partly unreadable: go page by page
            for p in range(off, off + n, 0x1000):
                b = rd(EXE + p, 0x1000)
                if b and len(b) == 0x1000:
                    img[p:p + 0x1000] = b
                else:
                    bad += 1
    open(out, "wb").write(img)
    print(f"wrote {out}: {size} bytes, unreadable pages {bad}")


if __name__ == "__main__":
    dump(sys.argv[1])
