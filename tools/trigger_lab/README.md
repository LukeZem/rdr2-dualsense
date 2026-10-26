# DualSense Trigger Lab

Feel and tune every RDR2 weapon **outside the game**, before the logic goes into the ASI mod.
Everything here is the reference the C++ mod is ported from: effect encoders, weapon engine,
the audio→haptics converter, `weapons.json`, `haptics.json`.

```
run_lab.bat                                   start (uses ..\..\.venv)
python lab.py --page range|sounds|lab|calibrate|haptics|log
python -m unittest discover -s tests -t .     offline tests (47)
python selftest.py                            headless check that the controller accepts every effect
```

**Before testing:** quit RDR2, DSX and DS4Windows, because they also write to the controller. Use **USB**:
true audio haptics need it. Bluetooth falls back to rumble emulation.

## Pages
| Page | What it's for |
|---|---|
| **Weapon Range** | All 63 weapons, grouped and searchable. Shoot with R2 and see the live pull curve (take-up / wall / break / overtravel), the state with instructions, ammo, and whether each shot landed **on the trigger snap**. Tune the curve, break, recoil and haptic strength live, then *Save to weapons.json*. |
| **Sounds** | The game's own sound banks. Play on speakers [Space] or as haptics [H], then label each sound with keys 1-9/0. Labels go to `data/sound_labels.json` and take effect immediately. |
| **Effect Lab** | Raw adaptive-trigger modes, a draggable zone editor, and the controller's feedback bytes. |
| **Calibrate** | Measures where the 10 zones sit on *your* controller (1 min per trigger). Do it first. |
| **Haptics** | Backend, master strength, every recipe, and what it's built from. |
| **Log** | Events. *Record CSV trace* saves raw 250 Hz data to `logs/`. |

Controller on the Range: ▲▼ weapon, ◄► category, □ reload, L3+R3 Dead Eye, OPTIONS manual cocking.

## Matching the game
- **Sounds:** each weapon's shot haptic is built from **its own recorded shots** in the game's sound
  bank. AWC banks are decoded directly from `lml/*/audio/sfx` (your RWS mod); the audio is plain PCM.
  Every recording becomes a variant, and one is picked per shot, as the game does. The trigger
  recoil of that shot follows the same recording.
- **Audio → haptics** (`gameaudio/convert.py`): the actuators work at about 20–400 Hz, but gunshots are mostly
  1–6 kHz. So the signal is rebuilt from the recording: its own low band (boom) + its transients
  carried at the actuator's sweet spot (snap, clicks) + its loudness on a low tone (push). Then the
  reverb tail is tightened, the signal soft-clipped and low-passed (no buzz).
- **Behaviour (RDR2):**
  - Single-action hammers, levers, bolts and pumps are cycled with an R2 tap between shots (unchecking
    *Manual cocking* models the "Automatic Cocking" mod).
  - Single-action revolvers can be fanned when hip-firing.
  - Pulling an empty gun reloads it.
  - Dead Eye slows the recoil, haptics and action, and adds a heartbeat.
- **Per mechanism:**
  - Semi-autos lock open when empty, so the trigger goes dead with no click; revolvers dry-click.
  - Double action has a stacking pull with a cylinder-index tick.
  - The Mauser has a gritty creep and a stripper-clip reload; the Schofield is a top-break with fast ejection.
  - Pumps are worked by the support hand (left actuator); the bow's shock hits the bow hand (left).
  - Dynamite: a lit fuse, then the game's own explosion after the fuse time.
  - Lasso/fishing: a live, struggling pull with jerks; melee: R1 swing + impact.
- **Weapon identity:** internal names → `joaat` hash. ✓ = name seen in the running game or in installed
  mods' tables. Unverified names fall back to the weapon group in the mod.

## Still to verify in the game
Bow controls (hold R2 to draw?), the exact fanning input, real fire rates and clip sizes (the mod
reads them at runtime), and the six "shared" slots in every weapon bank: label them on the Sounds page.
