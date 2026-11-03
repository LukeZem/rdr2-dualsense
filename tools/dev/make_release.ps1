# Builds the release zip: release\DualSenseRDR2-v<version>.zip
#   DualSenseRDR2.asi, DualSenseRDR2\ (weapons, haptics, sound labels), lml\ (the Settings page), README.txt,
#   LICENSE.txt
# Your personal calibration.json is NOT included (players get estimated zones + auto-align).
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$version = (Select-String -Path "$root\mod\src\common.h" -Pattern 'kVersion = "([^"]+)"').Matches[0].Groups[1].Value
$asi = "$root\mod\build\DualSenseRDR2.asi"
if (-not (Test-Path $asi)) { throw "build the mod first" }

$stage = "$root\release\stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force "$stage\DualSenseRDR2" | Out-Null
Copy-Item $asi $stage
foreach ($f in "weapons.json", "haptics.json", "sound_labels.json") { Copy-Item "$root\tools\trigger_lab\data\$f" "$stage\DualSenseRDR2\" }
# the Settings page for Lenny's Mod Loader, laid out like <game>\lml
$lml = "$root\mod\lml\DualSenseRDR2"
$archives = @("replace\update_4\x64\data\ui\startup_data.rpf")
$loose = "install.xml", "data\ui\settings\controls.ymt", "data\gamepad_icons_pc.ytd", "data\pm_settings_controls.ytd"
foreach ($f in $loose + $archives) {
    if (-not (Test-Path "$lml\$f")) { throw "LML file missing: $f (run the tools\rpf8 builders)" }
}
New-Item -ItemType Directory -Force "$stage\lml\DualSenseRDR2\data\ui\settings" | Out-Null
foreach ($f in $loose) { Copy-Item "$lml\$f" "$stage\lml\DualSenseRDR2\$f" }
foreach ($a in $archives) {
    New-Item -ItemType Directory -Force (Split-Path "$stage\lml\$a") | Out-Null
    Copy-Item "$lml\$a" "$stage\lml\$a"
}
# (the texts are not a file: the .asi adds them to the game's string table - any game language)
Copy-Item "$root\release\README.txt" $stage
Copy-Item "$root\LICENSE" "$stage\LICENSE.txt"

$zip = "$root\release\DualSenseRDR2-v$version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Remove-Item $stage -Recurse -Force
Get-Item $zip | Select-Object Name, Length
