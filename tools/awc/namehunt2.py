import itertools, sys
from collections import defaultdict
from pathlib import Path
import sys; sys.path.insert(0, "../trigger_lab"); from gameaudio import awc
ROOT = Path("C:/steam/steamapps/common/Red Dead Redemption 2/lml/RWS/audio/sfx")
ids = defaultdict(set)
for f in ROOT.rglob("*.awc"):
    for s in awc.read(f):
        ids[s.id].add(f.parent.name + "/" + f.stem)
cats = ("revolver pistol repeater rifle shotgun sniper sniperrifle bow lasso knife thrown throwing melee gun weapon weapons "
        "cattleman schofield lemat doubleaction volcanic mauser semiauto m1899 carbine lancaster litchfield evans varmint "
        "springfield boltaction bolt rollingblock carcano sawedoff pumpaction pump repeating doublebarrel double navy "
        "elephant tomahawk dynamite molotov machete hatchet cleaver lantern torch binoculars camera fishingrod gatling maxim "
        "cannon ammo shell shells casing generic player npc arrow improvedbow").split()
acts = ("draw holster unholster equip unequip cock cocking hammer hammercock hammerback hammerdown hammer_cock hammer_back "
        "uncock decock lever leveropen leverclose lever_open lever_close leverdown leverup lever_down lever_up "
        "bolt boltopen boltclose bolt_open bolt_close boltback boltforward bolt_back bolt_forward boltup boltdown bolt_up bolt_down "
        "pump pumpback pumpforward pump_back pump_forward rack "
        "reload reloadstart reloadend reload_start reload_end reloadloop load loadround insert insertshell insert_shell "
        "shellin shell_in shellout shell_out eject ejectshells eject_shells eject_shell casing casings cartridge cartridges "
        "dry dryfire dry_fire empty click trigger fire shot spin cylinder cylinderspin cylinder_spin cylinderopen cylinderclose "
        "cylinder_open cylinder_close gate gateopen gateclose gate_open gate_close open close breech breechopen breechclose "
        "breech_open breech_close slide slideback slideforward clip clipin clipout stripper strip magazine magin magout "
        "string stringpull string_pull drawback draw_back release nock aim aimin aimout fan fanning twirl spinning flip "
        "throw catch swing hit impact rattle handling handle movement move foley pickup drop putaway grab "
        "tap tapped flick check inspect clean cleaning oil polish load_in load_out").split()
nums = [""] + [str(i) for i in range(0, 21)] + [f"_{i}" for i in range(0, 21)] + [f"_{i:02d}" for i in range(0, 21)] + ["_a", "_b", "_c", "a", "b"]
hits = defaultdict(list)
for c, a in itertools.product(cats, acts):
    for sep in ("_", ""):
        base = f"{c}{sep}{a}"
        for n in nums:
            h = awc.joaat(base + n) & 0x1FFFFFFF
            if h in ids:
                hits[h].append(base + n)
# keep hits that belong to a series (same base appears >= 2 times) or exact obvious names
series = defaultdict(list)
for h, names in hits.items():
    for nm in names:
        base = nm.rstrip("0123456789").rstrip("_")
        series[base].append((nm, h))
for base, items in sorted(series.items()):
    if len(items) >= 2:
        banks = sorted({b for _, h in items for b in ids[h]})
        print(f"{base:<28} {len(items):3d}  {' '.join(sorted(n for n, _ in items))[:110]}  <- {', '.join(banks)[:60]}")
print(sum(len(v) for b, v in series.items() if len(v) >= 2), "ids in series;", len(hits), "raw hits", file=sys.stderr)
