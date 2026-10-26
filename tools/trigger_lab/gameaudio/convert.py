"""Game audio -> DualSense haptic signal.

The actuators are voice coils that reproduce roughly 20-400 Hz with real force; above
that they mostly make noise. A raw gunshot recording is mostly 1-6 kHz energy, so
playing it straight feels thin and buzzy. Instead the signal is rebuilt from three
parts, all driven by the recording itself so timing and character match what you hear:

  body    the recording's own low band (lo..hi Hz): the boom, kept as-is
  crack   the recording's transients (fast envelope minus slow envelope) carried on a
          tone near the actuator's sweet spot: the sharp snap of the shot, clicks of
          the mechanism - this is what makes it feel 'mechanical'
  rumble  the overall loudness envelope on a low tone: the weight / push

Then the reverb tail is tightened (a hand doesn't feel room echo for 2 s), the result
is soft-clipped for punch and normalised.
"""
from __future__ import annotations

import numpy as np

SR = 48000

PRESETS: dict[str, dict] = {
    # handguns: snappy, short
    "handgun": dict(lo=35, hi=240, body=0.75, crack=0.85, crack_hz=170, rumble=0.45, rumble_hz=62,
                    hold_ms=25, tail_ms=70, max_ms=420, drive=2.2),
    # rifles / repeaters: longer push
    "long": dict(lo=30, hi=220, body=0.85, crack=0.7, crack_hz=150, rumble=0.6, rumble_hz=50,
                 hold_ms=35, tail_ms=110, max_ms=550, drive=2.0),
    # big bores and shotguns: deep, long, heavy
    "heavy": dict(lo=25, hi=200, body=1.0, crack=0.6, crack_hz=140, rumble=0.75, rumble_hz=42,
                  hold_ms=45, tail_ms=150, max_ms=650, drive=2.4),
    # .22 and other tiny cartridges
    "small": dict(lo=60, hi=300, body=0.5, crack=0.9, crack_hz=200, rumble=0.2, rumble_hz=80,
                  hold_ms=10, tail_ms=40, max_ms=220, drive=1.6),
    # mechanical foley: clicks matter, no weight
    "mech": dict(lo=60, hi=320, body=0.35, crack=1.0, crack_hz=210, rumble=0.1, rumble_hz=90,
                 hold_ms=30, tail_ms=60, max_ms=400, drive=1.5),
    # explosions: long rolling rumble
    "explosion": dict(lo=20, hi=180, body=1.0, crack=0.45, crack_hz=120, rumble=0.9, rumble_hz=36,
                      hold_ms=120, tail_ms=450, max_ms=1600, drive=2.6),
}


def resample(x: np.ndarray, sr: int, target: int = SR) -> np.ndarray:
    if sr == target or len(x) == 0:
        return x.astype(np.float32)
    n = int(len(x) * target / sr)
    return np.interp(np.arange(n) * (sr / target), np.arange(len(x)), x).astype(np.float32)


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    # soft (raised-cosine, one octave) edges avoid ringing
    g = np.ones_like(f)
    g[f < lo / 2] = 0
    m = (f >= lo / 2) & (f < lo)
    g[m] = 0.5 - 0.5 * np.cos(np.pi * (f[m] - lo / 2) / (lo / 2))
    g[f > hi * 2] = 0
    m = (f > hi) & (f <= hi * 2)
    g[m] = 0.5 + 0.5 * np.cos(np.pi * (f[m] - hi) / hi)
    return np.fft.irfft(spec * g, len(x)).astype(np.float32)


def _follow(x: np.ndarray, release_ms: float, attack_ms: float = 0.0) -> np.ndarray:
    """Peak envelope on 1 ms blocks, instant/one-pole attack, exponential release."""
    hop = SR // 1000
    n = len(x) // hop + 1
    pad = np.zeros(n * hop, np.float32)
    pad[:len(x)] = np.abs(x)
    blocks = pad.reshape(n, hop).max(axis=1)
    rel = np.exp(-1.0 / max(release_ms, 0.1))
    att = np.exp(-1.0 / attack_ms) if attack_ms > 0 else 0.0
    env = np.empty(n, np.float32)
    e = 0.0
    for i, v in enumerate(blocks):
        e = (att * e + (1 - att) * v) if v > e else max(v, e * rel)
        env[i] = e
    env = np.convolve(env, np.ones(3) / 3, mode="same")               # no 1 kHz block steps
    return np.interp(np.arange(len(x)) / hop, np.arange(n), env).astype(np.float32)


def to_haptic(audio: np.ndarray, sr: int, preset: str | dict = "handgun", pan: float = 0.0,
              amp: float = 1.0) -> np.ndarray:
    """audio: (n,) or (n, 2) float. Returns float32 (m, 2) at 48 kHz for the actuators."""
    p = PRESETS[preset] if isinstance(preset, str) else preset
    x = audio.mean(axis=1) if audio.ndim == 2 else audio
    x = resample(x, sr)
    peak = float(np.abs(x).max()) if len(x) else 0.0
    if peak < 1e-5:
        return np.zeros((1, 2), np.float32)
    x = x / peak
    start = max(0, int(np.argmax(np.abs(x) > 0.03)) - SR // 500)       # trim silence, keep 2 ms
    x = x[start:start + int(SR * p["max_ms"] / 1000)]
    t = np.arange(len(x)) / SR

    body = _band(x, p["lo"], p["hi"])
    body /= max(1e-6, float(np.abs(body).max()))
    fast = _follow(x, 25)
    slow = _follow(x, 90, attack_ms=8)
    trans = np.clip(fast - slow, 0, None)
    trans /= max(1e-6, float(trans.max()))
    loud = fast / max(1e-6, float(fast.max()))
    crack = np.sin(2 * np.pi * p["crack_hz"] * t) * trans
    rumble = np.sin(2 * np.pi * p["rumble_hz"] * t) * loud
    h = p["body"] * body + p["crack"] * crack + p["rumble"] * rumble

    hold = p["hold_ms"] / 1000
    shape = np.where(t < hold, 1.0, np.exp(-(t - hold) / (p["tail_ms"] / 1000)))
    h *= shape
    cut = np.nonzero(shape > 0.01)[0]
    h = h[: cut[-1] + 1 if len(cut) else len(h)]
    h /= max(1e-6, float(np.abs(h).max()))
    d = p["drive"]
    h = np.tanh(d * h) / np.tanh(d)
    h = _band(h, 15, 300)                     # drop clipping harmonics: actuators buzz above ~500 Hz
    h = h / max(1e-6, float(np.abs(h).max())) * amp
    fade = min(len(h), SR // 200)                                       # 5 ms fade-out, no click
    h[-fade:] *= np.linspace(1, 0, fade)
    gl, gr = min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)
    return np.stack([h * gl, h * gr], axis=1).astype(np.float32)


def kick_steps(audio: np.ndarray, sr: int, step_ms: float, max_steps: int = 8, floor: float = 0.12,
               peak: int = 8, expand: float = 3.0) -> list[int]:
    """Trigger recoil envelope (amplitudes 1-`peak` per step) following the shot's loudness.
    Taken from the source recording and forced to only decay - echoes in the recording
    must not make the trigger kick twice. Game gunshots are mastered loud and stay near
    full scale for 100+ ms, so the envelope is expanded (cubed): the kick is sharp and
    its decay still has the recording's character."""
    x = audio.mean(axis=1) if audio.ndim == 2 else audio
    x = resample(x, sr)
    if not len(x) or float(np.abs(x).max()) < 1e-5:
        return []
    x = x[max(0, int(np.argmax(np.abs(x) > 0.03 * np.abs(x).max()))):]
    env = _follow(x, 30)
    env = env[int(np.argmax(env)):]                  # the kick starts at the loudest moment
    hop = max(1, int(SR * step_ms / 1000))
    n = min(max_steps, len(env) // hop)
    env = env[: n * hop].reshape(n, hop).max(axis=1)
    env = np.minimum.accumulate(env / max(1e-6, float(env.max()))) ** expand
    steps = []
    for e in env:
        if e < floor:
            break
        steps.append(max(1, min(8, int(round(peak * e)))))
    return steps
