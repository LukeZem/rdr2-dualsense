"""Check the exact-line method on a speech-probe log: from each playing speech sound (speechreq-s0 dump)
  voice   = u32 at sound+0x110 (joaat of the voice, = the .awc file name, banks: <voice>_NN.awc)
  partial = u32 at sound+0x114 (the line's context hash before joaat's last mixing step)
  var     = u32 at sound+0x118 (variation number)
  stream  = finish(joaat continued with "_%02d" % var from partial) & 0x1FFFFFFF
-> look the stream up in the speech archives, compare with the io-probe disk reads, and diff s0/s1 (0.5 s apart)
to find the playback position.
Usage: speech_exact.py <log>
"""
import os
import re
import struct
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import match_reads as M  # noqa: E402

ARCS = ["PEDS_%02d.rpf" % i for i in range(11)] + ["S_MISC.rpf", "S_RE.rpf", "SS_AM.rpf", "SS_NZ.rpf", "S_VOFX.rpf"]


def part(s, h=0):
    for c in s.lower().encode():
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    return h


def fin(h):
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


def index():
    """voice hash -> [(archive, file name, {stream ids})]"""
    idx = defaultdict(list)
    for arc in ARCS:
        p = os.path.join(M.GAME, "x64/audio/sfx", arc)
        if not os.path.exists(p):
            continue
        A = M.Archive("x64/audio/sfx/" + arc)
        for e in A.es:
            name = e.display_name()
            if not name.lower().endswith(".awc"):
                continue
            stem = os.path.splitext(name)[0]
            sids = {s[2] for s in A.streams(e)}
            idx[M.joaat(stem)].append((arc, name, sids))
            m = re.match(r"(.*)_\d\d$", stem)            # banks: arthur_normal_02 -> voice arthur_normal
            if m:
                idx[M.joaat(m.group(1))].append((arc, name, sids))
    return idx


def main(path):
    M.rpf8.NAMES.load()
    idx = index()
    print("voices indexed:", len(idx))
    s0, s1, reads = {}, {}, []
    for l in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"^(\S+) .*speechreq-s([01]): ped (-?\d+) ([0-9A-F]+) \+([0-9A-F]{3}) ([0-9A-F]+)", l)
        if m:
            d = s0 if m.group(2) == "0" else s1
            key = m.group(4)
            if m.group(2) == "0" and m.group(5) == "000":
                d[key] = {"t": M.sec(m.group(1)), "ped": m.group(3), "b": b""}
            if key in d:
                d[key]["b"] += bytes.fromhex(m.group(6))
            elif m.group(2) == "1":
                d[key] = {"t": M.sec(m.group(1)), "b": bytes.fromhex(m.group(6))}
            continue
        m = re.search(r"io: (\S+) (\S+) off 0x([0-9A-F]+) len (\d+)", l)
        if m and re.search(r"\\(PEDS_\d+|S_MISC|S_RE|S_VOFX|SS_AM|SS_NZ)\.rpf$", m.group(2)):
            reads.append((M.sec(m.group(1)), m.group(2).split("\\")[-1], int(m.group(3), 16)))
    archives = {}
    rd = []
    for t, arc, off in reads:
        A = archives.setdefault(arc, M.Archive("x64/audio/sfx/" + arc))
        e, inner = A.entry(off)
        if e is None:
            continue
        inside = [s for s in A.streams(e) if s[0] <= inner < s[1] and s[3] == 0x55]
        if inside:
            rd.append((t, e.display_name(), inside[0][2]))
    stats = Counter()
    pos_cand = defaultdict(list)
    for key, d in s0.items():
        b = d["b"]
        if len(b) < 0x120:
            continue
        voice, partial, var = struct.unpack_from("<III", b, 0x110)
        if not partial:
            stats["no line hash"] += 1
            continue
        sid = fin(part("_%02d" % var, partial)) & 0x1FFFFFFF
        files = [(arc, n) for arc, n, sids in idx.get(voice, []) if sid in sids]
        disk = [r for r in rd if -1.5 <= r[0] - d["t"] <= 1.0 and r[2] == sid]
        stats["lines"] += 1
        stats["found in files"] += bool(files)
        stats["voice known"] += voice in idx
        stats["confirmed by a disk read"] += bool(disk)
        print(f"{d['t'] % 86400:9.3f} ped {d['ped']:>7} voice {voice:08X} var {var:2} stream {sid:08X} -> "
              f"{files[0] if files else ('voice known, stream not in it' if voice in idx else 'voice not indexed')}"
              f"{'  [disk read matches]' if disk else ''}")
        if key in s1 and len(s1[key]["b"]) >= 0x200:
            a, c = b[:0x200], s1[key]["b"][:0x200]
            for o in range(0, 0x200, 4):
                x, y = struct.unpack_from("<I", a, o)[0], struct.unpack_from("<I", c, o)[0]
                fx, fy = struct.unpack_from("<f", a, o)[0], struct.unpack_from("<f", c, o)[0]
                if x != y:
                    pos_cand[o].append((x, y, fx, fy))
    print("\n", dict(stats))
    print("\nfields that change in 0.5 s (offset: how many sounds, examples int/float):")
    for o, v in sorted(pos_cand.items(), key=lambda kv: -len(kv[1]))[:20]:
        ex = v[:3]
        print(f"  +0x{o:03X} {len(v):3}  " + "  ".join(f"{x}->{y} ({fx:.3f}->{fy:.3f})" for x, y, fx, fy in ex))


if __name__ == "__main__":
    main(sys.argv[1])
