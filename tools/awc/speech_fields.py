"""Find which fields of the game's speech request name the exact recording (debug log of the speech request probe).

For every request dump (speechreq-r) that starts playing, look for the line in the io-probe reads that follow
(archive -> .awc file -> stream id), then search the dump for:
  - the stream id (joaat("<CONTEXT>_<NN>") & 0x1FFFFFFF), also as a full 32-bit hash with any top bits
  - joaat of the .awc file name (the voice)
  - the context hash the native reported, and its partial form (joaat before the last mixing step)
Prints the offsets that match, and how often each offset matches across all lines.
Usage: speech_fields.py <log>
"""
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import match_reads as M  # noqa: E402

SPEECH = re.compile(r"\\(PEDS_\d+|S_MISC|S_RE|S_VOFX|SS_AM|SS_NZ)\.rpf$")


def finish(h):
    """joaat's last mixing step (what the native does to the stored value)"""
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


def main(path):
    M.rpf8.NAMES.load()
    dumps = defaultdict(dict)        # req -> {off: bytes} (latest dump per request at state change)
    starts = []                      # (t, ped, req, type, partial)
    reads = []
    for l in open(path, encoding="utf-8", errors="replace"):
        m = re.search(r"^(\S+) .*speechreq: ped (-?\d+) req ([0-9A-F]+)( new)? type (\d+) state (\d+) .*partial ([0-9A-F]{8})", l)
        if m:
            t = M.sec(m.group(1))
            if m.group(6) == "5":
                starts.append((t, m.group(2), m.group(3), int(m.group(5)), int(m.group(7), 16)))
            cur = (m.group(3), t)
            continue
        m = re.search(r"^(\S+) .*speechreq-r: ped (-?\d+) ([0-9A-F]+) \+([0-9A-F]{3}) ([0-9A-F]+)", l)
        if m:
            dumps[(m.group(3), M.sec(m.group(1)))][int(m.group(4), 16)] = bytes.fromhex(m.group(5))
            continue
        m = re.search(r"io: (\S+) (\S+) off 0x([0-9A-F]+) len (\d+)", l)
        if m and SPEECH.search(m.group(2)):
            reads.append((M.sec(m.group(1)), m.group(2).split("\\")[-1], int(m.group(3), 16), int(m.group(4))))
    # resolve reads -> (file, stream id)
    archives, res = {}, []
    for t, arc, off, ln in reads:
        if arc not in archives:
            archives[arc] = M.Archive("x64/audio/sfx/" + arc)
        A = archives[arc]
        e, inner = A.entry(off)
        if e is None:
            continue
        inside = [s for s in A.streams(e) if s[0] <= inner < s[1]]
        inside.sort(key=lambda c: (c[3] != 0x55, c[1] - c[0]))
        if inside and inside[0][3] == 0x55:
            res.append((t, arc, e.display_name(), inside[0][2]))
    print(f"playing starts: {len(starts)}, resolved recording reads: {len(res)}")
    hits = Counter()
    n_matched = 0
    for t, ped, req, typ, partial in starts:
        # dump taken at this state change
        key = min((k for k in dumps if k[0] == req), key=lambda k: abs(k[1] - t), default=None)
        if not key:
            continue
        blob = b"".join(dumps[key].get(o, b"\0" * 0x100) for o in (0, 0x100, 0x200))
        near = [r for r in res if -1.5 <= r[0] - t <= 1.0]
        words = {o: int.from_bytes(blob[o:o + 4], "little") for o in range(0, len(blob) - 3, 4)}
        found = []
        for o, v in words.items():
            if partial and v == partial:
                found.append((o, "partial context"))
            if partial and v == finish(partial):
                found.append((o, "context hash"))
            for rt, arc, name, sid in near:
                if v & 0x1FFFFFFF == sid:
                    found.append((o, f"stream id {sid:08X} ({name})"))
                stem = os.path.splitext(name)[0]
                if v == M.joaat(stem):
                    found.append((o, f"voice = joaat('{stem}')"))
        if near:
            n_matched += 1
        for o, what in found:
            hits[(o, what.split(" (")[0].split(" =")[0] if "stream" not in what else "stream id")] += 1
        print(f"{t % 86400:9.3f} ped {ped} type {typ} partial {partial:08X} reads near: "
              f"{[(n, '%08X' % s) for _, _, n, s in near][:3]}")
        for o, what in found:
            print(f"      +0x{o:03X}  {what}")
    print(f"\nlines with a recording read near: {n_matched}")
    print("offsets matching most often:")
    for (o, what), c in hits.most_common(20):
        print(f"  +0x{o:03X} {what:16} {c}")


if __name__ == "__main__":
    main(sys.argv[1])
