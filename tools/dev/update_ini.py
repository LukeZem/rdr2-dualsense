"""Updates the installed DualSenseRDR2.ini in place: new defaults and new keys, everything else untouched."""
import re
import sys
from pathlib import Path

ini = Path(sys.argv[1])
lines = ini.read_text(encoding="utf-8-sig").splitlines()
set_values = {("Haptics", "GameAudio"): "0", ("Gyro", "Mode"): "off"}
add = {
    "General": [("TeachSurfaceKey", "121", "; F10: show the ground under you (identified automatically); F10 again while shown changes it")],
    "Haptics": [("Footsteps", "0.22", "; footsteps on foot, timed by the real feet, per surface"),
                ("Landing", "0.7", "; landing from a jump or drop"),
                ("Actions", "0.5", "; grabbing a ledge, opening a door, drawing / holstering a gun"),
                ("TableGames", "0.7", "; five finger fillet, poker / blackjack chips and cards, dominoes"),
                ("CampLife", "0.6", "; bites, sips, puffs, cleaning the gun, horse care, skinning, pelts, herbs, bathing, crafting, cooking"),
                ("Weather", "0", "; rain on the hat (0 = off)"),
                ("WheelClick", "0.6", "; the little click of L2/R2 while browsing the weapon wheel (0 = off)")],
    "Gyro": [("VerticalRatio", "0.75", "; vertical relative to horizontal"),
             ("SmoothThreshold", "6", "; movements slower than this (deg/s) are smoothed, faster pass straight through")],
    "Voice": [("CalmPhrase", "easy,easy boy,easy girl,steady", "; calm your horse (riding it or standing next to it)"),
              ("StopPhrase", "whoa", "; stop your horse"),
              ("SpeedPhrase", "giddy up,faster,yah,hyah", "; spur your horse on"),
              ("SpurTaps", "2", "; taps of Cross/A per command")],
}
section = None
present = set()
out = []
for line in lines:
    m = re.match(r"\s*\[(\w+)\]", line)
    if m:
        section = m.group(1)
    kv = re.match(r"\s*(\w+)\s*=", line)
    if kv and section:
        present.add((section, kv.group(1)))
        if (section, kv.group(1)) in set_values:
            line = f"{kv.group(1)}={set_values[(section, kv.group(1))]}"
    out.append(line)
result = []
section = None
for i, line in enumerate(out):
    m = re.match(r"\s*\[(\w+)\]", line)
    if m and section in add:
        # end of the previous section: append its missing keys before the blank line / header
        while result and not result[-1].strip():
            result.pop()
        for k, v, comment in add[section]:
            if (section, k) not in present:
                result += [comment, f"{k}={v}"]
        result.append("")
    if m:
        section = m.group(1)
    result.append(line)
if section in add:
    for k, v, comment in add[section]:
        if (section, k) not in present:
            result += [comment, f"{k}={v}"]
ini.write_text("\n".join(result) + "\n", encoding="utf-8")
print("updated", ini)
