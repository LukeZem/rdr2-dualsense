"""Survey the WEAPONS bank for short mechanical sounds (clicks, cocks, lever/bolt actions, shell inserts).
Prints per-sound features and writes a CSV for clustering."""
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "trigger_lab"))
from gameaudio import awc  # noqa: E402

BANK = Path("C:/steam/steamapps/common/Red Dead Redemption 2/lml/RWS/audio/sfx/RDR3.Resident/WEAPONS.awc")


def features(x: np.ndarray, sr: int) -> dict:
    env = np.abs(x)
    pk = float(env.max()) if len(env) else 0.0
    if pk <= 1e-4:
        return {}
    above = np.where(env > pk * 0.05)[0]
    active = (above[-1] - above[0]) / sr
    # onsets: 2 ms RMS frames, a jump of 4x over the previous 10 ms
    hop = max(1, sr // 500)
    n = len(x) // hop
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    onsets = []
    for i in range(5, n):
        if rms[i] > 0.08 * pk and rms[i] > 4 * rms[i - 5:i].mean():
            if not onsets or i - onsets[-1] > 15:     # 30 ms apart
                onsets.append(i)
    spec = np.abs(np.fft.rfft(x[: min(len(x), sr)] * np.hanning(min(len(x), sr))))
    f = np.fft.rfftfreq(min(len(x), sr), 1 / sr)
    centroid = float((spec * f).sum() / (spec.sum() + 1e-9))
    low = float(spec[f < 300].sum() / (spec.sum() + 1e-9))
    # decay: time from peak to -30 dB
    ip = int(env.argmax())
    tail = np.where(env[ip:] > pk * 0.03)[0]
    decay = (tail[-1] if len(tail) else 0) / sr
    return {"dur": len(x) / sr, "active": active, "peak": pk, "onsets": len(onsets),
            "onset_gaps": ",".join(f"{(b - a) * hop / sr * 1000:.0f}" for a, b in zip(onsets, onsets[1:])),
            "centroid": centroid, "low": low, "decay": decay}


def main():
    streams = awc.read(BANK)
    rows = []
    for s in streams:
        x = s.samples
        if len(x) == 0:
            continue
        ft = features(x, s.sample_rate)
        if ft:
            rows.append({"id": s.name, "sr": s.sample_rate, **ft})
    out = Path(__file__).with_name("weapons_survey.csv")
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    durs = np.array([r["dur"] for r in rows])
    print(len(rows), "sounds;", "duration histogram:")
    for lo, hi in [(0, 0.15), (0.15, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 2.0), (2.0, 99)]:
        print(f"  {lo:.2f}-{hi:.2f}s: {int(((durs >= lo) & (durs < hi)).sum())}")
    short = [r for r in rows if r["active"] < 0.6 and r["decay"] < 0.4]
    print(len(short), "short, dry sounds (mechanical candidates); by onset count:")
    for k in range(1, 6):
        print(f"  {k} onset(s): {sum(1 for r in short if r['onsets'] == k)}")


if __name__ == "__main__":
    main()
