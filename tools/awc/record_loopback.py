"""Record what the PC plays (WASAPI loopback of the default speaker) with wall-clock time stamps, to line up the
game's cutscene audio with the mod's log. Writes <out>.wav (mono, 48 kHz) and <out>.json (local time of sample 0).
Usage: record_loopback.py <out> <seconds>
"""
import json
import os
import sys
import time
from datetime import datetime

import numpy as np
import soundcard as sc
import soundfile as sf

RATE, BLOCK = 48000, 4800


def main(out, seconds):
    spk = sc.default_speaker()
    mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
    chunks, stamps = [], []
    with mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as rec:
        rec.record(numframes=BLOCK)                         # warm up
        n = 0
        while n < seconds * RATE and not os.path.exists(out + ".stop"):   # touch <out>.stop to end early
            x = rec.record(numframes=BLOCK)
            t = time.time()                                 # time the block's last sample arrived
            chunks.append(x.mean(axis=1).astype(np.float32))
            stamps.append((n + len(x), t))
            n += len(x)
    pcm = np.concatenate(chunks)
    # sample 0 time: fit over all blocks (arrival time - samples / rate), take the earliest = least delayed
    t0 = min(t - k / RATE for k, t in stamps)
    sf.write(out + ".wav", pcm, RATE, subtype="FLOAT")
    lt = datetime.fromtimestamp(t0)
    json.dump({"device": spk.name, "t0_epoch": t0, "t0_local": lt.strftime("%H:%M:%S.%f")[:-3], "rate": RATE,
               "seconds": len(pcm) / RATE}, open(out + ".json", "w"), indent=1)
    print("saved", out + ".wav", len(pcm) / RATE, "s, sample 0 at", lt.strftime("%H:%M:%S.%f")[:-3])


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]))
