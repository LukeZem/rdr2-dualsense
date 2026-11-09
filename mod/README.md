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
| Haptics | Shots from each gun's own recordings (read from the game's archives through its file layer, or from an LML sound mod such as RWS if installed); the game's rumble converted for the voice coils; **game-audio layer**: what you hear (hooves, explosions, cutscenes, mini-games) as haptics, keeping left/right, quieter while a weapon effect plays. |
| Dialogue | Experimental, off by default (`[Haptics] Dialogue=1`): every spoken line felt as the speaker's own voice, panned to their side. The exact recording is found from the game's speech request (voice + line + variation, `gamemem.cpp`) or the playing cutscene audio, decoded from the game's archives (`awc.cpp`, stb_vorbis) and timed by the line's own play clock; `SoundDelayMs` matches TV / headphone lag (auto: Bluetooth 200 ms, else 60 ms). |
| Cutscenes | Steps, hooves, gunfire, hits and explosions are felt in cutscenes as in play. |
| Pause / loading | The script thread stops in pause menus and loading screens: when the game state is older than 0.25 s everything goes quiet (effects, the game's rumble, dialogue tracks). |
| Around you | Damage felt from its direction and by cause (bullet, melee, animal, fall); nearby gunfire pressure waves from their direction; heartbeat at low health and in Dead Eye; shivers in freezing cold. |
| Explosions | The game's own, as they happen (`IS_EXPLOSION_IN_SPHERE`: dynamite, gas, lanterns, Molotovs, explosive rounds, lightning) - kind by explosion tag, distance by nested spheres, side by spheres left / right of the camera. Blasts: the game's explosion recordings + a pressure-wave shove + the ground rolling on for ~2 s; within 15 m the whole controller shakes and both triggers shudder. |
| Fights | While shots, hits or explosions happen (3 s), the everyday textures (steps, hooves, wading, bushes, rain, wheels) play at half strength. |
| Horse / feet | Hoofbeats and footsteps from the real limbs touching the ground: each limb's height above the ground under it (glitches of the ground query held, snow sinking accepted), rise -> fall -> the fall stops near the bottom = touchdown (`World::touchdown`, designed and scored offline with `tools/dev/limbs_touchdown.py`). Hooves ~88% of contacts, ~35 ms after landing; nothing is generated when the legs can't be read. The horse's heartbeat and breathing when it is spent; rearing. |
| Ground | The game's ground material, identified by name (mud_soft, gravel_dirt, pine_needles, wood_solid_medium...) - footsteps and hooves feel like it: every material its own recipe in 4 takes, heavier at a sprint. |
| Water / bushes / swimming | Wading (`GET_ENTITY_SUBMERGED_LEVEL`): a drag with every step that grows with depth and pace, a splash going in. Bushes (the ped blackboard's `FoliageActive` / `FoliageHeight`): a rustle going in and brushing while you move through, by plant height - nothing while standing. Swimming (`World::strokes`): each hand / foot / horse leg's position along the body's heading; a stroke is felt when it has come back from its furthest reach by max(3 cm, 10% of the stroke) - horse legs 6 cm / 30% (designed on recorded swims: every pull, ~0.13 s after the reach); a jump into water (falling > 2 m/s) splashes. |
| Trains / wagons | Rail joints (front and rear bogie), ruts. |
| Lightbar | Muzzle flash, damage flash, Dead Eye sepia glow, lantern flicker, wanted (red/white), low-health pulse, time-of-day ambience. Player LEDs show the rounds left. |
| Speaker | Off by default (`[Speaker] Mechanics`). The game's own recordings for drawing / holstering a revolver, the lasso throw and the rope (found by name in the sound banks); synthesized cocking / lever / bolt / pump clicks. |
| Gyro aim | Experimental, off by default: small gyro corrections while free-aiming (`[Gyro] Mode=aim`). |
| Microphone | Whistle into the controller → horse call. Say "chao" → a real greeting (counts for honor). "Easy" → calm the horse. A command only counts when said on its own (after a pause, short, confident). The mute button toggles listening (mute LED on = not listening). |
| Weather | Rain on the hat, as dense as the game's rain (`[Haptics] Weather`, 30%). |
| Touchpad | Click = map (BACK). Swipes / two-finger tap can be mapped to buttons in the ini. |
| Plug in any time | The game checks for new pads only when Windows reports a device change, before the mod has the controller open; the mod marks the game's pad slot itself (`gamemem::mark_pad_slot`) and reopens the controller's audio. |

Settings: `DualSenseRDR2.ini` (F9 or holding PS ~1 s reloads it and the data folder in game; changed defaults reach
existing ini files unless the player changed that setting - `Config::migrate`). Log: `DualSenseRDR2.log`
(`Debug=1` logs every weapon, strike and unknown ground material).

## Known limits / to verify in game
- Weapon names marked unverified in the lab fall back to their weapon group (logged as "group fallback").
- Ground materials are identified from the game's material hash, which is `joaat("<name>_<line in materials.dat>")` (e.g. `mud_soft_39`); the mod tries known material names with every line number. Unidentified ones count as dirt (logged with Debug=1). F10 shows the ground under you; F10 again while shown overrides it.
- Bow assumed to draw on R2 hold; fanning assumed on rapid hip-fire taps.
- The game-audio layer listens to the default output; with other apps playing (music, voice chat) those are felt too.
