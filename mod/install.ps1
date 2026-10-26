# Installs DualSense for RDR2 into the game folder.
#   - other DualSense mods are moved (not deleted) to DualSenseRDR2_backup\<time>\ - uninstall.ps1 restores them
#   - your DualSenseRDR2.ini is kept if it already exists
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1 [-GameDir "D:\Games\Red Dead Redemption 2"]
param([string]$GameDir = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$lab = Join-Path $here "..\tools\trigger_lab\data"

function Find-GameDir {
    $cands = @()
    try {
        $steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam").SteamPath -replace "/", "\"
        $cands += Join-Path $steam "steamapps\common\Red Dead Redemption 2"
        $vdf = Join-Path $steam "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            Select-String -Path $vdf -Pattern '"path"\s+"(.+)"' | ForEach-Object {
                $cands += Join-Path ($_.Matches[0].Groups[1].Value -replace "\\\\", "\") "steamapps\common\Red Dead Redemption 2"
            }
        }
    } catch {}
    $cands += "C:\Program Files\Rockstar Games\Red Dead Redemption 2", "C:\Program Files\Epic Games\RedDeadRedemption2"
    return $cands | Where-Object { Test-Path (Join-Path $_ "RDR2.exe") } | Select-Object -First 1
}

if (-not $GameDir) { $GameDir = Find-GameDir }
if (-not $GameDir -or -not (Test-Path (Join-Path $GameDir "RDR2.exe"))) { throw "Red Dead Redemption 2 not found - pass -GameDir" }
if (Get-Process -Name RDR2 -ErrorAction SilentlyContinue) { throw "Close Red Dead Redemption 2 first." }
Write-Host "Game: $GameDir"

$asi = Join-Path $here "build\DualSenseRDR2.asi"
if (-not (Test-Path $asi)) { throw "Build the mod first (build\DualSenseRDR2.asi missing)" }
foreach ($req in "ScriptHookRDR2.dll", "dinput8.dll") {
    if (-not (Test-Path (Join-Path $GameDir $req))) { Write-Warning "$req is missing - install Script Hook RDR2 and its ASI loader (dev-c.com)" }
}

# 1. move conflicting DualSense mods out of the way
$backup = Join-Path $GameDir ("DualSenseRDR2_backup\" + (Get-Date -Format "yyyyMMdd-HHmmss"))
$moved = @()
foreach ($f in "DualSenseHaptics.asi", "DualSenseHaptics.ini", "NodixDualSense.asi", "Nodix_DualSense.ini") {
    $p = Join-Path $GameDir $f
    if (Test-Path $p) {
        New-Item -ItemType Directory -Force $backup | Out-Null
        Move-Item $p (Join-Path $backup $f)
        $moved += $f
    }
}
if ($moved.Count) {
    $moved | Set-Content (Join-Path $backup "moved.txt")
    Write-Host "Disabled other DualSense mods (moved to $backup): $($moved -join ', ')"
}

# 2. the mod and its data
Copy-Item $asi (Join-Path $GameDir "DualSenseRDR2.asi") -Force
$data = Join-Path $GameDir "DualSenseRDR2"
New-Item -ItemType Directory -Force $data | Out-Null
foreach ($f in "weapons.json", "haptics.json", "calibration.json", "sound_labels.json") {
    $src = Join-Path $lab $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $data $f) -Force; Write-Host "  data: $f" }
}
if (-not (Test-Path (Join-Path $data "calibration.json"))) {
    Write-Warning "No trigger calibration yet - run the Trigger Lab's Calibrate page and install again for exact shot timing."
}
Write-Host "Installed DualSenseRDR2.asi"

# 3. things that would fight over the controller
if (Get-Process -Name DSX, DS4Windows -ErrorAction SilentlyContinue) {
    Write-Warning "DSX / DS4Windows is running - quit it before playing (it overwrites trigger effects)."
}
Write-Host "Done. Settings: $GameDir\DualSenseRDR2.ini (created on first start). Log: DualSenseRDR2.log"
