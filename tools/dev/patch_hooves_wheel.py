"""Auto-align sanity bounds, gait-driven hooves from a trot up, game rumble muted in the weapon wheel."""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "mod" / "src"


def edit(name, pairs):
    p = SRC / name
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{name}: not found: {a[:90]}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


# 1. auto-align: a snap only counts near this gun's wall
edit("engine.cpp", [(
    """        if (best_v < 1500 || best_v < 3 * speeds[speeds.size() / 2]) continue;
        snaps_.push_back(snap_from);""",
    """        if (best_v < 1500 || best_v < 3 * speeds[speeds.size() / 2]) continue;
        // a real break can only happen where this gun's wall is: from one zone before the configured
        // break to three zones after it. Anything else is a fast pull or a tap, not a snap.
        int bz = int(jnum(p_.value("fire", json::object()), "break_zone", 6));
        if (snap_from < cal_.raw_at(std::max(1, bz - 1)) || snap_from > cal_.raw_at(std::min(10, bz + 3))) {
            LOGD("%s: ignored a jump at raw %d (not where the wall is)", id_.c_str(), snap_from);
            continue;
        }
        snaps_.push_back(snap_from);""")])

# 2. hooves: gait rhythm from a trot up (leg detection misses fast gaits), legs at a walk
edit("features.cpp", [(
    """    // fallback: no leg bones, or the legs went quiet at speed (detection misses fast gaits)
    bool legs_quiet = now - last_hoof_event_ > 0.45;
    if ((!g.hoof_bones || legs_quiet) && stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {""",
    """    // from a trot up the gait rhythm drives the hooves (leg detection misses fast gaits);
    // at a walk the real legs do, unless they were not found
    bool gait_driven = !g.hoof_bones || v >= 2.3f;
    if (gait_driven && stride_hz > 0 && horse_gain_ > 0 && dt > 0 && dt < 0.1) {"""),
    ("""        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0) {
            last_hoof_event_ = now;""",
     """        } else if (e.type == WorldEvent::Hoof && horse_gain_ > 0 && g.mount_speed < 2.3f) {
            last_hoof_event_ = now;"""),
])

# 3. the game's rumble: muted while the weapon wheel is open, lower default
edit("core.cpp", [
    ("""    audio_.set_rumble(input().rumble_low(), input().rumble_high());""",
     """    if (paused) audio_.set_rumble(0, 0);                 // the game rumbles while you browse the wheel
    else audio_.set_rumble(input().rumble_low(), input().rumble_high());"""),
    ("""    audio_.set_rumble_gain(c.num("Haptics", "GameRumble", 0.6f));""",
     """    audio_.set_rumble_gain(c.num("Haptics", "GameRumble", 0.35f));"""),
])
edit("config.cpp", [("GameRumble=0.6\n", "GameRumble=0.35\n")])
print("patched")
