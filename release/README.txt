DualSense for RDR2  v1.0.0  -  by OldKrab
==========================================

Full DualSense support for Red Dead Redemption 2 on PC: adaptive triggers made per weapon,
voice-coil haptics, lightbar, speaker and microphone - driven by what the game is actually doing.


REQUIREMENTS
------------
- Red Dead Redemption 2 (PC, Steam / Rockstar / Epic), story mode
- Script Hook RDR2 + its ASI loader (dinput8.dll) - https://www.dev-c.com/rdr2/scripthookrdr2/
- A DualSense controller connected by USB cable (haptics and the speaker need USB;
  over Bluetooth you get triggers, lightbar and a rumble fallback)
- Close DSX / DS4Windows, and turn Steam Input OFF for RDR2
  (Steam -> RDR2 -> Properties -> Controller -> Disable Steam Input)
- Remove other DualSense mods (DualSenseHaptics.asi, NodixDualSense.asi ...) - they fight over the controller
- For the settings page in the game's menu: Lenny's Mod Loader (LML). Works with any game language (the
  page's texts are in English). Without LML everything else works; you change settings in
  DualSenseRDR2.ini instead.


INSTALL
-------
Copy everything from this zip into the game folder (where RDR2.exe is):
    DualSenseRDR2.asi
    DualSenseRDR2\  (folder with weapons.json, haptics.json, sound_labels.json)
    lml\            (merges into LML's folder: lml\DualSenseRDR2 and one archive in lml\replace)
Start the game. Settings are created on first start in DualSenseRDR2.ini.
If you use LML's Mod Manager, make sure "DualSense for RDR2 - Settings page" is enabled.
Note: lml\replace\update_4\x64\data\ui\startup_data.rpf replaces a whole game archive (the menus) - if another
mod ships the same file, only one of the two can work.

UNINSTALL: delete DualSenseRDR2.asi, the DualSenseRDR2 folder, DualSenseRDR2.ini, DualSenseRDR2.log,
lml\DualSenseRDR2 and the archive above.


WHAT YOU FEEL
-------------
Triggers   Every weapon has its own pull: take-up, wall, crisp break. The shot fires exactly when the trigger
           breaks. Single-action guns need their hammer / lever / bolt worked with R2 (follows the game's own
           "ready to shoot"). Recoil shoves back against your finger. Dirty guns feel gritty, exhaustion and
           cold make the pull shaky, express / explosive ammo kicks harder.
Dead Eye   Every target you paint ticks under your finger; each shot of the volley kicks as it really fires.
Fishing    R2 loads the cast and tugs when a fish bites (strike!). L2 - the rod grip - carries the real line
           tension and strains right before the line snaps. You feel the fish surge left / right, the reel
           click, and the catch flapping in your hand.
Lasso      Rope tension and jerks while something fights the catch.
Horse      Hoofbeats from the real hooves at every gait, on the real ground (mud, gravel, wood, grass, snow...),
           its heartbeat and breathing when it is spent, rearing.
On foot    Footsteps from Arthur's real feet on the real ground, landings, ledge grabs, doors, drawing and
           holstering.
Around you Hits felt from the direction they came from, nearby gunfire, low-health heartbeat, shivering cold.
Honor      A warm swell and gold glow when honor rises, a sinking thud when it falls.
Camp life  Bites, sips and puffs, cleaning your gun, brushing / feeding the horse, skinning, stowing pelts,
           picking herbs, bathing, crafting, cooking.
Table games Five finger fillet (every stab - and the miss), poker and blackjack chips and cards, dominoes.
Weapon wheel L2/R2 click like a selector switch while you browse.
Lightbar   Muzzle flash, hits, Dead Eye, lantern flicker, wanted, low health, time of day.
           Player LEDs show the rounds left.
Speaker    The game's own draw / holster / lasso sounds and mechanism clicks from the controller.


VOICE AND WHISTLE (controller microphone, English, offline - the mute button pauses it)
---------------------------------------------------------------------------------------
  whistle                       call your horse
  "chao"                        Arthur greets the nearest person for real - counts for honor
  "easy" / "easy boy" / "steady"  calm or pat your horse
Say a command on its own, after a short pause - words in the middle of a conversation are ignored, so
talking to someone in the room won't set it off.
Words can be changed or switched off in DualSenseRDR2.ini, section [Voice] (leave a phrase empty to disable it).


SETTINGS
--------
In the game: Pause > Settings > Controls > Controller > DualSense - every setting of the mod, changed with
left / right like the game's own. Changes apply as soon as you close the menu.
Everything is also in DualSenseRDR2.ini (every effect has its own strength, 0 = off); F9 reloads the file
in game.
Gyro aim (EXPERIMENTAL, off by default): [Gyro] Mode=aim turns on small gyro corrections while you aim
with L2. It is still being tuned and can feel floaty.
F10 shows the ground under you; F10 again while shown overrides how it feels.
Debug=1 writes details to DualSenseRDR2.log - attach it when reporting a problem.


CREDITS
-------
Game research: alloc8or's RDR3 native database, femga's rdr3_discoveries, Halen84 and others' decompiled
script references. nlohmann/json (MIT). Script Hook RDR2 by Alexander Blade.
Source code (MIT): see the mod page.
