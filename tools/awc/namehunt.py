"""Recover AWC stream names by hashing candidate names (ids are joaat(name) & 0x1FFFFFFF)."""
import itertools, sys
from pathlib import Path
import sys; sys.path.insert(0, "../trigger_lab"); from gameaudio import awc

ROOT = Path("C:/steam/steamapps/common/Red Dead Redemption 2/lml/RWS/audio/sfx")
ids = {}
for f in ROOT.rglob("*.awc"):
    for s in awc.read(f):
        ids.setdefault(s.id, set()).add(f.parent.name + "/" + f.stem)

weapons = ("cattleman schofield lemat double doubleaction double_action volcanic mauser semiauto semi_auto m1899 carbine "
           "lancaster litchfield evans winchester henry varmint springfield boltaction bolt_action rollingblock rolling_block "
           "carcano sawedoff sawed_off pump pumpaction pump_action repeating navy elephant revolver pistol repeater rifle "
           "shotgun sniper bow lasso knife rev ptl rpt rfl sht snp gun weapon generic").split()
actions = ("cock cocking hammer hammer_cock hammer_back hammer_down hammer_release lever lever_open lever_close lever_down lever_up "
           "bolt bolt_open bolt_close bolt_back bolt_forward bolt_up bolt_down pump pump_back pump_forward pump_open pump_close "
           "reload reload_start reload_end reload_in reload_out load insert shell shell_in shell_insert shell_eject eject casing "
           "casings cartridge dry dry_fire dryfire empty click spin cylinder cylinder_spin cylinder_open cylinder_close "
           "cylinder_rotate gate gate_open gate_close holster unholster draw equip unequip twirl mech mechanics mechanical "
           "handling rattle trigger fire shot shots tail tails close far distant interior exterior body sub low mid high "
           "breech breech_open breech_close slide slide_back slide_forward clip stripper magazine mag mag_in mag_out "
           "string string_pull draw_back release arrow nock fan fanning whip throw catch").split()
nums = [""] + [f"_{i}" for i in range(1, 9)] + [f"_{i:02d}" for i in range(1, 13)] + [str(i) for i in range(1, 9)] + ["_a", "_b", "_c", "_l", "_r", "_left", "_right"]
seps = ["_", ""]
cands = set()
for a in actions:
    for n in nums:
        cands.add(a + n)
for w, a in itertools.product(weapons, actions):
    for sep in seps:
        for n in nums:
            cands.add(f"{w}{sep}{a}{n}")
            cands.add(f"{a}{sep}{w}{n}")
            cands.add(f"weapons_{w}{sep}{a}{n}")
print(len(cands), "candidates", file=sys.stderr)
hits = {}
for c in cands:
    h = awc.joaat(c) & 0x1FFFFFFF
    if h in ids:
        hits.setdefault(h, []).append(c)
for h, names in sorted(hits.items(), key=lambda kv: sorted(kv[1])[0]):
    print(f"0x{h:08X} {', '.join(sorted(names))}  <- {', '.join(sorted(ids[h]))[:80]}")
print(len(hits), "ids named of", len(ids), file=sys.stderr)
