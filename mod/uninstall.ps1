# Removes DualSense for RDR2 and restores the mods install.ps1 moved away (latest backup).
# Usage: powershell -ExecutionPolicy Bypass -File uninstall.ps1 [-GameDir "..."] [-KeepSettings]
param([string]$GameDir = "", [switch]$KeepSettings)
$ErrorActionPreference = "Stop"
if (-not $GameDir) {
    $steam = (Get-ItemProperty "HKCU:\Software\Valve\Steam").SteamPath -replace "/", "\"
    $GameDir = Join-Path $steam "steamapps\common\Red Dead Redemption 2"
}
if (Get-Process -Name RDR2 -ErrorAction SilentlyContinue) { throw "Close Red Dead Redemption 2 first." }
$asi = Join-Path $GameDir "DualSenseRDR2.asi"
if (Test-Path $asi) { Remove-Item $asi; Write-Host "Removed DualSenseRDR2.asi" }
if (-not $KeepSettings) {
    foreach ($f in "DualSenseRDR2.ini", "DualSenseRDR2.log") { $p = Join-Path $GameDir $f; if (Test-Path $p) { Remove-Item $p } }
    $data = Join-Path $GameDir "DualSenseRDR2"
    if (Test-Path $data) { Remove-Item $data -Recurse }
}
$root = Join-Path $GameDir "DualSenseRDR2_backup"
$last = Get-ChildItem $root -Directory -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
if ($last) {
    Get-Content (Join-Path $last.FullName "moved.txt") | ForEach-Object {
        Move-Item (Join-Path $last.FullName $_) (Join-Path $GameDir $_) -Force
        Write-Host "Restored $_"
    }
    Remove-Item $last.FullName -Recurse
}
Write-Host "Done."
