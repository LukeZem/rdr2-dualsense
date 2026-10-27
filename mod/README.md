# DualSense for RDR2 (`DualSenseRDR2.asi`)

Full DualSense support for Red Dead Redemption 2 (story mode): adaptive triggers per weapon, true
voice-coil haptics built from the game's own sounds, lightbar/LEDs, controller speaker, gyro aim,
whistle-to-call-your-horse, touchpad gestures.

## Requirements
- Script Hook RDR2 + its ASI loader (`ScriptHookRDR2.dll`, `dinput8.dll`) in the game folder
- DualSense on **USB** (Bluetooth works but falls back to rumble emulation - no voice-coil haptics, no speaker/mic)
- **Quit DSX / DS4Windows** and turn **Steam Input off** for RDR2 (Steam → RDR2 → Properties → Controller → Disable
  Steam Input). The mod talks to the controller directly and becomes the game's only gamepad.

## Build / install
```
cmake -S . -B build -G Ninja -DCMAKE_CXX_COMPILER=g++   (CLion's bundled MinGW, CMake, Ninja)
cmake --build build
build\dsr2_test.exe --selftest                          offline checks (35)
build\dsr2_test.exe WEAPON_REVOLVER_CATTLEMAN 30        the whole mod without the game, real controller
powershell -ExecutionPolicy Bypass -File install.ps1    copies .asi + data (from tools/trigger_lab/data)
powershell -ExecutionPolicy Bypass -File uninstall.ps1  removes it and restores the mods install moved away
```
Tune weapons, record calibration and label sounds in the Trigger Lab (`tools/trigger_lab`), then run
`install.ps1` again - it copies the lab's data into `<game>\DualSenseRDR2\`.

## In game
| Feature | How it works |
|---|---|
| Triggers | Per-weapon pull curves from `weapons.json`. The game only sees R2 = 0 before the break and 255 after it, so the shot always lands on the snap. Auto-align learns where your trigger really breaks. Re-arming and cocking follow the game's own "ready to shoot" (no guessed fire rate). Recoil: a shove against the finger, then a fading rumble. |
| Game data | Ammo, reloads, Dead Eye, ammo type (express/explosive kick harder), gun dirt and wear (gritty creep), exhaustion / cold / drunk (shaky pull), lasso target struggle, melee hits from real damage. |
| Dead Eye | Every target you paint ticks on R2 and in the haptics (the game's mark count); each shot of the volley kicks when the game really fires it. |
| Fishing | Read from the game's fishing task: R2 loads the cast and tugs when a fish takes the bait (strike!), L2 (the rod grip) carries the real line tension and strains before the line snaps, the fish's surges come from its side, reel clicks, the catch flapping in your hand. |
| Honor | The story scripts' honor stats: a warm rising swell + gold glow when honor goes up (e.g. after a greeting), a sinking thud + ember glow when it drops. |
| Camp life | Bites, sips and puffs (the game's own effect moment), cleaning a gun, each brush stroke / mouthful when caring for the horse, skinning, stowing pelts on the horse, picking herbs, bathing, crafting, cooking. |
| Table games | Five finger fillet (every stab, the miss), poker / blackjack (chips, knocks, cards, shuffles from Arthur's hand animations), dominoes. |
| Haptics | Shots from each gun's own recordings (lml sound mods such as RWS); the game's rumble converted for the voice coils; **game-audio layer**: what you hear (hooves, explosions, cutscenes, mini-games) as haptics, keeping left/right, quieter while a weapon effect plays. |
| Around you | Damage felt from its direction and by cause (bullet, melee, animal, fall); nearby gunfire pressure waves from their direction; heartbeat at low health and in Dead Eye; shivers in freezing cold. |
| Horse | Hoofbeats from the real hooves touching the ground (height above the ground, any gait) on the ground under each hoof; the gait rhythm only if the legs can't be read; the horse's heartbeat and breathing when it is spent; rearing. |
| Ground | The game's ground material, identified by name (mud_soft, gravel_dirt, pine_needles, wood_solid_medium...) - footsteps and hooves feel like it. |
| Trains / wagons | Rail joints (front and rear bogie), ruts. |
| Lightbar | Muzzle flash, damage flash, Dead Eye sepia glow, lantern flicker, wanted (red/white), low-health pulse, time-of-day ambience. Player LEDs show the rounds left. |
| Speaker | The game's own recordings for drawing / holstering a revolver, the lasso throw and the rope (found by name in the sound banks); synthesized cocking / lever / bolt / pump clicks. |
| Gyro aim | Experimental, off by default: small gyro corrections while free-aiming (`[Gyro] Mode=aim`). |
| Microphone | Whistle into the controller → horse call. Say "chao" → a real greeting (counts for honor). "Easy" → calm the horse. A command only counts when said on its own (after a pause, short, confident). The mute button toggles listening (mute LED on = not listening). |
| Weather | Rain on the hat, as heavy as the game's rain - off by default (`[Haptics] Weather`). |
| Touchpad | Click = map (BACK). Swipes / two-finger tap can be mapped to buttons in the ini. |

Settings: `DualSenseRDR2.ini` (F9 reloads it and the data folder in game). Log: `DualSenseRDR2.log`
(`Debug=1` logs every weapon, strike and unknown ground material).

## Known limits / to verify in game
- Weapon names marked unverified in the lab fall back to their weapon group (logged as "group fallback").
- Ground materials are identified from the game's material hash, which is `joaat("<name>_<line in materials.dat>")` (e.g. `mud_soft_39`); the mod tries known material names with every line number. Unidentified ones count as dirt (logged with Debug=1). F10 shows the ground under you; F10 again while shown overrides it.
- Bow assumed to draw on R2 hold; fanning assumed on rapid hip-fire taps.
- The game-audio layer listens to the default output; with other apps playing (music, voice chat) those are felt too.
