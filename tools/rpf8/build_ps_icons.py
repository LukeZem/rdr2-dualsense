#!/usr/bin/env python3
"""PlayStation button icons everywhere the game shows a controller.

The game already contains Rockstar's own PlayStation art (ps4_button_<n>_img, controller_ps4, ...) but on PC it
draws the Xbox textures. This copies the PlayStation pixels over the Xbox ones - same size, same format; the ten
combo icons button_48-57 have no PS art and stay - and writes the two texture dictionaries as loose files for LML's
FileReplacement (install.xml):

  data/gamepad_icons_pc.ytd       update:/x64/data/cdimages/scaleform_platform_pc/gamepad_icons_pc.ytd  button prompts
  data/pm_settings_controls.ytd   update:/x64/textures/ui/ui_platform/pm_settings_controls.ytd          Settings picture

Loose resource format: RSC8, u32 0x01000002, u64 the resource's size flags, then the body as raw deflate. (Rebuilt
whole archives crash here: the game fails to decode the Oodle resource and reads it again.)
Usage: build_ps_icons.py [mod_dir]      Re-run after a game update.
"""
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rpf8  # noqa: E402
import ytd  # noqa: E402
from build_startup_data import open_inner, REPO  # noqa: E402

SRC_ARCHIVE = "update_4.rpf"
SETTINGS_MAP = {"controller_xboxone": "controller_ps4", "controller_xboxone_small": "controller_ps4_small",
                "controller_lines_xboxone": "controller_lines_ps4", "controller_generic": "controller_ps4",
                "controller_generic_small": "controller_ps4_small", "controller_lines_generic": "controller_lines_ps4"}


def icon_map(names):
    out = {}
    for n in names:
        m = re.fullmatch(r"ps4_button_(\d+)_img", n)
        if m and "button_%s_img" % m.group(1) in names:
            out["button_%s_img" % m.group(1)] = n
    return out


def copy_textures(data, mapping):
    y = ytd.Ytd(data)
    by = {t["name"]: t for t in y.textures}
    done = 0
    for dst, src in mapping.items():
        a, b = by[dst], by[src]
        if b["w"] == 4 and a["w"] > 4:         # button_48-57: combo icons, the PS slots are 4x4 red placeholders
            continue
        assert (a["w"], a["h"], a["fmt"], a["mips"]) == (b["w"], b["h"], b["fmt"], b["mips"]), (dst, src)
        so, size = y.pixels(b)
        do, dsize = y.pixels(a)
        assert size == dsize and do + size <= len(y.data) and so + size <= len(y.data), (dst, src)
        y.data[do:do + size] = y.data[so:so + size]
        done += 1
    assert len(y.data) == len(data), "size changed"
    return bytes(y.data), done


def loose_resource(rsc):
    flags = struct.unpack_from("<Q", rsc, 8)[0]
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return struct.pack("<IIQ", 0x38435352, 0x01000002, flags) + c.compress(rsc[16:]) + c.flush()


def build(inner, entry_name, mapping_of, out):
    _, _, sub = open_inner(SRC_ARCHIVE, inner)
    e = next(x for x in sub.entries if x.display_name().lower() == entry_name)
    rsc = sub.read_entry(e)
    mapping = mapping_of({t["name"] for t in ytd.Ytd(rsc).textures})
    new, n = copy_textures(rsc, mapping)
    built = loose_resource(new)
    assert zlib.decompress(built[16:], -15) == new[16:]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(built)
    print("%s: %d textures replaced, %d bytes; verified OK" % (out, n, len(built)))


def main(argv):
    out = argv[0] if argv else os.path.join(REPO, "mod", "lml", "DualSenseRDR2")
    rpf8.NAMES.load()
    build("x64/data/cdimages/scaleform_platform_pc.rpf", "gamepad_icons_pc.ytd", icon_map,
          os.path.join(out, "data", "gamepad_icons_pc.ytd"))
    build("x64/textures/ui/ui_platform.rpf", "pm_settings_controls.ytd", lambda _: SETTINGS_MAP,
          os.path.join(out, "data", "pm_settings_controls.ytd"))


if __name__ == "__main__":
    main(sys.argv[1:])
