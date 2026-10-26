#!/usr/bin/env python3
"""Recover unknown RPF8 entry names (hashes) for the UI archives by brute-force
candidate generation from strings found in the extracted files themselves.

Usage: recover_names.py <rawdir> <out_names.txt>
Candidates = known directories of each nested archive x name tokens harvested from
all extracted files (text payloads, attribute values, path fragments). Matches are
appended to <out_names.txt> as full in-archive relative paths (no extension); copy
or append them to third_party/downloads/rpf8/names.extra.txt to make rpf8.py show them.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpf8  # noqa: E402
import numpy as np  # noqa: E402

M32 = np.uint64(0xFFFFFFFF)


def joaat_state(prefix):
    h = 0
    for ch in prefix.encode("latin-1", "replace"):
        h = (h + ch) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    return h


class TokenBatch:
    def __init__(self, toks):
        self.toks = sorted(toks)
        enc = [t.encode("latin-1", "replace") for t in self.toks]
        self.lens = np.array([len(b) for b in enc])
        L = int(self.lens.max())
        self.arr = np.zeros((len(enc), L), dtype=np.uint64)
        for i, b in enumerate(enc):
            self.arr[i, :len(b)] = np.frombuffer(b, dtype=np.uint8)

    def hashes(self, prefix):
        h = np.full(len(self.toks), joaat_state(prefix), dtype=np.uint64)
        for j in range(self.arr.shape[1]):
            m = self.lens > j
            x = (h + self.arr[:, j]) & M32
            x = (x + (x << np.uint64(10))) & M32
            x ^= x >> np.uint64(6)
            h = np.where(m, x, h)
        h = (h + (h << np.uint64(3))) & M32
        h ^= h >> np.uint64(11)
        h = (h + (h << np.uint64(15))) & M32
        return h.astype(np.uint32)

ARCHIVES = ["data_0", "update_4"]


def harvest_tokens(rawdir):
    toks = set()
    paths = set()
    rx = re.compile(rb"[A-Za-z0-9_\-./\\:]{2,120}")
    for r, _, fs in os.walk(rawdir):
        for f in fs:
            base = os.path.splitext(f)[0].lower()
            toks.add(base)
            with open(os.path.join(r, f), "rb") as fh:
                data = fh.read()
            for m in rx.findall(data):
                s = m.decode("latin-1").lower().replace("\\", "/").strip("/.")
                if not s:
                    continue
                s = re.sub(r"\.(ymt|xml|meta|rpf)$", "", s)
                for pre in ("update:/", "platform:/", "common:/", "x64/", "data/ui/", "ui/"):
                    if s.startswith(pre):
                        s = s[len(pre):]
                if "/" in s:
                    paths.add(s)
                    parts = s.split("/")
                    for i in range(len(parts)):
                        paths.add("/".join(parts[i:]))
                    toks.update(parts)
                else:
                    toks.add(s)
    return toks, paths


def main(rawdir, out):
    rpf8.NAMES.load()
    toks, paths = harvest_tokens(rawdir)
    # derived tokens: common suffix/prefix variants
    extra = set()
    for t in list(toks):
        for suf in ("_flow", "_launcher_flow", "_root", "_index", "_main", "_screen", "_list", "_menu"):
            extra.add(t + suf)
            if t.endswith(suf):
                extra.add(t[: -len(suf)])
    toks |= extra
    toks = {t for t in toks if 1 < len(t) < 64 and re.fullmatch(r"[a-z0-9_\-]+", t) and not t.isdigit()}
    batch = TokenBatch(toks)
    print("tokens", len(toks), "paths", len(paths), file=sys.stderr)
    found = {}
    for an in ARCHIVES:
        arc = rpf8.RPF8(os.path.join(rpf8.GAME_DIR, an + ".rpf"))
        for e in arc.entries:
            if e.ext_id != 0:
                continue
            nm = e.display_name()
            if "data/ui/" not in nm:
                continue
            sub = arc.nested(e)
            unknown = {x.hash: x for x in sub.entries if rpf8.NAMES.get(x.hash) is None}
            if not unknown:
                continue
            dirs = {""}
            for x in sub.entries:
                n = rpf8.NAMES.get(x.hash)
                if n:
                    parts = n.split("/")[:-1]
                    for i in range(len(parts) + 1):
                        dirs.add("/".join(parts[:i]))
            hits = 0
            for c in paths:
                h = rpf8.joaat(c)
                if h in unknown and h not in found:
                    found[h] = c
                    hits += 1
            ukeys = np.array(sorted(unknown), dtype=np.uint32)
            for d in sorted(dirs):
                pre = d + "/" if d else ""
                hs = batch.hashes(pre)
                for i in np.nonzero(np.isin(hs, ukeys))[0]:
                    h = int(hs[i])
                    if h not in found:
                        found[h] = pre + batch.toks[i]
                        hits += 1
            cands = len(dirs) * len(batch.toks) + len(paths)
            print("%s/%s: unknown=%d recovered=%d (cands=%d)" % (an, nm, len(unknown), hits, cands),
                  file=sys.stderr)
    with open(out, "a", encoding="utf-8") as fh:
        for h, c in sorted(found.items(), key=lambda kv: kv[1]):
            fh.write(c + "\n")
    print("recovered %d names -> %s" % (len(found), out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
