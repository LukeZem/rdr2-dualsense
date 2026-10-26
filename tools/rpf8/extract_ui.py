#!/usr/bin/env python3
"""Extract the newest copy of every x64/data/ui/** file from the RDR2 archives.

Usage: extract_ui.py <outdir> [filter-substring ...]

Archive priority (later wins): data_0, common_0, update_1, update_2, update_3, update_4.
Path normalisation:
  data/ui/...                  (data_0)   -> x64/data/ui/...
  x64/data/ui/...              (update_4) -> x64/data/ui/...
  common/data/ui/... (update_1/common_0)  -> common/data/ui/...
  nested archive  x64/data/ui/widgets.rpf/<p>  -> x64/data/ui/widgets/<p>
Override semantics: loose files override per file; a nested archive (e.g.
x64/data/ui/flow.rpf) is replaced as a WHOLE by the newest archive that contains it,
so files that only exist in an older copy of a nested archive are NOT extracted
(they are listed in _stale.tsv instead).
Writes <outdir>/_manifest.tsv (path, archive, virtual path, size, attrs).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rpf8  # noqa: E402

ORDER = ["data_0", "common_0", "update_1", "update_2", "update_3", "update_4"]


def norm(vp, arcname):
    p = vp.replace(".rpf/", "/")
    if arcname == "common_0" and p.startswith("data/"):
        p = "common/" + p
    if p.startswith("data/"):
        p = "x64/" + p
    return p


def main(outdir, filters):
    rpf8.NAMES.load()
    best = {}
    containers = {}  # normalized nested-archive path -> newest archive name
    for an in ORDER:
        arc = rpf8.RPF8(os.path.join(rpf8.GAME_DIR, an + ".rpf"))
        for e in arc.entries:
            if e.ext_id == 0:
                containers[norm(e.display_name(), an)[:-4]] = an
    stale = []
    for an in ORDER:
        path = os.path.join(rpf8.GAME_DIR, an + ".rpf")
        arc = rpf8.RPF8(path)
        for vp, a, e in arc.walk():
            if e.ext_id == 0:
                continue
            p = norm(vp, an)
            if not p.startswith(("x64/data/ui/", "common/data/ui/")) or "loading_screen_images" in p:
                continue
            if filters and not any(f in p.lower() for f in filters):
                continue
            if ".rpf/" in vp:
                cont = norm(vp.split(".rpf/")[0] + ".rpf", an)[:-4]
                if containers.get(cont) != an:
                    stale.append((p, an, vp))
                    continue
            best[p] = (an, vp, a, e)
    with open(os.path.join(outdir, "_stale.tsv"), "w", encoding="utf-8") as sf:
        sf.write("path\tarchive\tvirtual_path  (superseded: its nested archive is replaced by a newer one)\n")
        for row in stale:
            sf.write("\t".join(row) + "\n")
    with open(os.path.join(outdir, "_manifest.tsv"), "w", encoding="utf-8") as mf:
        mf.write("path\tarchive\tvirtual_path\tsize\tattrs\n")
        for p in sorted(best):
            an, vp, a, e = best[p]
            dst = os.path.join(outdir, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                data = a.read_entry(e)
            except Exception as ex:  # noqa
                print("FAILED %s (%s %s): %s" % (p, an, e.attrs(), ex), file=sys.stderr)
                mf.write("%s\t%s.rpf\t%s\t-1\tFAILED %s\n" % (p, an, vp, ex))
                continue
            with open(dst, "wb") as fh:
                fh.write(data)
            mf.write("%s\t%s.rpf\t%s\t%d\t%s\n" % (p, an, vp, len(data), e.attrs()))
    print("extracted %d files to %s" % (len(best), outdir))


if __name__ == "__main__":
    os.makedirs(sys.argv[1], exist_ok=True)
    main(sys.argv[1], [f.lower() for f in sys.argv[2:]])
