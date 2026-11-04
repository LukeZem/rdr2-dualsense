# DualSense for RDR2

Full DualSense support for Red Dead Redemption 2 on PC — adaptive triggers per weapon, voice-coil haptics,
lightbar, speaker and microphone (beta), driven by what the game is actually doing (ScriptHookRDR2 `.asi` mod).

Players: download it from **[Nexus Mods](https://www.nexusmods.com/reddeadredemption2/mods/11444)** or the
[GitHub release](https://github.com/OldKrab/rdr2-dualsense/releases/tag/v1.0.0), and read `release/README.txt`.

## Repository layout
| Path | What |
|---|---|
| `mod/` | The mod (C++17, CMake + MinGW-w64). `mod/README.md`: build, install, feature table. |
| `mod/src/` | Controller I/O (HID, WASAPI haptics), trigger engine, game state (natives), features, voice/whistle. |
| `tools/trigger_lab/` | Python lab to design and test trigger effects and haptic recipes outside the game; `data/` holds the weapon profiles and haptic recipes the mod ships. |
| `tools/awc/` | Game sound bank tools (AWC decoding, sound / material name recovery). |
| `tools/dev/` | Release script, ini updater, one-off patch scripts. |
| `release/` | Player README and mod page text. |

## Build
```
cmake -S mod -B mod/build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build mod/build
mod/build/dsr2_test.exe --selftest
powershell -ExecutionPolicy Bypass -File tools/dev/make_release.ps1
```

## License
MIT — see `LICENSE`. Uses nlohmann/json (MIT). Research credits: alloc8or's RDR3 native DB, femga's
rdr3_discoveries, decompiled RDR3 script references.
