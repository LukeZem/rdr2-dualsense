# Closes RDR2, installs the freshly built mod, starts the game again and checks that it really started.
# Steam ignores a launch while it still thinks the game runs (the Rockstar launcher takes a while to exit),
# so: wait until everything is gone, give Steam a few seconds, launch, verify, retry once.
param([switch]$NoInstall)
$names = "RDR2", "PlayRDR2", "Launcher", "RockstarService", "RockstarErrorHandler", "SocialClubHelper"
# (the quit confirmation is answered with Enter below; the game saves nothing on quit, so only quit after saving)
function Running { Get-Process -Name $names -ErrorAction SilentlyContinue }

# close it like a player would (window close), so the game saves and Steam can sync; force only if it hangs
$g = Get-Process RDR2 -ErrorAction SilentlyContinue
if ($g) {
    $g | ForEach-Object { [void]$_.CloseMainWindow() }
    $t = 0
    while ((Get-Process RDR2 -ErrorAction SilentlyContinue) -and $t -lt 30) {
        Start-Sleep -Seconds 1; $t++
        # the game asks "quit?" first: confirm it (Enter) a moment after the close request, and again if needed
        if ($t -eq 2 -or $t -eq 6) { & (Join-Path $PSScriptRoot "gamekeys.ps1") -Keys "enter" | Out-Null }
    }
    if (Get-Process RDR2 -ErrorAction SilentlyContinue) { "game did not close in 30 s - forcing"; Stop-Process -Name RDR2 -Force }
}
$t = 0
while ((Running) -and $t -lt 60) { Start-Sleep -Seconds 1; $t++ }
if (Running) { Stop-Process -Name $names -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 }
"game closed after $t s"

if (-not $NoInstall) {
    & (Join-Path $PSScriptRoot "..\..\mod\install.ps1") | Select-String "Installed"
}

Start-Sleep -Seconds 20                   # let Steam notice the game is gone and sync the saves
for ($try = 1; $try -le 2; $try++) {
    Start-Process "steam://rungameid/1174180"
    $t = 0
    while (-not (Get-Process -Name RDR2, PlayRDR2 -ErrorAction SilentlyContinue) -and $t -lt 45) { Start-Sleep -Seconds 1; $t++ }
    if (Get-Process -Name RDR2, PlayRDR2 -ErrorAction SilentlyContinue) { "game starting (try $try)"; exit 0 }
    "no game process after 45 s - retrying"
    Start-Sleep -Seconds 5
}
"game did not start"
exit 1
