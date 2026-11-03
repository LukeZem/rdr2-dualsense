#!/usr/bin/env python3
"""PlayStation button icons everywhere the game shows a controller.

The game already contains Rockstar's own PlayStation art (ps4_button_<n>_img, controller_ps4, ...) but on PC it
draws the Xbox textures. This copies the PlayStation pixels over the Xbox ones - same size, same format. The ten
combo icons button_48-57 have no PS art, so they come from art/combo_icons.png (ours: 5 x 2 icons on transparency).
The two texture dictionaries are written as loose files for LML's FileReplacement (install.xml):

  data/gamepad_icons_pc.ytd       update:/x64/data/cdimages/scaleform_platform_pc/gamepad_icons_pc.ytd  button prompts
  data/pm_settings_controls.ytd   update:/x64/textures/ui/ui_platform/pm_settings_controls.ytd          Settings picture

Loose resource format: RSC8, u32 0x01000002, u64 the resource's size flags, then the body as raw deflate. (Rebuilt
whole archives crash here: the game fails to decode the Oodle resource and reads it again.)
Usage: build_ps_icons.py [mod_dir]      Re-run after a game update.
"""
import io
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

from PIL import Image  # noqa: E402

SRC_ARCHIVE = "update_4.rpf"
COMBO_ART = os.path.join(HERE, "art", "combo_icons.png")
COMBO_FIRST = 48                              # button_48-52: face buttons, button_53-57: the same with L1
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


def spans(on, gap):
    """[(start, end)] of the runs of True, joining runs less than `gap` apart."""
    out = []
    for i, x in enumerate(on):
        if x:
            if out and i - out[-1][1] < gap:
                out[-1][1] = i + 1
            else:
                out.append([i, i + 1])
    return out


def combo_icons():
    """The ten icons of the art sheet as BC3 blocks for 64x64 slots."""
    sheet = Image.open(COMBO_ART).convert("RGBA")
    alpha = sheet.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    w, h = sheet.size
    px = alpha.load()
    rows = spans([any(px[x, y] for x in range(0, w, 2)) for y in range(h)], 12)
    assert len(rows) == 2, rows
    out = []
    for r0, r1 in rows:
        cols = spans([any(px[x, y] for y in range(r0, r1, 2)) for x in range(w)], 12)
        assert len(cols) == 5, cols
        for c0, c1 in cols:
            icon = sheet.crop((c0, r0, c1, r1)).convert("RGBa")          # premultiplied: clean edges when scaled
            icon.thumbnail((62, 62), Image.LANCZOS)
            cell = Image.new("RGBa", (64, 64))
            cell.paste(icon, ((64 - icon.width) // 2, (64 - icon.height) // 2))
            buf = io.BytesIO()
            cell.convert("RGBA").save(buf, "DDS", pixel_format="DXT5")
            d = buf.getvalue()
            assert d[84:88] == b"DXT5" and len(d) == 128 + 4096, (d[84:88], len(d))
            out.append(d[128:])
    return out


def put_combo_icons(data):
    y = ytd.Ytd(data)
    by = {t["name"]: t for t in y.textures}
    for i, blocks in enumerate(combo_icons()):
        t = by["button_%d_img" % (COMBO_FIRST + i)]
        off, size = y.pixels(t)
        assert (t["w"], t["h"], t["fmt"], size) == (64, 64, 77, len(blocks)), t
        y.data[off:off + size] = blocks
    assert len(y.data) == len(data)
    return bytes(y.data)


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


def build(inner, entry_name, mapping_of, out, finish=None):
    _, _, sub = open_inner(SRC_ARCHIVE, inner)
    e = next(x for x in sub.entries if x.display_name().lower() == entry_name)
    rsc = sub.read_entry(e)
    mapping = mapping_of({t["name"] for t in ytd.Ytd(rsc).textures})
    new, n = copy_textures(rsc, mapping)
    if finish:
        new = finish(new)
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
          os.path.join(out, "data", "gamepad_icons_pc.ytd"), put_combo_icons)
    build("x64/textures/ui/ui_platform.rpf", "pm_settings_controls.ytd", lambda _: SETTINGS_MAP,
          os.path.join(out, "data", "pm_settings_controls.ytd"))


if __name__ == "__main__":
    main(sys.argv[1:])
