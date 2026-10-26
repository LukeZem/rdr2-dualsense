"""Reader for RDR2 AWC (Audio Wave Container) files.

Layout (little endian, magic "ADAT"):
    0x00 magic, 0x04 u16 version, 0x06 u16 flags, 0x08 u32 stream count, 0x0C u32 header size
    [flags & 1] u16 chunk start index per stream
    u32 per stream: id (29-bit name hash) | chunk count << 29
    u64 per chunk:  type << 56 | size << 28 | offset
Chunk types seen in RDR2 PC weapon banks:
    0x76 format: u32 samples, i32 loop start (-1), u16 sample rate, ...
    0x55 data:   PCM16 mono (size == samples * 2)
    0x36 peak/envelope data, 0xBD markers
Stream ids are the low 29 bits of a Jenkins one-at-a-time hash of the sound name.
"""
from __future__ import annotations

import struct
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TAG_DATA, TAG_FORMAT = 0x55, 0x76


@dataclass
class Stream:
    id: int
    sample_rate: int
    pcm: np.ndarray            # int16 mono view into the file (decoded lazily)
    codec_ok: bool

    @property
    def samples(self) -> np.ndarray:
        """float32 mono, -1..1"""
        return self.pcm.astype(np.float32) / 32768.0

    @property
    def name(self) -> str:
        return f"0x{self.id:08X}"

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0


def joaat(text: str) -> int:
    h = 0
    for c in text.lower().encode():
        h = (h + c) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    return (h + (h << 15)) & 0xFFFFFFFF


def read(path: Path) -> list[Stream]:
    d = path.read_bytes()
    if d[:4] != b"ADAT":
        raise ValueError(f"{path.name}: not a little-endian AWC")
    _ver, flags, count, _hsize = struct.unpack_from("<HHII", d, 4)
    off = 16 + (2 * count if flags & 1 else 0)
    infos = [struct.unpack_from("<I", d, off + 4 * i)[0] for i in range(count)]
    off += 4 * count
    streams = []
    for info in infos:
        chunks = {}
        for _ in range(info >> 29):
            v = struct.unpack_from("<Q", d, off)[0]
            off += 8
            chunks[v >> 56] = ((v >> 28) & 0x0FFFFFFF, v & 0x0FFFFFFF)
        if TAG_FORMAT not in chunks or TAG_DATA not in chunks:
            continue
        fsize, foff = chunks[TAG_FORMAT]
        n_samples = struct.unpack_from("<I", d, foff)[0]
        rate = struct.unpack_from("<H", d, foff + 8)[0]
        dsize, doff = chunks[TAG_DATA]
        ok = dsize == n_samples * 2
        pcm = np.frombuffer(d, dtype="<i2", count=n_samples, offset=doff) if ok else np.zeros(0, "<i2")
        streams.append(Stream(info & 0x1FFFFFFF, rate, pcm, ok))
    return streams


def write_wav(path: Path, samples: np.ndarray, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
