"""Which speech file belongs to which voice - the table the mod needs to pick the speaker's own recording of a line
(a line's stream id comes from the line's name, e.g. GREET_MALE_01, so the same id is in hundreds of voices' files).

The game names a ped's voice by a hash: joaat of the voice's file name (0429_a_m_m_strtownfolk_01_white_01) or of
a prefix of it (Arthur's voice "arthur" -> arthur_normal_02.awc ...). The mod finds the files without names (keyless
walk, awc.cpp), so it identifies a file by a fingerprint of its header: FNV-1a 64 of the raw stream-info table
(u32 per stream, right after the 16-byte header and the optional u16 table) and the chunk table after it. This tool reads the archives with
names (rpf8.py + its key tables, which never ship) and writes, per speech file: fingerprint and the joaat of every
underscore prefix of its name. Metadata only, no audio.
Output: tools/trigger_lab/data/speech_voices.txt   lines "<fingerprint hex> <voice hash hex> ..."
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import match_reads as M  # noqa: E402

ARCS = ["PEDS_%02d" % i for i in range(11)] + ["S_MISC", "S_RE", "SS_AM", "SS_NZ"]
OUT = os.path.join(HERE, "..", "trigger_lab", "data", "speech_voices.txt")


def fnv1a64(b):
    h = 0xCBF29CE484222325
    for x in b:
        h ^= x
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def fingerprint(hdr):
    """FNV-1a 64 of the stream-info table and the chunk table (ids, chunk offsets and sizes): unique per file"""
    _, flags, count, _ = struct.unpack_from("<HHII", hdr, 4)
    off = 16 + (2 * count if flags & 1 else 0)
    chunks = sum(struct.unpack_from("<I", hdr, off + 4 * i)[0] >> 29 for i in range(count))
    return fnv1a64(hdr[off:off + 4 * count + 8 * chunks])


def main():
    M.rpf8.NAMES.load()
    rows, seen, unnamed = [], {}, 0
    for a in ARCS:
        A = M.Archive("x64/audio/sfx/%s.rpf" % a)
        for e in A.es:
            name = e.display_name()
            if not name.lower().endswith(".awc"):
                continue
            if name.startswith("0x"):
                unnamed += 1
                continue
            hdr = A.a.read(e.offset, 16)
            count = struct.unpack_from("<I", hdr, 8)[0]
            hdr = A.a.read(e.offset, 16 + 6 * count + 64 * count)
            fp = fingerprint(hdr)
            stem = os.path.splitext(name)[0].lower()
            parts = stem.split("_")
            voices = sorted({M.joaat("_".join(parts[:k])) for k in range(1, len(parts) + 1)})
            if fp in seen and seen[fp] != stem:
                print("  same fingerprint:", seen[fp], stem)
            seen[fp] = stem
            rows.append("%016X %s" % (fp, " ".join("%08X" % v for v in voices)))
    with open(OUT, "w", newline="\n") as f:
        f.write("# speech file fingerprint -> voice hashes (tools/awc/build_voice_table.py)\n")
        f.write("\n".join(rows) + "\n")
    print("%d speech files (%d without a known name) -> %s" % (len(rows), unnamed, os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
