# One test cycle for a settings-page build: installs <Rpf> as the LML startup_data.rpf, restarts the game,
# opens Settings > Controls > Controller > DualSense from the title screen and takes a screenshot.
# Usage: test_page_variant.ps1 -Rpf build\page_variant\minimal\replace\update_4\x64\data\ui\startup_data.rpf -Shot C:\tmp\v_minimal.png
param([Parameter(Mandatory)][string]$Rpf, [string]$Shot = "C:\tmp\page.png")
$dst = "C:\Steam\steamapps\common\Red Dead Redemption 2\lml\replace\update_4\x64\data\ui\startup_data.rpf"
Stop-Process -Name RDR2, PlayRDR2 -Force -ErrorAction SilentlyContinue
$t = 0
while ((Get-Process RDR2 -ErrorAction SilentlyContinue) -and $t -lt 30) { Start-Sleep -Seconds 1; $t++ }
Start-Sleep -Seconds 2
Copy-Item $Rpf $dst -Force -ErrorAction Stop
"installed $Rpf ($((Get-Item $dst).Length) bytes)"
& (Join-Path $PSScriptRoot "restart_game.ps1") -NoInstall
if ($LASTEXITCODE -ne 0) { exit 1 }
$t = 0
while (-not (Get-Process RDR2 -ErrorAction SilentlyContinue) -and $t -lt 120) { Start-Sleep -Seconds 2; $t += 2 }
& (Join-Path $PSScriptRoot "test_settings_row.ps1") -Press -Shot $Shot -MinWait 60
