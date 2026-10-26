# In-game check of the "DualSense" settings row from the title screen:
# waits for the title, opens Settings > Controls > Controller, moves to our row (3rd), takes a screenshot,
# and reports a crash (the game's window title turns into "ERROR:...").
param([string]$Shot = "C:\tmp\row.png", [switch]$Press, [int]$MinWait = 0)
$dev = $PSScriptRoot
$py = Join-Path $dev "..\..\.venv\Scripts\python.exe"
$t = 0; $start = Get-Date
while ($t -lt 240) {
    Start-Sleep -Seconds 5; $t += 5
    $g = Get-Process RDR2 -ErrorAction SilentlyContinue
    if (-not $g) { "game not running"; exit 1 }
    if ($g.MainWindowTitle -like "ERROR*") { "CRASH at boot: $($g.MainWindowTitle)"; exit 2 }
    & (Join-Path $dev "screenshot.ps1") -Title "Red Dead Redemption 2*" -Out "C:\tmp\_title.png" | Out-Null
    if (-not (Test-Path "C:\tmp\_title.png")) { continue }
    $m = & $py -I -c "from PIL import Image, ImageStat; im=Image.open(r'C:\tmp\_title.png').convert('L').resize((320,180)); print(int(ImageStat.Stat(im).mean[0]))"
    # the legal/intro screens come first: only trust the brightness once the game has run a while
    # (keys pressed on an intro screen can quit the game, so a dim title is only trusted late)
    $el = ((Get-Date) - $start).TotalSeconds
    if (([int]$m -gt 40 -and $el -gt $MinWait) -or ([int]$m -gt 20 -and $el -gt 100)) { break }
}
"title after $t s"
$keys = @("wait:2000", "z", "wait:3000", "up", "wait:400", "enter", "wait:2000", "right", "wait:400", "enter", "wait:2500", "down", "wait:600", "down", "wait:1500")
if ($Press) { $keys += @("enter", "wait:2000") }
& (Join-Path $dev "gamekeys.ps1") -Keys $keys -Shot $Shot | Out-Null
$g = Get-Process RDR2 -ErrorAction SilentlyContinue
if (-not $g) { "game exited"; exit 2 }
if ($g.MainWindowTitle -like "ERROR*") { "CRASH: $($g.MainWindowTitle)"; exit 2 }
& $py -I -c "from PIL import Image; im=Image.open(r'$Shot'); im.thumbnail((1280,720)); im.save(r'$Shot'.replace('.png','_s.png'))"
"ok - screenshot $Shot"
