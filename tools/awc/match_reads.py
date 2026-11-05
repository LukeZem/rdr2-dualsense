"""Match the game's audio-archive reads (DualSenseRDR2.log, io probe) to files and recordings, and line them up with
the spoken lines (speech probe) and cutscenes (control probe).

  read: archive + offset  ->  archive entry (an .awc file)  ->  stream (recording) whose chunk contains the offset
Usage: match_reads.py <log>
"""
import bisect
import os
import re
import struct
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rpf8"))
import rpf8  # noqa: E402

GAME = r"C:\Steam\steamapps\common\Red Dead Redemption 2"
SPEECH = re.compile(r"\\(PEDS_\d+|S_MISC|S_RE|S_VOFX|SS_AM|SS_NZ|CUTSCENE_MASTERED_ONLY)\.rpf$")


def joaat(s):
    h = 0
    for c in s.lower().encode():
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


def sec(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


class Archive:
    def __init__(self, rel):
        self.a = rpf8.RPF8(os.path.join(GAME, rel))
        es = sorted(self.a.entries, key=lambda e: e.offset)
        self.offs = [e.offset for e in es]
        self.es = es
        self.awc = {}

    def entry(self, off):
        i = bisect.bisect_right(self.offs, off) - 1
        if i < 0:
            return None, 0
        e = self.es[i]
        return (e, off - e.offset) if off - e.offset < e.disk_size else (None, 0)

    def streams(self, e):
        """[(start, end, stream id, chunk tag)] inside the awc"""
        if e.offset in self.awc:
            return self.awc[e.offset]
        hdr = self.a.read(e.offset, min(e.size, 0x40000))
        out = []
        if hdr[:4] == b"ADAT":
            _, flags, count, _ = struct.unpack_from("<HHII", hdr, 4)
            off = 16 + (2 * count if flags & 1 else 0)
            infos = [struct.unpack_from("<I", hdr, off + 4 * i)[0] for i in range(count)]
            off += 4 * count
            for info in infos:
                for _ in range(info >> 29):
                    v = struct.unpack_from("<Q", hdr, off)[0]
                    off += 8
                    out.append((v & 0x0FFFFFFF, (v & 0x0FFFFFFF) + ((v >> 28) & 0x0FFFFFFF), info & 0x1FFFFFFF, v >> 56))
        self.awc[e.offset] = out
        return out


def main(path):
    rpf8.NAMES.load()
    reads, speech, control = [], [], []
    for l in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"io: (\S+) (\S+) off 0x([0-9A-F]+) len (\d+)", l)
        if m and SPEECH.search(m.group(2)):
            reads.append((sec(m.group(1)), m.group(2).split("\\")[-1], int(m.group(3), 16), int(m.group(4))))
            continue
        m = re.search(r"^(\S+) .*speech: start ped (\d+) model ([0-9A-F]{8}) line ([0-9A-F]{8}).*ambient (\d) dist ([\d.]+)", l)
        if m:
            speech.append((sec(m.group(1)), m.group(2), m.group(3), m.group(4), m.group(5), float(m.group(6)), "player" in l))
            continue
        m = re.search(r"^(\S+) .*control: (.*)", l)
        if m:
            control.append((sec(m.group(1)), m.group(2)))
    archives = {}
    resolved = []
    for t, arc, off, ln in reads:
        if arc not in archives:
            archives[arc] = Archive("x64/audio/sfx/" + arc)
        A = archives[arc]
        e, inner = A.entry(off)
        if e is None:
            resolved.append((t, arc, "?", None, None, off, ln))
            continue
        inside = [(s0, s1, sid, tag) for s0, s1, sid, tag in A.streams(e) if s0 <= inner < s1]
        inside.sort(key=lambda c: (c[3] != 0x55, c[1] - c[0]))
        sid = inside[0][2] if inside else None
        tag = inside[0][3] if inside else None
        resolved.append((t, arc, e.display_name(), sid, tag, inner, ln))
    print("== reads in speech/cutscene archives:", len(resolved))
    for r in resolved[:60]:
        t, arc, name, sid, tag, inner, ln = r
        print(f"  {t % 86400:9.3f}  {arc:24} {name:46} stream {('%08X' % sid) if sid is not None else '-':8} "
              f"chunk {('%02X' % tag) if tag is not None else '--'} inner 0x{inner:X} len {ln}")
    # coverage: each spoken line -> data reads of a speech archive within -0.3 .. +0.5 s
    print("\n== spoken lines vs reads")
    data = [r for r in resolved if r[5] > 0 and r[1] != "CUTSCENE_MASTERED_ONLY" and r[3] is not None]
    print(f"  recording reads: {len(data)}; landing in an audio data chunk (0x55): {sum(r[4] == 0x55 for r in data)}")
    for lo, hi in ((-0.3, 0.5), (-1.0, 0.5), (-2.0, 1.0)):
        got = sum(any(lo <= r[0] - sp[0] <= hi for r in data) for sp in speech)
        print(f"  spoken lines with a recording read within {lo:+.1f}..{hi:+.1f} s: {got} of {len(speech)}")
    lag = sorted(min((r[0] - sp[0] for r in data if -2 <= r[0] - sp[0] <= 1), key=abs)
                 for sp in speech if any(-2 <= r[0] - sp[0] <= 1 for r in data))
    if lag:
        print("  read time minus speech start: median %.3f s, 10%% %.3f, 90%% %.3f" %
              (lag[len(lag) // 2], lag[len(lag) // 10], lag[9 * len(lag) // 10]))
    by, files = defaultdict(int), defaultdict(int)
    for r in data:
        by[r[1]] += 1
        files[r[2]] += 1
    print("  recording reads per archive:", dict(by))
    print("  most read voice files:", sorted(files.items(), key=lambda x: -x[1])[:12])
    print("\n== control changes:", control)


if __name__ == "__main__":
    main(sys.argv[1])


def by_length(path):
    """coverage of spoken lines by their length (grunts/breaths are short and come from preloaded banks)"""
    import re as _re
    starts, ends = {}, []
    for l in open(path, encoding="utf-8", errors="replace"):
        m = _re.search(r"^(\S+) .*speech: start ped (\d+)", l)
        if m:
            starts[m.group(2)] = sec(m.group(1))
            continue
        m = _re.search(r"speech: end ped (\d+) line \S+ after (\d+) ms", l)
        if m and m.group(1) in starts:
            ends.append((starts.pop(m.group(1)), int(m.group(2)) / 1000))
    return ends
