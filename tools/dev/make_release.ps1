# Builds the release zip: release\DualSenseRDR2-v<version>.zip
#   DualSenseRDR2.asi, DualSenseRDR2\ (weapons, haptics, sound labels), README.txt, LICENSE.txt
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
Copy-Item "$root\release\README.txt" $stage
Copy-Item "$root\LICENSE" "$stage\LICENSE.txt"

$zip = "$root\release\DualSenseRDR2-v$version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$stage\*" -DestinationPath $zip
Remove-Item $stage -Recurse -Force
Get-Item $zip | Select-Object Name, Length
