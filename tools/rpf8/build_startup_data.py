#!/usr/bin/env python3
"""Rebuild update_4.rpf -> x64/data/ui/startup_data.rpf with our settings_group_flow.ymt.

Usage: build_startup_data.py [modified_ymt] [out_rpf]
  modified_ymt default: mod/lml/DualSenseRDR2/data/ui/startup_data/settings/flow/settings_group_flow.ymt
  out_rpf      default: mod/lml/DualSenseRDR2/replace/update_4/x64/data/ui/startup_data.rpf
                        (LML legacy replace folder: lml/replace/update_4/x64/data/ui/startup_data.rpf)

All other entries are copied raw (see rpf8.rebuild_archive); the result is re-read and
verified (every entry decodes to the same bytes as in the original, ours to the new file).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rpf8  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
MOD = os.path.join(REPO, "mod", "lml", "DualSenseRDR2")
SRC_ARCHIVE = "update_4.rpf"
INNER = "x64/data/ui/startup_data.rpf"
TARGET = "settings/flow/settings_group_flow.ymt"


def open_inner(archive, inner):
    top = rpf8.RPF8(os.path.join(rpf8.GAME_DIR, archive))
    ent = next(e for e in top.entries if e.display_name().lower() == inner)
    return top, ent, top.nested(ent)


def verify(orig, built_path, replaced):
    """replaced: {entry_index: expected decoded bytes}"""
    new = rpf8.RPF8(built_path)
    assert new.count == orig.count and new.tag == 0xFF
    for i, (a, b) in enumerate(zip(orig.entries, new.entries)):
        assert a.hash == b.hash and a.ext_id == b.ext_id
        if i in replaced:
            got = new.read_entry(b)
            assert got == replaced[i], "replaced entry %d differs" % i
        else:
            assert (a.v1, a.v2, a.v3) == (b.v1, b.v2, b.v3), "TOC changed for entry %d" % i
            assert new.read_entry(b) == orig.read_entry(a), "entry %d differs" % i
    return new


def main(ymt, out):
    rpf8.NAMES.load()
    _, ent, sub = open_inner(SRC_ARCHIVE, INNER)
    h, _ = rpf8.path_hash(TARGET)
    idx = next(i for i, e in enumerate(sub.entries) if e.hash == h)
    with open(ymt, "rb") as fh:
        data = fh.read()
    built = rpf8.rebuild_archive(sub, {idx: data})
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(built)
    verify(sub, out, {idx: data})
    print("%s: %d entries, %d -> %d bytes; entry #%d 0x%08X (%s) replaced; verified OK"
          % (out, sub.count, sub.length, len(built), idx, h, TARGET))


if __name__ == "__main__":
    a = sys.argv[1:]
    main(a[0] if a else os.path.join(MOD, "data", "ui", "startup_data", "settings", "flow", "settings_group_flow.ymt"),
         a[1] if len(a) > 1 else os.path.join(MOD, "replace", "update_4", "x64", "data", "ui", "startup_data.rpf"))
