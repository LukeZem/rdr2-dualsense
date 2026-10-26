"""Acoustic features used to classify game sounds (shot body / tail / mechanism / low layer)."""
import numpy as np


def features(x: np.ndarray, sr: int) -> dict:
    if len(x) == 0:
        return {}
    a = np.abs(x)
    hop = max(1, sr // 1000)                            # 1 ms envelope
    n = len(a) // hop
    env = a[:n * hop].reshape(n, hop).max(axis=1) if n else a
    peak = float(env.max()) if len(env) else 0.0
    ipk = int(env.argmax())
    onset = int(np.argmax(env > peak * 0.1)) if peak > 0 else 0
    after = env[ipk:]
    below = np.nonzero(after < peak * 0.1)[0]
    decay_ms = int(below[0]) if len(below) else len(after)
    spec = np.abs(np.fft.rfft(x[: min(len(x), sr // 2)] * np.hanning(min(len(x), sr // 2))))
    f = np.fft.rfftfreq(min(len(x), sr // 2), 1 / sr)
    tot = spec.sum() + 1e-12
    return {
        "dur_ms": int(1000 * len(x) / sr),
        "peak": round(peak, 3),
        "rms": round(float(np.sqrt(np.mean(x ** 2))), 4),
        "onset_ms": onset,
        "attack_ms": ipk - onset,
        "decay_ms": decay_ms,
        "centroid": int((spec * f).sum() / tot),
        "low": round(float(spec[f < 200].sum() / tot), 2),   # share of energy below 200 Hz
    }
