#!/usr/bin/env python3
"""Rebuild update_3.rpf -> x64/data/lang/<lang>_rel.rpf with our labels added to settings.yldb.

Usage: build_lang.py [--all] [out_dir]
       build_lang.py --test <outroot> [ABCDE]   isolation variants (see VARIANTS)
  default language: american only (--all: every <lang>_rel.rpf, English text everywhere)
  out_dir default: mod/lml/DualSenseRDR2/replace/update_3/x64/data/lang
                   (LML legacy replace folder: lml/replace/update_3/x64/data/lang/<lang>_rel.rpf)

Labels come from make_lml_dualsense.LABELS (the Settings row) and dualsense_settings.labels()
(the page); keys are joaat(lower(label)). The modified
settings.yldb is stored as an unencrypted, uncompressed RSC8 resource; every other entry
is copied raw. The result is re-read and verified, and the new labels are looked up.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rpf8  # noqa: E402
import gxt2  # noqa: E402
from build_startup_data import open_inner, verify, REPO  # noqa: E402
import dualsense_settings  # noqa: E402
from make_lml_dualsense import LABELS as ROW_LABELS  # noqa: E402

# the Settings row + every text of the DualSense page
LABELS = dict(ROW_LABELS, **dualsense_settings.labels())

SRC_ARCHIVE = "update_3.rpf"
YLDB = "settings.yldb"
LANGS = ["american", "brazilian", "chinesesimp", "chinesetrad", "french", "german", "italian",
         "japanese", "korean", "mexican", "polish", "russian", "spanish"]


def build(lang, out_dir, modify=True, compress="oodle", replace=True, out_name=None):
    """modify: add our labels; compress: None | "oodle" storage of the new settings.yldb;
    replace=False: no entry replaced at all (archive rewritten with plain TOC only)."""
    inner = "x64/data/lang/%s_rel.rpf" % lang
    _, ent, sub = open_inner(SRC_ARCHIVE, inner)
    h, _ = rpf8.path_hash(YLDB)
    idx = next(i for i, e in enumerate(sub.entries) if e.hash == h)
    e = sub.entries[idx]
    rsc = sub.read_entry(e)  # plain RSC8 header + body
    new_rsc, new_v3 = rsc, e.v3
    if modify:
        strings = {gxt2.label_hash(k): v for k, v in LABELS.items()}
        new_rsc, new_v3 = gxt2.yldb_add_strings(rsc, strings)
    repl = {idx: (new_rsc, compress)} if replace else {}
    built = rpf8.rebuild_archive(sub, repl)
    out = os.path.join(out_dir, out_name or "%s_rel.rpf" % lang)
    os.makedirs(out_dir, exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(built)
    new = verify(sub, out, {idx: new_rsc} if replace else {})
    table = gxt2.parse_yldb(new.read_entry(new.entries[idx]))
    old = gxt2.parse_yldb(rsc)
    if modify and replace:
        for k, v in LABELS.items():
            assert table[gxt2.label_hash(k)] == v
    assert all(table[k] == v for k, v in old.items())
    ne = new.entries[idx]
    print("%s: %d -> %d bytes; settings.yldb %s (v1 0x%X v2 0x%X v3 0x%X, %s); strings %d -> %d; verified OK"
          % (out, sub.length, len(built), "replaced" if replace else "untouched", ne.v1, ne.v2, ne.v3,
             ne.attrs() or "plain", len(old), len(table)))


VARIANTS = {  # name: (modify, compress, replace)
    "A": (False, None, False),     # no content change, only the rewritten (plain) TOC
    "B": (True, "oodle", True),    # our labels, resource stored Oodle-compressed, unencrypted
    "C": (False, None, True),      # unmodified settings.yldb re-stored plain/uncompressed
    "D": (False, "oodle", True),   # unmodified settings.yldb re-stored Oodle, unencrypted
    "E": (True, None, True),       # our labels, plain/uncompressed (= the build that crashed)
}


def main(argv):
    rpf8.NAMES.load()
    if argv and argv[0] == "--test":  # --test <outroot> [variants]: <outroot>/<V>/american_rel.rpf
        root = argv[1]
        for v in (argv[2] if len(argv) > 2 else "ABCD"):
            m, c, r = VARIANTS[v]
            build("american", os.path.join(root, v), m, c, r)
        return
    langs = LANGS if "--all" in argv else ["american"]
    rest = [a for a in argv if a != "--all"]
    out_dir = rest[0] if rest else os.path.join(REPO, "mod", "lml", "DualSenseRDR2", "replace", "update_3",
                                                "x64", "data", "lang")
    for lang in langs:
        build(lang, out_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
