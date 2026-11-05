"""Decode RDR2 streamed AWC audio (codec 8 = Vorbis), e.g. CUTSCENE_MASTERED_ONLY/*.awc, to WAV.

Layout (found by inspection, RDR2 PC):
  stream 0 (id 0): chunk 0x48 stream format: u32 blocks, u32 block size (0x80000), u32 channels,
                   then per channel 16 bytes: u32 id, u32 samples, i16 headroom, u16 rate, u8 codec (8), ...
                   chunk 0x55: the blocks
  stream <channel id>: chunk 0x7f: three Vorbis headers (identification, comment, setup), each u32 size + data
  block: per channel 0x18 bytes (u32 -1, u32 frames, u32 0, u32 samples in block, 0, 0),
         per channel u32 x frames: start sample of each frame (seek table),
         aligned to 0x800: per channel `frames` x 0x800 bytes; a frame holds u16-size-prefixed Vorbis packets.
The packets are rewrapped as an Ogg Vorbis stream (one page per frame, granule from the seek table) and decoded
with libsndfile.
Usage: awc_vorbis.py <file.awc> <out.wav>   (all channels, float32)
"""
import io
import struct
import sys

import numpy as np
import soundfile as sf


def _crc_table():
    t = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else (r << 1)
        t.append(r & 0xFFFFFFFF)
    return t


_CRC = _crc_table()


def _crc(b):
    c = 0
    for x in b:
        c = ((c << 8) & 0xFFFFFFFF) ^ _CRC[((c >> 24) ^ x) & 0xFF]
    return c


def _page(packets, granule, serial, seq, flags):
    lace = bytearray()
    for p in packets:
        n = len(p)
        lace += bytes([255] * (n // 255)) + bytes([n % 255])
    assert len(lace) <= 255
    head = b"OggS" + struct.pack("<BBqIIIB", 0, flags, granule, serial, seq, 0, len(lace)) + bytes(lace)
    body = b"".join(packets)
    page = bytearray(head + body)
    struct.pack_into("<I", page, 22, _crc(page))
    return bytes(page)


def _chunks(d):
    _ver, flags, count, _ = struct.unpack_from("<HHII", d, 4)
    off = 16 + (2 * count if flags & 1 else 0)
    infos = [struct.unpack_from("<I", d, off + 4 * i)[0] for i in range(count)]
    off += 4 * count
    streams = {}
    for info in infos:
        ch = {}
        for _ in range(info >> 29):
            v = struct.unpack_from("<Q", d, off)[0]
            off += 8
            ch[v >> 56] = (v & 0x0FFFFFFF, (v >> 28) & 0x0FFFFFFF)     # offset, size
        streams[info & 0x1FFFFFFF] = ch
    return streams


def decode(path):
    d = open(path, "rb").read()
    assert d[:4] == b"ADAT"
    st = _chunks(d)
    fo, _ = st[0][0x48]
    blocks, bsize, nch = struct.unpack_from("<III", d, fo)
    chans = []
    for c in range(nch):
        cid, samples, _hr, rate, codec, _r, _u = struct.unpack_from("<IIhHBBH", d, fo + 12 + 16 * c)
        assert codec == 8, codec
        chans.append((cid, samples, rate))
    do, dsize = st[0][0x55]
    heads = []
    for cid, _, _ in chans:
        vo, _ = st[cid][0x7F]
        hs, i = [], vo
        for _ in range(3):
            n = struct.unpack_from("<I", d, i)[0]
            hs.append(d[i + 4:i + 4 + n])
            i += 4 + n
        heads.append(hs)
    # Each block restarts every channel's stream with pre-roll packets that repeat the end of the previous block.
    # Block header per channel: (u32 -1, u32 frames, u32 samples to skip at the block start, u32 samples in the
    # block including the skipped ones, 0, 0). Decode each channel as one continuous Ogg stream (granules counting
    # the skipped samples too), then cut every block's first `skip` samples out - without this, multi-block files
    # drift (~190 ms per block with 6 stems).
    frames = [[] for _ in range(nch)]
    spans = [[] for _ in range(nch)]                      # (start in the decoded output, skip, samples) per block
    base = [0] * nch
    for b in range(blocks):
        bo = do + b * bsize
        if bo >= do + dsize:
            break
        hdr = [struct.unpack_from("<6I", d, bo + 0x18 * c) for c in range(nch)]
        ent = [h[1] for h in hdr]
        tables, p = [], bo + 0x18 * nch                    # seek tables: start sample of each frame in the block
        for c in range(nch):
            tables.append(struct.unpack_from("<%dI" % ent[c], d, p))
            p += 4 * ent[c]
        p = bo + ((p - bo + 0x7FF) & ~0x7FF)
        for c in range(nch):
            for k in range(ent[c]):
                f = d[p + k * 0x800: p + (k + 1) * 0x800]
                pk, i = [], 0
                while i + 2 <= 0x800:
                    s = struct.unpack_from("<H", f, i)[0]
                    if s == 0 or i + 2 + s > 0x800:
                        break
                    pk.append(f[i + 2:i + 2 + s])
                    i += 2 + s
                end = tables[c][k + 1] if k + 1 < ent[c] else hdr[c][3]
                frames[c].append((pk, base[c] + end))
            p += ent[c] * 0x800
            spans[c].append((base[c], hdr[c][2], hdr[c][3]))
            base[c] += hdr[c][3]
    out = []
    for c, (cid, samples, rate) in enumerate(chans):
        ogg = io.BytesIO()
        serial = 0x5EED + c
        ogg.write(_page([heads[c][0]], 0, serial, 0, 2))
        ogg.write(_page(heads[c][1:], 0, serial, 1, 0))
        seq = 2
        nf = len(frames[c])
        for k, (pk, g) in enumerate(frames[c]):
            if not pk:
                continue
            ogg.write(_page(pk, g, serial, seq, 4 if k == nf - 1 else 0))
            seq += 1
        ogg.seek(0)
        x, sr = sf.read(ogg, dtype="float32")
        out.append(np.concatenate([x[s0 + skip:s0 + n] for s0, skip, n in spans[c]])[:samples])
    n = min(len(x) for x in out)
    return np.stack([x[:n] for x in out], axis=1), chans[0][2]


if __name__ == "__main__":
    pcm, rate = decode(sys.argv[1])
    sf.write(sys.argv[2], pcm, rate, subtype="FLOAT")
    print("%s: %d ch, %.1f s, %d Hz, peak per channel %s" % (sys.argv[2], pcm.shape[1], len(pcm) / rate, rate,
                                                                np.round(np.abs(pcm).max(axis=0), 3).tolist()))
