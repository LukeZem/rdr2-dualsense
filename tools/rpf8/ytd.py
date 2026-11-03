#!/usr/bin/env python3
"""RDR2 texture dictionaries (.ytd, RSC8 version 2): read the list of textures and their pixel data.

Layout found in gamepad_icons_pc.ytd: RSC8 header (16 bytes), virtual segment, physical segment (sizes in the
header's flags). Virtual: dictionary {+0x20 name hashes*, +0x28 count, +0x30 textures*}. Texture record:
+0x08 u32 stored size / 16 (block formats), +0x0C u32 bytes per block, +0x18 u16 width, height, depth, u8 mips, u8 DXGI format,
+0x28 name*, +0x38 pixels* (physical segment).
"""
import struct

BC_BYTES = {71: 8, 72: 8, 77: 16, 78: 16, 98: 16, 99: 16}


class Ytd:
    def __init__(self, data):
        self.data = bytearray(data)
        magic, _ver, flags = struct.unpack_from("<IIQ", data, 0)
        assert magic == 0x38435352, "not RSC8"
        self.vsize = flags & 0xFFFFFFF0
        self.psize = (flags >> 32) & 0xFFFFFFF0
        assert 16 + self.vsize + self.psize == len(data), "sizes do not add up"
        self.hashes_p, self.count = struct.unpack_from("<QH", self.data, 16 + 0x20)
        ptrs_p = struct.unpack_from("<Q", self.data, 16 + 0x30)[0]
        self.textures = []
        for i in range(self.count):
            p = struct.unpack_from("<Q", self.data, 16 + (ptrs_p & 0xFFFFFFF) + 8 * i)[0]
            t = p & 0xFFFFFFF
            pitch, block = struct.unpack_from("<II", self.data, 16 + t + 8)
            w, h, _d, mips, fmt = struct.unpack_from("<HHHBB", self.data, 16 + t + 0x18)
            name_p = struct.unpack_from("<Q", self.data, 16 + t + 0x28)[0]
            pix_p = struct.unpack_from("<Q", self.data, 16 + t + 0x38)[0]
            n = 16 + (name_p & 0xFFFFFFF)
            name = bytes(self.data[n:self.data.index(0, n)]).decode("ascii", "replace")
            self.textures.append(dict(name=name, w=w, h=h, mips=mips, fmt=fmt, pitch=pitch, block=block,
                                      offset=16 + self.vsize + (pix_p & 0xFFFFFFF)))

    def pixels(self, t):
        """(offset, size) of the stored pixels (one mip level; every texture here has one). For block-compressed
        formats the +0x08 field is the stored size / 16; rows of big textures are padded, so size isn't w*h."""
        assert t["mips"] == 1
        return t["offset"], t["pitch"] * 16 if t["fmt"] in BC_BYTES else t["pitch"]
