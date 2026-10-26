"""Convert a C# KeysContainer.cs (RDR2 TFIT2 key tables, PC) into a compact .npz.

Usage: python -I convert_keys.py <KeysContainer.cs> <out.npz>

The output is private research data (key material) - do NOT ship it.
Parses the compact (hex literal) layout of the file: one key per line in the
keysValues dictionary, then the tfit2Context block (EndXor, EndTables, EndMasks,
Rounds, InitTables).
"""
import re
import sys

import numpy as np

HEX = re.compile(r"0x([0-9A-Fa-f]+)")


def nums(s):
    return [int(m, 16) for m in HEX.findall(s)]


def main(src, dst):
    lines = open(src, encoding="utf-8-sig").read().splitlines()
    iv = None
    keys = {}
    i = 0
    n = len(lines)
    ctx = {}
    while i < n:
        ln = lines[i]
        if iv is None and "byte[] iv" in ln:
            iv = bytes(nums(ln))
        m = re.match(r"\s*\{(\d+),new Tfit2Key\(\)", ln)
        if m:
            v = nums(ln)
            assert len(v) == 36, (m.group(1), len(v))
            keys[int(m.group(1))] = np.array(v, dtype=np.uint64).reshape(18, 2)
        if "EndXor" in ln:
            ctx["end_xor"] = np.array(nums(ln.split("]", 1)[1]), dtype=np.uint8)
        for name, cnt in (("EndTables", 16), ("EndMasks", 16), ("InitTables", 16), ("Rounds", 17)):
            if re.match(r"\s*%s\s*=" % name, ln):
                rows = []
                j = i + 1
                while len(rows) < cnt:
                    if "new " in lines[j]:
                        rows.append(lines[j])
                    j += 1
                if name == "EndTables":
                    ctx["end_tables"] = np.array([nums(r) for r in rows], dtype=np.uint8)
                elif name == "EndMasks":
                    ctx["end_masks"] = np.array([nums(r) for r in rows], dtype=np.uint64)
                elif name == "InitTables":
                    ctx["init_tables"] = np.array([nums(r) for r in rows], dtype=np.uint64)
                else:
                    lookups, masks, xors = [], [], []
                    for r in rows:
                        lk, bl = r.split("Blocks=", 1)
                        lookups.append(nums(lk))
                        blocks = re.split(r"new Block\s*\{", bl)[1:]
                        assert len(blocks) == 16
                        mm, xx = [], []
                        for b in blocks:
                            ms, xs = b.split("Xor=")
                            mm.append(nums(ms))
                            xx.append(nums(xs)[0])
                        masks.append(mm)
                        xors.append(xx)
                    ctx["round_lookup"] = np.array(lookups, dtype=np.uint64)
                    ctx["round_masks"] = np.array(masks, dtype=np.uint64)
                    ctx["round_xor"] = np.array(xors, dtype=np.uint64)
                i = j - 1
        i += 1
    assert ctx["end_tables"].shape == (16, 256)
    assert ctx["end_masks"].shape == (16, 8)
    assert ctx["init_tables"].shape == (16, 256)
    assert ctx["round_lookup"].shape == (17, 4096)
    assert ctx["round_masks"].shape == (17, 16, 16)
    ids = sorted(keys)
    np.savez_compressed(dst, iv=np.frombuffer(iv, dtype=np.uint8), key_ids=np.array(ids, dtype=np.int32),
                        keys=np.stack([keys[k] for k in ids]), **ctx)
    print("keys:", len(ids), "ids", ids[0], "..", ids[-1])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
