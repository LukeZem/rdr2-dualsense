"""Hoof / foot touchdown detection, offline, on limb recordings from the game.

Record: DualSenseRDR2.ini [General] Debug=1, Record=1 -> the mod appends every frame's limb positions to
<game>\\DualSenseRDR2_limbs.csv (t, mode (horse / foot), speed, n, then per limb x, y, z, ground under it, plant = the
mod felt a touchdown on that frame).

    python limbs_touchdown.py DualSenseRDR2_limbs.csv [--from T]

prints, for hooves and feet: how far the mod's decisions (recorded) agree with an exact replay of World::steps here,
and how both score against the true touchdowns, per gait.

ground : the game's ground query glitches (a surface up to ~0.5 m too high for up to ~0.3 s). A limb is never below
         the ground and the ground doesn't jump up under it: such readings are dropped and the last good ground kept;
         an offset that lasts > 0.4 s is real (a hoof / foot sunk into snow).
truth  : (non-causal) every clear dip of a limb's height; the touchdown is the earliest frame before its low where the
         height is within 2 cm (or 10% of the dip) of the low.
replay : World::limb_height + World::touchdown (real time, per limb): it rose clearly above its last low -> it falls ->
         the fall stops near the bottom = touchdown; plus the self-healing restart and the double-hit gap.
"""
import argparse
import numpy as np
from scipy.signal import find_peaks

GAITS = {"horse": ((0.4, 2.3, "walk"), (2.3, 4.6, "trot"), (4.6, 8.0, "canter"), (8.0, 30, "gallop")),
         "foot": ((0.4, 2.2, "walk"), (2.2, 4.8, "run"), (4.8, 30, "sprint"))}
# World::steps: touchdown(rise_min, stop, margin, swing_max), double-hit gap
PARAMS = {"horse": ((0.04, 0.4, 0.65, 1.0), 0.15), "foot": ((0.07, 0.1, 0.5, 0.6), 0.2)}


def load(path, mode, t_from=None):
    rows = []
    for line in open(path):
        f = line.strip().split(",")
        if len(f) < 4 or f[1] != mode:
            continue
        try:
            n = int(f[3])
            rows.append((float(f[0]), float(f[2]), np.array(list(map(float, f[4:4 + 5 * n]))).reshape(n, 5)))
        except ValueError:                        # a line cut short when the game closed
            continue
    rows = [r for r in rows if t_from is None or r[0] >= t_from]
    n = max((r[2].shape[0] for r in rows), default=0)
    rows = [r for r in rows if r[2].shape[0] == n]
    rows.sort(key=lambda r: r[0])
    t = np.array([r[0] for r in rows])
    sp = np.array([r[1] for r in rows])
    A = np.array([r[2] for r in rows])            # frames x limbs x (x, y, z, ground, plant)
    return t, sp, A


def segments(t):
    cut = np.where(np.diff(t) > 0.1)[0]
    starts, ends = np.r_[0, cut + 1], np.r_[cut + 1, len(t)]
    return [(a, b) for a, b in zip(starts, ends) if b - a > 30]


def ground_hold(t, Z, G):
    out = np.empty_like(G)
    for a, b in segments(t):
        good = G[a].copy()
        held = np.zeros(G.shape[1])
        for k in range(a, b):
            for i in range(G.shape[1]):
                g = G[k, i]
                if g != 0 and (held[i] > 0.4 or (g <= Z[k, i] + 0.05 and g - good[i] < 0.25)):
                    good[i] = g
                    held[i] = 0
                elif k > a:
                    held[i] += t[k] - t[k - 1]
                out[k, i] = good[i]
    return out


def truth(t, H, sp):
    out = []                                      # (frame, limb)
    for a, b in segments(t):
        dtm = np.median(np.diff(t[a:b]))
        for i in range(H.shape[1]):
            h = H[a:b, i]
            pk, prop = find_peaks(-h, prominence=0.05, distance=max(1, int(0.15 / dtm)))
            for k, prom in zip(pk, prop["prominences"]):
                thr = h[k] + max(0.02, 0.1 * prom)
                j = k
                while j > 0 and h[j - 1] <= thr:
                    j -= 1
                if sp[a + j] > 0.4:
                    out.append((a + j, i))
    return out


class Limb:
    def __init__(self, now=0.0):
        self.good_gz = 0.0; self.held = 0.0; self.have_gz = False; self.have_h = False; self.td = 0
        self.hi = self.low = self.last_low = self.prev_h = 0.0; self.swing = 0.2
        self.last_td = now; self.reset_t = now; self.last_seen = -10.0


def touchdown(L, h, dt, rise_min, stop, margin, swing_max):
    if not L.have_h:
        L.have_h = True
        L.prev_h = L.hi = L.low = L.last_low = h
        return False
    v = (h - L.prev_h) / dt
    L.prev_h = h
    base = min(L.last_low, L.low)
    if L.td == 0:                                 # after a touchdown: wait for a clear rise
        L.low = min(L.low, h)
        L.last_low = min(L.last_low, h)
        L.hi = max(L.hi, h)
        if L.hi - min(L.last_low, L.low) > max(rise_min, 0.25 * L.swing):
            L.td = 1
        return False
    if L.td == 1:                                 # risen: wait for the fall
        L.hi = max(L.hi, h)
        if v < -stop:
            L.td = 2
        return False
    if v > -stop and h < base + margin * L.swing:  # falling: the fall stops near the bottom
        L.swing = min(max(0.7 * L.swing + 0.3 * (L.hi - h), 0.05), swing_max)
        L.last_low = L.low = L.hi = h
        L.td = 0
        return True
    return False


def replay(t, sp, A, mode):
    params, gap = PARAMS[mode]
    n = A.shape[1]
    limbs = [Limb() for _ in range(n)]
    fired = np.zeros((len(t), n), bool)
    for k in range(len(t)):
        now = t[k]
        dt = t[k] - t[k - 1] if k else 1 / 60
        if dt <= 0 or dt > 0.1:
            dt = 1 / 60
        for i in range(n):
            L = limbs[i]
            # self-healing: back after a gap, or silent for 2 s while moving
            if now - L.last_seen > 0.5 or (sp[k] > 1 and L.have_h and now - L.last_td > 2 and now - L.reset_t > 2):
                limbs[i] = L = Limb(now)
            L.last_seen = now
            z, gz = A[k, i, 2], A[k, i, 3]
            if gz != 0 and (L.held > 0.4 or (gz <= z + 0.05 and (not L.have_gz or gz - L.good_gz < 0.25))):
                if L.held > 0.4:
                    L.have_h = False                 # sunk in (snow): start over from the new level
                L.good_gz = gz; L.have_gz = True; L.held = 0
            else:
                L.held += dt
            if not L.have_gz or not touchdown(L, z - L.good_gz, dt, *params):
                continue
            double = now - L.last_td < gap
            L.last_td = now
            if not double and sp[k] > 0.4:
                fired[k, i] = True
    return fired


def score(name, fired, tru, t, sp, mode, tol=0.08):
    det = list(zip(*np.where(fired)))
    by = {}
    for k, i in tru:
        by.setdefault(i, []).append(k)
    used, lat = set(), []
    for k, i in det:
        cand = [j for j in by.get(i, []) if abs(t[j] - t[k]) <= tol and (j, i) not in used]
        if cand:
            j = min(cand, key=lambda j: abs(t[j] - t[k]))
            used.add((j, i))
            lat.append(t[k] - t[j])
    parts = []
    for lo, hi, g in GAITS[mode]:
        tg = [x for x in tru if lo <= sp[x[0]] < hi]
        dg = [d for d in det if lo <= sp[d[0]] < hi]
        if tg:
            cg = sum(1 for x in tg if x in used)
            parts.append(f"{g} {100 * cg / len(tg):.0f}%/+{max(0, len(dg) - cg)}")
    print(f"  {name:9s} caught {100 * len(used) / max(1, len(tru)):3.0f}% of {len(tru)}, off-time / extra "
          f"{len(det) - len(used):3d}" + (f", {1000 * np.median(lat):+.0f} ms after landing" if lat else "")
          + " | " + "  ".join(parts))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--from", dest="t_from", type=float, help="only frames from this t on (one session)")
    args = ap.parse_args()
    for mode in ("horse", "foot"):
        t, sp, A = load(args.csv, mode, args.t_from)
        if len(t) < 100:
            continue
        H = A[:, :, 2] - ground_hold(t, A[:, :, 2], A[:, :, 3])
        tru = truth(t, H, sp)
        rec = A[:, :, 4] > 0
        rep = replay(t, sp, A, mode)
        secs = sum(t[b - 1] - t[a] for a, b in segments(t))
        print(f"{mode}: {len(t)} frames, {secs:.0f} s, {A.shape[1]} limbs; recorded {int(rec.sum())}, replayed "
              f"{int(rep.sum())}, same frames {int((rec & rep).sum())}")
        score("recorded", rec, tru, t, sp, mode)
        score("replay", rep, tru, t, sp, mode)


if __name__ == "__main__":
    main()
