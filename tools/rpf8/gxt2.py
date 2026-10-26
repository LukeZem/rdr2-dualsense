#!/usr/bin/env python3
"""Dump RDR2 text tables (.yldb resources, RSC8 type 5) -> TSV "0xHASH<TAB>text".

RDR2 PC does not use GXT2 files: localized text lives in x64/data/lang/<lang>_rel.rpf as
*.yldb resources (global.yldb holds the menu/UI strings). A yldb is a hash map:
  +0x10 ptr  bucket array, +0x18 u32 bucket count
  bucket -> linked list of { u64 hash, ptr value(+0x10 -> {ptr string, u64 len}), ptr next }
Pointers are virtual (0x50xxxxxx); the low 24 bits are offsets into the resource body.
Label hashes are joaat of the label name lower-cased (e.g. joaat("mo_autosav")).

Usage:
  gxt2.py dump <archive.rpf> <out.tsv> [lang_rpf_inner_path]
        default inner path: x64/data/lang/american_rel.rpf (use update_3.rpf - newest)
  gxt2.py file <file.yldb> [out.tsv]          (a .yldb extracted with RSC8 header)
  gxt2.py hash <LABEL> ...                    print joaat(lower(label))
  gxt2.py grep <tsv> <regex>                  case-insensitive search in text
  gxt2.py build <in.txt> <out.gxt2>           'LABEL = text' lines -> binary GXT2
  gxt2.py read <file.gxt2>                    binary GXT2 -> '0xHASH = text'
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpf8  # noqa: E402


def label_hash(s):
    return rpf8.joaat(s.lower())


def parse_yldb(data):
    if data[:4] == b"RSC8":
        data = data[16:]
    off = lambda p: p & 0xFFFFFF  # noqa: E731
    buckets_ptr, count = struct.unpack_from("<QI", data, 0x10)
    res = {}
    bp = off(buckets_ptr)
    for i in range(count):
        p = struct.unpack_from("<Q", data, bp + 8 * i)[0]
        seen = 0
        while p and seen < 100000:
            o = off(p)
            h, vptr, nxt = struct.unpack_from("<QQQ", data, o)
            vo = off(vptr) + 0x10
            sptr, slen = struct.unpack_from("<QQ", data, vo)
            so = off(sptr)
            s = data[so:so + slen].split(b"\0", 1)[0].decode("utf-8", "replace")
            res[h & 0xFFFFFFFF] = s
            p = nxt
            seen += 1
    return res


def yldb_add_strings(rsc, strings, version=5):
    """Add/replace strings in a .yldb resource (bytes WITH the 16-byte RSC8 header).

    New entries are appended into the zero-filled free tail of the virtual page if they
    fit (resource size unchanged), else the page is grown. Each new entry = string
    (NUL-terminated) + value block {16 zero bytes, ptr string, u64 strlen+1} + node
    {u64 hash, ptr value, ptr next}; the node is pushed at the head of bucket
    (hash % bucket_count) and the entry count at +0x20 is incremented. Existing keys get a
    new string (value block pointer redirected). Returns (new_rsc_bytes, new_v3).
    """
    import struct as st
    hdr = bytearray(rsc[:16])
    magic, val1, v3 = st.unpack_from("<IIQ", hdr, 0)
    assert magic == 0x38435352
    body = bytearray(rsc[16:])
    vsize = v3 & 0xFFFFFFF0
    assert ((v3 >> 32) & 0xFFFFFFF0) == 0, "physical segment not expected in yldb"
    assert len(body) == vsize
    off = lambda p: p & 0xFFFFFF  # noqa: E731
    ptr = lambda o: 0x50000000 | o  # noqa: E731
    bp, cnt = st.unpack_from("<QI", body, 0x10)
    existing = {}
    for i in range(cnt):
        p = st.unpack_from("<Q", body, off(bp) + 8 * i)[0]
        while p:
            h, v, nx = st.unpack_from("<QQQ", body, off(p))
            existing[h & 0xFFFFFFFF] = off(p)
            p = nx
    used = len(body.rstrip(b"\0"))
    cur = (used + 15) & ~15
    need = sum(((len(s.encode("utf-8")) + 1 + 15) & ~15) + 0x20 + 0x20 for s in strings.values())
    if cur + need > len(body):
        # the game only takes single power-of-two pages (every .yldb is 0x10000 or 0x20000);
        # 0x11000 made it quit silently as soon as the table loaded (Settings menu)
        size = len(body)
        while size < cur + need:
            size *= 2
        body.extend(b"\0" * (size - len(body)))
    for h, s in strings.items():
        sb = s.encode("utf-8") + b"\0"
        so = cur
        body[so:so + len(sb)] = sb
        cur += (len(sb) + 15) & ~15
        vo = cur
        st.pack_into("<16xQQ", body, vo, ptr(so), len(sb))
        cur += 0x20
        if h in existing:
            st.pack_into("<Q", body, existing[h] + 8, ptr(vo))
            continue
        no = cur
        b_i = h % cnt
        head = st.unpack_from("<Q", body, off(bp) + 8 * b_i)[0]
        st.pack_into("<QQQ", body, no, h, ptr(vo), head)
        st.pack_into("<Q", body, off(bp) + 8 * b_i, ptr(no))
        n_entries = st.unpack_from("<I", body, 0x20)[0]
        st.pack_into("<I", body, 0x20, n_entries + 1)
        cur += 0x20
    new_v3 = (v3 & ~0xFFFFFFF0) | len(body)
    st.pack_into("<Q", hdr, 8, new_v3)
    return bytes(hdr) + bytes(body), new_v3


def parse_text_table(path):
    """Read 'LABEL = text' / '0xHASH = text' lines -> {hash: text} (# comments allowed)."""
    out = {}
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            h = int(k, 16) if k.lower().startswith("0x") else label_hash(k)
            out[h] = v
    return out


def build_gxt2(entries):
    """GTA V style binary GXT2 (little endian): 'GXT2' magic (bytes '2TXG'), count,
    [hash, offset] sorted by hash, magic, end offset, NUL-terminated UTF-8 strings."""
    items = sorted(entries.items())
    off = (len(items) * 2 + 4) * 4
    table = bytearray()
    blob = bytearray()
    for h, s in items:
        table += struct.pack("<II", h, off)
        b = s.encode("utf-8") + b"\0"
        blob += b
        off += len(b)
    magic = struct.pack("<I", 0x47585432)
    return magic + struct.pack("<I", len(items)) + table + magic + struct.pack("<I", off) + blob


def read_gxt2(data):
    n = struct.unpack_from("<I", data, 4)[0]
    res = {}
    for i in range(n):
        h, o = struct.unpack_from("<II", data, 8 + 8 * i)
        res[h] = data[o:data.index(b"\0", o)].decode("utf-8")
    return res


def esc(s):
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    cmd = argv[0]
    if cmd == "hash":
        for a in argv[1:]:
            print("0x%08X %s" % (label_hash(a), a))
        return 0
    if cmd == "build":  # build <in.txt> <out.gxt2>  (binary GXT2)
        b = build_gxt2(parse_text_table(argv[1]))
        with open(argv[2], "wb") as fh:
            fh.write(b)
        print("wrote %s (%d bytes)" % (argv[2], len(b)))
        return 0
    if cmd == "read":  # read <file.gxt2>
        with open(argv[1], "rb") as fh:
            for h, s in sorted(read_gxt2(fh.read()).items()):
                print("0x%08X = %s" % (h, s))
        return 0
    if cmd == "grep":
        rx = re.compile(argv[2], re.I)
        with open(argv[1], encoding="utf-8") as fh:
            for line in fh:
                if rx.search(line.split("\t", 2)[-1]):
                    sys.stdout.buffer.write(line.encode("utf-8"))
        return 0
    if cmd == "file":
        with open(argv[1], "rb") as fh:
            d = parse_yldb(fh.read())
        out = open(argv[2], "w", encoding="utf-8", newline="\n") if len(argv) > 2 else sys.stdout
        for h, s in sorted(d.items()):
            out.write("0x%08X\t%s\n" % (h, esc(s)))
        return 0
    if cmd == "dump":
        rpf8.NAMES.load()
        arc = rpf8.RPF8(argv[1])
        inner = (argv[3] if len(argv) > 3 else "x64/data/lang/american_rel.rpf").lower()
        tgt = next((e for e in arc.entries if e.display_name().lower() == inner), None)
        if tgt is None:
            print("inner archive not found: " + inner, file=sys.stderr)
            return 2
        sub = arc.nested(tgt)
        n = 0
        with open(argv[2], "w", encoding="utf-8", newline="\n") as out:
            out.write("hash\tfile\ttext\n")
            for e in sub.entries:
                name = e.display_name()
                if not name.endswith(".yldb"):
                    continue
                try:
                    d = parse_yldb(sub.read_entry(e))
                except Exception as ex:  # noqa
                    print("skip %s: %s" % (name, ex), file=sys.stderr)
                    continue
                for h, s in d.items():
                    out.write("0x%08X\t%s\t%s\n" % (h, name, esc(s)))
                    n += 1
        print("%d strings -> %s" % (n, argv[2]))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
