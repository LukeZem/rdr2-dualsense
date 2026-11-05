"""Experiment: turning RDR2 cutscene audio into DualSense haptics.

Input: decoded CUTSCENE_MASTERED_ONLY stems (awc_vorbis.py). Channel 0 is the dialogue stem, the rest is music,
ambience and effects. Every method runs on the full mix (what the player hears, what the mod would capture),
and the dialogue stem is used as ground truth:
  voice share  - how much of the haptic output exists only because of the voices: rms(H(mix) - H(mix - dialogue)) / rms(H(mix))
  busy         - share of time the haptics are on (above 10 % of their own loud level): high = constant buzz
  voice busy   - share of time the haptics are on when fed the dialogue alone
  events/min   - distinct haptic hits per minute
Methods:
  A lowpass   - the mix low-passed at 120 Hz, played directly (what "audio to haptics" apps do)
  B rumble    - 20-200 Hz loudness envelope driving a 70 Hz tone (rumble-to-haptics style)
  C onsets    - only sudden hits: spectral-flux onsets over the whole spectrum -> short 80 Hz knocks
  D lowonsets - the same, onsets measured below 150 Hz only (voices have little energy there)
  E percussive- harmonic/percussive separation; the percussive part below 250 Hz, played directly
Usage: cutscene_haptics_lab.py <scene.wav> [...]   -> prints a table, writes <scene>_<method>.wav (haptic channel)
"""
import sys

import numpy as np
import soundfile as sf
from scipy.ndimage import median_filter
from scipy.signal import butter, istft, sosfilt, stft

SR = 48000


def lp(x, hz, order=4):
    return sosfilt(butter(order, hz, "lowpass", fs=SR, output="sos"), x)


def bp(x, lo, hi, order=4):
    return sosfilt(butter(order, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def env(x, ms=10):
    h = int(SR * ms / 1000)
    n = len(x) // h
    return np.sqrt(np.mean(x[:n * h].reshape(n, h) ** 2, axis=1) + 1e-12)


def knocks(times, strengths, n):
    """short decaying 80 Hz bursts at the onset times"""
    out = np.zeros(n, np.float32)
    L = int(0.03 * SR)
    t = np.arange(L) / SR
    k = np.sin(2 * np.pi * 80 * t) * np.exp(-t / 0.008)
    for tm, s in zip(times, strengths):
        i = int(tm * SR)
        if i < n:
            out[i:i + L] += (s * k)[:max(0, min(L, n - i))]
    return out


def onsets(x, band_hz=None):
    f, t, Z = stft(x, SR, nperseg=1024, noverlap=768)
    M = np.abs(Z)
    if band_hz:
        M = M[f < band_hz]
    M = np.log1p(100 * M)
    flux = np.maximum(0, np.diff(M, axis=1)).sum(axis=0)
    flux = np.concatenate([[0], flux])
    thr = median_filter(flux, size=101) * 2.5 + 1e-3 + np.percentile(flux, 50)
    peaks = [i for i in range(1, len(flux) - 1)
             if flux[i] > thr[i] and flux[i] >= flux[i - 1] and flux[i] >= flux[i + 1]]
    # at most one knock per 80 ms
    keep, last = [], -1e9
    for i in peaks:
        if t[i] - last >= 0.08:
            keep.append(i)
            last = t[i]
    s = flux[keep] / (np.percentile(flux[keep], 95) + 1e-9) if keep else []
    return t[keep], np.clip(s, 0, 1.5)


def percussive(x):
    f, t, Z = stft(x, SR, nperseg=2048, noverlap=1536)
    M = np.abs(Z)
    H = median_filter(M, size=(1, 17))
    P = median_filter(M, size=(17, 1))
    mask = P ** 2 / (P ** 2 + H ** 2 + 1e-12)
    _, y = istft(Z * mask, SR, nperseg=2048, noverlap=1536)
    return lp(y[:len(x)], 250)


def method(name, x):
    n = len(x)
    if name == "A_lowpass":
        return lp(x, 120)
    if name == "B_rumble":
        e = env(bp(x, 20, 200), 30)
        e = np.repeat(e, int(SR * 0.03))[:n]
        e = np.pad(e, (0, n - len(e)))
        return e * np.sin(2 * np.pi * 70 * np.arange(n) / SR)
    if name == "C_onsets":
        return knocks(*onsets(x), n)
    if name == "D_lowonsets":
        return knocks(*onsets(x, 150), n)
    if name == "E_percussive":
        return percussive(x)
    raise ValueError(name)


METHODS = ["A_lowpass", "B_rumble", "C_onsets", "D_lowonsets", "E_percussive"]


def rms(x):
    return float(np.sqrt(np.mean(np.square(x)) + 1e-20))


def busy(h, ref):
    e = env(h, 10)
    return float(np.mean(e > 0.1 * ref))


def events(h, ref):
    e = env(h, 10) > 0.25 * ref
    return int(np.sum(e[1:] & ~e[:-1]))


def run(path):
    x, sr = sf.read(path, dtype="float32")
    assert sr == SR
    if x.ndim == 1:
        x = x[:, None]
    mix = x.sum(axis=1)
    dlg = x[:, 0]
    rest = mix - dlg
    minutes = len(mix) / SR / 60
    print(f"\n== {path}: {len(mix) / SR:.0f} s, dialogue {20 * np.log10(rms(dlg) / rms(mix)):+.1f} dB of the mix")
    print(f"   {'method':14} {'voice share':>11} {'busy':>6} {'voice busy':>10} {'events/min':>10}")
    for m in METHODS:
        hm, hr, hd = method(m, mix), method(m, rest), method(m, dlg)
        ref = np.percentile(env(hm, 10), 99) + 1e-9
        share = rms(hm - hr) / rms(hm)
        print(f"   {m:14} {share:11.2f} {busy(hm, ref):6.2f} {busy(hd, ref):10.2f} {events(hm, ref) / minutes:10.1f}")
        out = hm / (np.max(np.abs(hm)) + 1e-9) * 0.9
        sf.write(path.replace(".wav", f"_{m}.wav"), out.astype(np.float32), SR)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        run(p)
