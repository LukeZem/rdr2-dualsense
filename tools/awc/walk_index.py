"""Keyless index of the AWC files inside an RDR2 audio archive (prototype of the mod's C++ indexer).
The archive's table of contents is encrypted, but the files are stored plain: walk from one "ADAT" header to the
next (file end = furthest chunk end, next file 16-byte aligned; if not there, search forward).
Usage: walk_index.py <archive.rpf> [compare]   (compare = check against the key-based reader)
"""
import os
import struct
import sys
import time


def walk(path):
    f = open(path, "rb")
    size = os.path.getsize(path)
    magic, count = struct.unpack("<Ii", f.read(8))
    pos = 16 + 0x100 + count * 24
    files = []
    misses = 0
    while pos + 16 <= size:
        f.seek(pos)
        h = f.read(16)
        if h[:4] != b"ADAT":
            # search forward for the next 16-aligned ADAT
            f.seek(pos)
            found = -1
            while found < 0:
                blk = f.read(1 << 20)
                if not blk:
                    break
                i = blk.find(b"ADAT")
                while i >= 0 and (pos + i) % 16:
                    i = blk.find(b"ADAT", i + 1)
                if i >= 0:
                    found = pos + i
                elif len(blk) < (1 << 20):                 # end of the archive
                    break
                else:
                    pos += len(blk) - 16                   # overlap so a header across the boundary is not missed
                    f.seek(pos)
            if found < 0:
                break
            misses += 1
            pos = found
            continue
        _, flags, cnt, hsize = struct.unpack_from("<HHII", h, 4)
        f.seek(pos)
        hdr = f.read(16 + 2 * cnt + 4 * cnt + 8 * 8 * cnt + 64)  # enough for <= 8 chunks per stream
        off = 16 + (2 * cnt if flags & 1 else 0)
        infos = [struct.unpack_from("<I", hdr, off + 4 * i)[0] for i in range(cnt)]
        off += 4 * cnt
        end = hsize
        streams = []
        for info in infos:
            sid = info & 0x1FFFFFFF
            ch = {}
            for _ in range(info >> 29):
                v = struct.unpack_from("<Q", hdr, off)[0]
                off += 8
                o, n = v & 0x0FFFFFFF, (v >> 28) & 0x0FFFFFFF
                ch[v >> 56] = (o, n)
                end = max(end, o + n)
            streams.append((sid, ch))
        if end < 32 or end > (1 << 31) or cnt == 0 or cnt > 100000:     # not a real header ("ADAT" inside data)
            pos += 16
            misses += 1
            continue
        files.append((pos, end, streams))
        pos = (pos + end + 15) & ~15
    return files, misses


if __name__ == "__main__":
    t = time.time()
    files, misses = walk(sys.argv[1])
    ns = sum(len(s) for _, _, s in files)
    print(f"{os.path.basename(sys.argv[1])}: {len(files)} awc files, {ns} streams, {misses} searches, {time.time() - t:.1f} s")
    if len(sys.argv) > 2:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rpf8"))
        import rpf8
        a = rpf8.RPF8(sys.argv[1])
        want = sorted(e.offset for e in a.entries if not e.is_resource)
        got = {p for p, _, _ in files}
        print(f"  key-based entries {len(want)}, walker found {len(got & set(want))}, extra {len(got - set(want))}")
