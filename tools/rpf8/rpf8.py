#!/usr/bin/env python3
"""RDR2 RPF8 archive reader (list / extract), our own implementation.

Format knowledge (header layout, entry bit fields, strided TFIT2-CBC encryption,
Oodle/deflate compression) was learned from public C# RPF8 tools; this is an
independent Python port of the algorithms. Key tables are NOT included: they are
loaded from a private .npz produced by convert_keys.py (default
third_party/downloads/rpf8/keys/tfit2_pc.npz, override with env RPF8_KEYS).

Usage:
  rpf8.py list <archive> [filter]            list entries (recurses into nested .rpf)
  rpf8.py extract <archive> <path-or-hash> <out>
  rpf8.py extract-all <archive> <filter> <outdir>
  rpf8.py info <archive>

Paths inside nested archives are written as "inner.rpf/<name>". Names come from
hash -> name dictionaries (names.txt lists + names.extra.txt + generated); unknown
names are shown as 0xHASH.ext.
"""
import ctypes
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DL = os.path.join(REPO, "third_party", "downloads", "rpf8")
KEYS_PATH = os.environ.get("RPF8_KEYS", os.path.join(DL, "keys", "tfit2_pc.npz"))
NAME_FILES = [
    os.path.join(DL, "src", "amr", "names.txt"),
    os.path.join(DL, "names.extra.txt"),
]
NAMES_CACHE = os.path.join(DL, "names_cache.json")
GAME_DIR = r"C:\Steam\steamapps\common\Red Dead Redemption 2"

MAGIC = 0x52504638
PLATFORM_PC = 121  # 'y'

BASE_EXTS = ["rpf", "#mf", "#dr", "#ft", "#dd", "#td", "#bn", "#bd", "#pd", "#bs", "#sd", "#mt", "#sc", "#cs"]
EXTRA_EXTS = ["mrf", "cut", "gfx", "#cd", "#ld", "#pmd", "#pm", "#ed", "#pt", "#map", "#typ", "#ch", "#ldb",
              "#jd", "#ad", "#nv", "#hn", "#pl", "#nd", "#vr", "#wr", "#nh", "#fd", "#as"]


def ext_for_id(eid, plat=PLATFORM_PC):
    c = chr(plat)
    if 0 <= eid < len(BASE_EXTS):
        return "." + BASE_EXTS[eid].replace("#", c)
    if 64 <= eid < 64 + len(EXTRA_EXTS):
        return "." + EXTRA_EXTS[eid - 64].replace("#", c)
    return ""


def ext_id_for(ext, plat=PLATFORM_PC):
    ext = ext.lstrip(".").lower()
    c = chr(plat)
    for i, e in enumerate(BASE_EXTS):
        if e.replace("#", c) == ext:
            return i
    for i, e in enumerate(EXTRA_EXTS):
        if e.replace("#", c) == ext:
            return 64 + i
    return 255


def joaat(s):
    h = 0
    for ch in s.encode("latin-1", "replace"):
        h = (h + ch) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def path_hash(path):
    """Hash used for an entry name: joaat of the path without extension if the extension
    is one of the known RAGE ids, otherwise joaat of the full name."""
    p = path.replace("\\", "/").lower()
    base, ext = os.path.splitext(p)
    if ext and ext_id_for(ext) != 255:
        return joaat(base), ext_id_for(ext)
    return joaat(p), 255


# ---------------------------------------------------------------- names
class Names:
    def __init__(self):
        self.map = {}
        self._loaded = False

    def add(self, name):
        name = name.strip().replace("\\", "/")
        if not name:
            return
        for n in {name, name.lower()}:
            h = joaat(n)
            self.map.setdefault(h, n)

    def load(self):
        if self._loaded:
            return self
        self._loaded = True
        stamp = []
        for f in NAME_FILES:
            if os.path.exists(f):
                st = os.stat(f)
                stamp.append([f, st.st_size, st.st_mtime])
        if os.path.exists(NAMES_CACHE):
            try:
                with open(NAMES_CACHE, encoding="utf-8") as fh:
                    c = json.load(fh)
                if c.get("stamp") == stamp:
                    self.map = {int(k): v for k, v in c["map"].items()}
                    return self
            except Exception:
                pass
        for f, _, _ in stamp:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "%platform%" in line:
                        self.add(line.replace("%platform%", "x64"))
                    else:
                        self.add(line)
                        # Many lists omit the platform prefix; also try with x64/
                        if line.startswith("data/") or line.startswith("anim/") or line.startswith("levels/"):
                            self.add("x64/" + line)
        try:
            os.makedirs(os.path.dirname(NAMES_CACHE), exist_ok=True)
            with open(NAMES_CACHE, "w", encoding="utf-8") as fh:
                json.dump({"stamp": stamp, "map": {str(k): v for k, v in self.map.items()}}, fh)
        except OSError:
            pass
        return self

    def get(self, h):
        return self.map.get(h)


NAMES = Names()


# ---------------------------------------------------------------- TFIT2 cipher
class Tfit2:
    _ctx = None

    @classmethod
    def ctx(cls):
        if cls._ctx is None:
            if not os.path.exists(KEYS_PATH):
                raise SystemExit("key file not found: %s (run convert_keys.py)" % KEYS_PATH)
            z = np.load(KEYS_PATH)
            c = {k: z[k] for k in z.files}
            c["key_map"] = {int(k): i for i, k in enumerate(c["key_ids"])}
            # Precompute per-round block input selector (0 -> lo half, 1 -> hi half)
            cls._ctx = c
        return cls._ctx

    SEL_B = np.array([0] * 8 + [1] * 8)
    SEL_C = np.array([0, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0])
    M01 = np.uint64(0x0101010101010101)
    M02 = np.uint64(0x0202020202020202)

    @staticmethod
    def _splat(half):
        # half: (N,) uint64 ; returns (8, N): v[i] = 0x0101.. * byte[7-i]
        out = np.empty((8, half.shape[0]), dtype=np.uint64)
        for i in range(8):
            out[i] = ((half >> np.uint64(8 * (7 - i))) & np.uint64(0xFF)) * Tfit2.M01
        return out

    @staticmethod
    def _parity_bits(x):
        x = x ^ (x >> np.uint64(1))
        x = x ^ (x >> np.uint64(2))
        x = x ^ (x >> np.uint64(4))
        x = x & Tfit2.M01
        x = x | (x >> np.uint64(7))
        x = x | (x >> np.uint64(14))
        x = x | (x >> np.uint64(28))
        return x

    @classmethod
    def _round(cls, r, lo, hi, key, sel):
        c = cls.ctx()
        masks = c["round_masks"][r]  # (16 blocks, 16)
        xors = c["round_xor"][r]
        lookup = c["round_lookup"][r]
        v = (cls._splat(lo), cls._splat(hi))
        out = [np.uint64(key[0]), np.uint64(key[1])]
        acc = [np.zeros_like(lo), np.zeros_like(lo)]
        for b in range(16):
            vin = v[sel[b]]
            m = masks[b]
            lower = m[8] & vin[0]
            upper = m[0] & vin[0]
            for k in range(1, 8):
                lower ^= m[8 + k] & vin[k]
                upper ^= m[k] & vin[k]
            lower = cls._parity_bits(lower)
            upper = upper ^ (upper << np.uint64(1))
            upper = upper ^ (upper >> np.uint64(2))
            upper = upper ^ (upper >> np.uint64(4))
            upper = upper & cls.M02
            upper = upper | (upper << np.uint64(7))
            upper = upper | (upper >> np.uint64(14))
            idx = (lower & np.uint64(0xFF)) ^ (upper & np.uint64(0xF00)) ^ xors[b]
            acc[b // 8] ^= lookup[idx.astype(np.intp)]
        return acc[0] ^ out[0], acc[1] ^ out[1]

    @classmethod
    def decrypt_blocks(cls, key_id, blocks):
        """ECB-decrypt (N,16) uint8 ciphertext blocks -> (N,16) uint8."""
        c = cls.ctx()
        key = c["keys"][c["key_map"][key_id]][1:]  # 17 x 2
        n = blocks.shape[0]
        init = c["init_tables"]
        lo = np.zeros(n, dtype=np.uint64)
        hi = np.zeros(n, dtype=np.uint64)
        for i in range(8):
            lo ^= init[i][blocks[:, i]]
            hi ^= init[8 + i][blocks[:, 8 + i]]
        lo, hi = cls._round(0, lo, hi, key[0], cls.SEL_B)
        lo, hi = cls._round(1, lo, hi, key[1], cls.SEL_B)
        for r in range(2, 16):
            lo, hi = cls._round(r, lo, hi, key[r], cls.SEL_C)
        lo, hi = cls._round(16, lo, hi, key[16], cls.SEL_B)
        # Round D
        v = (cls._splat(lo), cls._splat(hi))
        out = np.empty((n, 16), dtype=np.uint8)
        em, et, ex = c["end_masks"], c["end_tables"], c["end_xor"]
        for j in range(16):
            vin = v[j // 8]
            m = em[j]
            acc = m[0] & vin[0]
            for k in range(1, 8):
                acc ^= m[k] & vin[k]
            b = (cls._parity_bits(acc) & np.uint64(0xFF)).astype(np.uint8) ^ ex[j]
            out[:, j] = et[j][b]
        return out


class CbcDecoder:
    """Stateful CBC decoder: like the reference, the IV chains across successive
    decode() calls on the same object (segments of one file)."""

    def __init__(self, key_id):
        self.key_id = key_id
        self.iv = np.frombuffer(bytes(Tfit2.ctx()["iv"]), dtype=np.uint8).copy()

    def decode(self, buf, start, length, chunk=1 << 15):
        nblk = length // 16
        if nblk == 0:
            return
        ct = np.frombuffer(bytes(buf[start:start + nblk * 16]), dtype=np.uint8).reshape(nblk, 16)
        pt = np.empty_like(ct)
        for s in range(0, nblk, chunk):
            pt[s:s + chunk] = Tfit2.decrypt_blocks(self.key_id, ct[s:s + chunk])
        prev = np.vstack([self.iv[None, :], ct[:-1]])
        pt ^= prev
        buf[start:start + nblk * 16] = pt.tobytes()
        self.iv = ct[-1].copy()


def strided_segments(config, file_size, chunk_size):
    res = []
    state = {"off": 0}

    def upd(s, e):
        s = max(s, state["off"])
        e = min(e, file_size)
        if s < e:
            res.append((s, e))
            state["off"] = e

    tail_off = file_size - 0x400
    head = blen = stride = 0
    if config & 3:
        head = 0x400 << ((config & 3) * 2)
    lc = (config >> 2) & 7
    if lc:
        blen = 0x400 << lc
        stride = (((config >> 5) & 7) + 1) << 16
    upd(0, head)
    if head < tail_off:
        if blen or stride:
            if stride == chunk_size and tail_off < stride < file_size:
                state["off"] = stride
            else:
                block = stride if state["off"] else 0
                while block + blen <= tail_off:
                    upd(block, block + blen)
                    block += stride
        upd(tail_off, file_size)
    return res


# ---------------------------------------------------------------- Oodle
_oodle = None


def oodle():
    global _oodle
    if _oodle is None:
        src = os.path.join(GAME_DIR, "oo2core_5_win64.dll")
        d = os.path.join(tempfile.gettempdir(), "rpf8py_oodle")
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, "oo2core_5_win64.dll")
        if not os.path.exists(dst):
            shutil.copyfile(src, dst)
        lib = ctypes.WinDLL(dst)
        f = lib.OodleLZ_Decompress
        f.restype = ctypes.c_int64
        f.argtypes = [ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int64] + [ctypes.c_int] * 9 + [
            ctypes.c_int]
        _oodle = f
    return _oodle


def oodle_decompress(data, size):
    out = ctypes.create_string_buffer(size)
    n = oodle()(bytes(data), len(data), out, size, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3)
    if n != size:
        raise ValueError("Oodle decompression failed (%d != %d)" % (n, size))
    return out.raw


_oodle_c = None


def oodle_compress(data, fmt=8, level=4):
    """OodleLZ_Compress (default Kraken / Normal) via the game's oo2core_5 DLL."""
    global _oodle_c
    if _oodle_c is None:
        oodle()
        lib = ctypes.WinDLL(os.path.join(tempfile.gettempdir(), "rpf8py_oodle", "oo2core_5_win64.dll"))
        f = lib.OodleLZ_Compress
        f.restype = ctypes.c_int64
        f.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int64, ctypes.c_char_p, ctypes.c_int,
                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
        _oodle_c = f
    data = bytes(data)
    out = ctypes.create_string_buffer(len(data) + 65536 + len(data) // 2)
    n = _oodle_c(fmt, data, len(data), out, level, None, None, None, None, 0)
    if n <= 0:
        raise ValueError("Oodle compression failed")
    comp = out.raw[:n]
    assert oodle_decompress(comp, len(data)) == data
    return comp


# ---------------------------------------------------------------- archive
class Entry:
    __slots__ = ("v1", "v2", "v3", "archive", "index", "name")

    def __init__(self, v1, v2, v3, archive, index):
        self.v1, self.v2, self.v3 = v1, v2, v3
        self.archive = archive
        self.index = index
        self.name = None

    hash = property(lambda s: s.v1 & 0xFFFFFFFF)
    enc_config = property(lambda s: (s.v1 >> 32) & 0xFF)
    key_id = property(lambda s: (s.v1 >> 40) & 0xFF)
    ext_id = property(lambda s: (s.v1 >> 48) & 0xFF)
    is_resource = property(lambda s: bool((s.v1 >> 56) & 1))
    is_signed = property(lambda s: bool((s.v1 >> 57) & 1))
    disk_size = property(lambda s: (s.v2 & 0xFFFFFFF) << 4)
    offset = property(lambda s: ((s.v2 >> 28) & 0x7FFFFFFF) << 4)
    compressor = property(lambda s: (s.v2 >> 59) & 0x1F)
    resource_version = property(lambda s: (s.v3 >> 32) & 0xF)

    @property
    def size(self):
        if not self.is_resource:
            return self.v3 & 0xFFFFFFFF
        return (self.v3 & 0xFFFFFFF0) + ((self.v3 >> 32) & 0xFFFFFFF0)

    @property
    def ext(self):
        return ext_for_id(self.ext_id, self.archive.platform)

    def display_name(self):
        if self.name:
            return self.name
        n = NAMES.get(self.hash)
        if n is not None:
            return n + self.ext
        return "0x%08X%s" % (self.hash, self.ext)

    def attrs(self):
        a = []
        if self.is_resource:
            a.append("rsc(v%d)" % self.resource_version)
        if self.compressor:
            a.append(["", "deflate", "oodle"][self.compressor] if self.compressor < 3 else "comp%d" % self.compressor)
        if self.key_id != 255:
            a.append("enc(k%d,c%02x)" % (self.key_id, self.enc_config))
        if self.is_signed:
            a.append("signed")
        return ",".join(a)


class RPF8:
    def __init__(self, path, base=0, length=None, fh=None, vpath=None):
        self.path = path
        self.vpath = vpath or os.path.basename(path)
        self.fh = fh or open(path, "rb")
        self.base = base
        if length is None:
            self.fh.seek(0, 2)
            length = self.fh.tell()
        self.length = length
        self._read_header()

    def read(self, off, n):
        self.fh.seek(self.base + off)
        return self.fh.read(n)

    def _read_header(self):
        magic, count, names_len, tag, plat = struct.unpack("<IiiHH", self.read(0, 16))
        if magic != MAGIC:
            raise ValueError("%s: not an RPF8 archive" % self.vpath)
        self.count, self.names_len, self.tag, self.platform = count, names_len, tag, plat
        toc = bytearray(self.read(16 + 0x100, count * 24))
        if tag != 255:
            CbcDecoder(tag).decode(toc, 0, len(toc))
        self.entries = []
        for i in range(count):
            v1, v2, v3 = struct.unpack_from("<QQQ", toc, i * 24)
            self.entries.append(Entry(v1, v2, v3, self, i))
        self.names_blob = self.read(self.length - names_len, names_len) if names_len else b""

    def read_entry(self, e, rsc_header=True):
        off = e.offset
        raw = e.disk_size
        if e.is_signed:
            # 0x100-byte signature is appended AFTER the data (the C# references skip it at
            # the front, which breaks decompression of signed entries)
            raw -= 0x100
        rsc_hdr = None
        if e.is_resource:
            rsc_hdr = self.read(off, 16)
            off += 16
            raw -= 16
        data = bytearray(self.read(off, raw))
        if e.key_id != 255:
            comp = e.compressor != 0
            if e.is_resource:
                chunk = 0x80000 if comp else e.size
            else:
                chunk = 0x2000 if comp else 0x1000
            dec = CbcDecoder(e.key_id)
            for s, t in strided_segments(e.enc_config, raw, chunk):
                dec.decode(data, s, t - s)
        if e.compressor == 0:
            out = bytes(data[:e.size])
        elif e.compressor == 1:
            out = zlib.decompress(bytes(data), -15)
        elif e.compressor == 2:
            out = oodle_decompress(data, e.size)
        else:
            raise ValueError("unknown compressor %d" % e.compressor)
        if e.is_resource and rsc_header:
            # Rebuild an unencrypted/uncompressed RSC8 header (like the reference tools)
            val1 = (e.resource_version & 0xFF) | (0x1F << 8) | (0 << 16) | (0 << 24)
            out = struct.pack("<IIQ", 0x38435352, val1, e.v3) + out
        return out

    def nested(self, e):
        """Open a nested .rpf entry (stored raw) as an RPF8 view onto the same file."""
        if e.compressor != 0 or e.key_id != 255:
            return RPF8Mem(self.read_entry(e), vpath=self.vpath + "/" + e.display_name())
        return RPF8(self.path, base=self.base + e.offset, length=e.size, fh=self.fh,
                    vpath=self.vpath + "/" + e.display_name())

    def walk(self, recurse=True, prefix=""):
        """Yield (virtual_path, archive, entry)."""
        for e in self.entries:
            name = e.display_name()
            vp = prefix + name
            yield vp, self, e
            if recurse and e.ext_id == 0:
                try:
                    sub = self.nested(e)
                except Exception as ex:  # noqa
                    print("warn: cannot open nested %s: %s" % (vp, ex), file=sys.stderr)
                    continue
                yield from sub.walk(True, vp + "/")


class RPF8Mem(RPF8):
    def __init__(self, data, vpath):
        import io
        super().__init__(vpath, fh=io.BytesIO(data), vpath=vpath)


# ---------------------------------------------------------------- writer
RSC8_MAGIC = 0x38435352


def make_plain_rsc8(version, v3, body):
    """RSC8 header for an unencrypted, uncompressed, unsigned resource + body."""
    val1 = (version & 0xFF) | (0x1F << 8)  # compressor 0x1F = none, keyid+1 = 0 = none, cfg 0
    return struct.pack("<IIQ", RSC8_MAGIC, val1, v3) + body


def _v2(off, disk, comp_id):
    assert off % 16 == 0 and (off >> 4) < (1 << 31) and (disk >> 4) < (1 << 28)
    return ((disk >> 4) & 0xFFFFFFF) | ((off >> 4) << 28) | (comp_id << 59)


def rebuild_archive(arc, replacements, additions=None):
    """Return the bytes of `arc` (an RPF8, may be a nested view) with some entries replaced
    and (optionally) new entries added.

    replacements: {entry_index: bytes | (bytes, "oodle")}. For normal entries the bytes are the plain file
    content; for resource entries (e.is_resource) they must be a full RSC8 file
    (16-byte header + body, see make_plain_rsc8), whose header Val2 becomes TOC v3.
    additions: {archive_path: bytes | (bytes, "oodle")}, e.g. {"settings/screens/x.ymt": data}. New
    NON-resource entries; the name hash is path_hash(path) (joaat of the lower-case path without the
    extension, extension -> ext id). The name itself is not stored anywhere (RPF8 entries only carry
    the hash; the names blob at the end is opaque/encrypted and is kept unchanged).
    Strategy (append-only, like the public RPF8 tools' import):
      * the original archive body is copied byte-for-byte, so every untouched entry keeps
        its raw (encrypted/compressed/signed) data AND its original offset;
      * replaced data is appended after the body, stored unencrypted (key 0xFF),
        uncompressed (or Oodle), unsigned; the old data stays in place (harmless);
      * with additions the TOC grows by 24 bytes per entry. The game's TOC is sorted by name hash
        (unsigned, verified on the shipped archives) so it can be binary-searched: the new TOC is
        sorted the same way. Entries whose data would overlap the grown TOC (the first ones after
        the old TOC: the archives are packed without slack) are moved, raw, to the end; only their
        offset field changes (the per-entry cipher does not depend on the position);
      * the original names blob is re-appended at the end (names_len unchanged);
      * the TOC is written in plain text (header decryption tag = 0xFF, since we only have
        the decrypt direction of the whitebox cipher); the 0x100-byte header signature block
        is kept as is.
    """
    additions = additions or {}
    raw = arc.read(0, arc.length)
    body_end = arc.length - arc.names_len
    out = bytearray(raw[:body_end])
    entries = [[e.v1, e.v2, e.v3] for e in arc.entries]

    def pad16():
        out.extend(b"\0" * (-len(out) % 16))

    count = arc.count + len(additions)
    data_start = 0x110 + 24 * count
    data_start += -data_start % 16
    if additions:
        pad16()
        for i, e in enumerate(arc.entries):
            if i in replacements or e.disk_size == 0 or e.offset >= data_start:
                continue
            # this entry's data sits where the grown TOC goes: move it (raw) to the end
            blob = raw[e.offset:e.offset + e.disk_size]
            off = len(out)
            out.extend(blob)
            pad16()
            v2 = entries[i][1]
            v2 &= ~(0x7FFFFFFF << 28)
            v2 |= (off >> 4) << 28
            entries[i][1] = v2
        while len(out) < data_start:
            out.append(0)

    for idx, data in sorted(replacements.items()):
        compress = None
        if isinstance(data, tuple):
            data, compress = data
        e = arc.entries[idx]
        if e.is_resource:
            magic, val1, val2 = struct.unpack_from("<IIQ", data, 0)
            assert magic == RSC8_MAGIC, "resource replacement must start with an RSC8 header"
            v3 = val2
            body = data[16:]
            if compress == "oodle":
                val1 = (val1 & ~(0x1F << 8)) | (1 << 8)  # RSC8 compressor field = id - 1
                body = oodle_compress(body)
            stored = struct.pack("<IIQ", magic, val1, val2) + body
        else:
            v3 = len(data)
            stored = oodle_compress(data) if compress == "oodle" else data
        comp_id = 2 if compress == "oodle" else 0
        pad16()
        off = len(out)
        out.extend(stored)
        pad16()
        disk = len(out) - off
        v1 = e.v1
        v1 &= ~((0xFF << 32) | (0xFF << 40) | (1 << 57))  # enc cfg 0, key id, signed off
        v1 |= 0xFF << 40                                    # key id 0xFF = not encrypted
        v2 = _v2(off, disk, comp_id)
        entries[idx] = [v1, v2, v3]
    existing = {e.hash for e in arc.entries}
    for path, data in sorted(additions.items()):
        compress = None
        if isinstance(data, tuple):
            data, compress = data
        h, eid = path_hash(path)
        assert eid != 255, "unknown extension: " + path
        assert h not in existing, "an entry with the hash of %s already exists" % path
        existing.add(h)
        stored = oodle_compress(data) if compress == "oodle" else bytes(data)
        pad16()
        off = len(out)
        out.extend(stored)
        pad16()
        disk = len(out) - off
        v1 = h | (0 << 32) | (0xFF << 40) | (eid << 48)    # enc cfg 0, key 0xFF (plain), not rsc/signed
        entries.append([v1, _v2(off, disk, 2 if compress == "oodle" else 0), len(data)])
    entries.sort(key=lambda x: x[0] & 0xFFFFFFFF)
    pad16()
    out.extend(raw[body_end:])  # names blob
    toc = b"".join(struct.pack("<QQQ", *x) for x in entries)
    assert len(entries) == count and 0x110 + len(toc) <= data_start
    hdr = struct.pack("<IiiHH", MAGIC, count, arc.names_len, 0xFF, arc.platform)
    out[0:16] = hdr
    # out[16:0x110] = original signature block (kept)
    out[0x110:0x110 + len(toc)] = toc
    return bytes(out)


def lookup_hash(arc, h):
    """Binary search of the (hash-sorted) TOC, the way the game looks a name hash up."""
    lo, hi = 0, arc.count - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        m = arc.entries[mid].hash
        if m == h:
            return arc.entries[mid]
        if m < h:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def find_entry(arc, query):
    q = query.replace("\\", "/").lower()
    hq = None
    m = re.fullmatch(r"0x([0-9a-f]{1,8})(\..*)?", q)
    if m:
        hq = int(m.group(1), 16)
    for vp, a, e in arc.walk():
        if vp.lower() == q or vp.lower().endswith("/" + q):
            return vp, a, e
        if hq is not None and e.hash == hq:
            return vp, a, e
    # by hash of the given path
    h, eid = path_hash(q.split(".rpf/")[-1])
    for vp, a, e in arc.walk():
        if e.hash == h:
            return vp, a, e
    return None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd = argv[0]
    NAMES.load()
    arc = RPF8(argv[1])
    if cmd == "info":
        print("entries=%d names_len=%d tag=%d platform=%d" % (arc.count, arc.names_len, arc.tag, arc.platform))
        return 0
    if cmd == "list":
        flt = argv[2].lower() if len(argv) > 2 else None
        for vp, a, e in arc.walk():
            if flt and flt not in vp.lower():
                continue
            print("%-90s %10d %10d %s" % (vp, e.size, e.disk_size, e.attrs()))
        return 0
    if cmd == "extract":
        r = find_entry(arc, argv[2])
        if not r:
            print("not found: " + argv[2], file=sys.stderr)
            return 2
        vp, a, e = r
        data = a.read_entry(e)
        out = argv[3]
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "wb") as fh:
            fh.write(data)
        print("%s -> %s (%d bytes)" % (vp, out, len(data)))
        return 0
    if cmd == "extract-all":
        flt = argv[2].lower()
        outdir = argv[3]
        n = 0
        for vp, a, e in arc.walk():
            if flt not in vp.lower() or e.ext_id == 0:
                continue
            rel = vp.split(".rpf/")[-1]
            dst = os.path.join(outdir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as fh:
                fh.write(a.read_entry(e))
            n += 1
        print("extracted %d files" % n)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
