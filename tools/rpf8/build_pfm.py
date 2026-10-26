#!/usr/bin/env python3
"""OPTIONAL: patched packfile cache (pfm.dat) for rebuilt archives.

appdata0_update.rpf/pfm.dat ("RPFC") caches every archive's 16+256+24*N header block
(and its names blob). If the game mounts an archive from this cache instead of reading
the TOC from the (LML-replaced) file, our modified TOC would be ignored (the archive then
behaves exactly like the original, because rebuild_archive keeps all original data at
its original offsets). This script writes a pfm.dat whose cached header blocks for the
given rebuilt archives are replaced by the new headers, for the LML replace path
lml/replace/appdata0_update/pfm.dat (seen in vfs.log as "packcache:/pfm.dat").
Only use it if the plain archive replacement has no effect. pfm.dat is game-version
specific: regenerate after every game update.

Usage: build_pfm.py <out_pfm.dat> <built.rpf>=<archive>:<inner path> ...
  e.g. build_pfm.py out/pfm.dat
         mod/.../startup_data.rpf=update_4.rpf:x64/data/ui/startup_data.rpf
         mod/.../american_rel.rpf=update_3.rpf:x64/data/lang/american_rel.rpf
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rpf8  # noqa: E402


def main(argv):
    out = argv[0]
    rpf8.NAMES.load()
    app = rpf8.RPF8(os.path.join(rpf8.GAME_DIR, "appdata0_update.rpf"))
    pe = next(e for e in app.entries if e.display_name() == "pfm.dat")
    pfm = bytearray(app.read_entry(pe))
    assert pfm[:4] == b"RPFC"
    for spec in argv[1:]:
        built, src = spec.split("=", 1)
        archive, inner = src.split(":", 1)
        top = rpf8.RPF8(os.path.join(rpf8.GAME_DIR, archive))
        ent = next(e for e in top.entries if e.display_name().lower() == inner.lower())
        orig = top.nested(ent)
        n = 16 + 256 + 24 * orig.count
        old_hdr = orig.read(0, n)
        with open(built, "rb") as fh:
            new_hdr = fh.read(n)
        pos = pfm.find(old_hdr)
        assert pos >= 0 and pfm.find(old_hdr, pos + 1) < 0, "cached header not found/unique for " + inner
        pfm[pos:pos + n] = new_hdr
        print("patched cached header of %s at 0x%X (%d bytes)" % (inner, pos, n))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(pfm)
    print("wrote %s (%d bytes, plain/unencrypted RPFC)" % (out, len(pfm)))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
