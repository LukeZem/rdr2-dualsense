# Renders release\art\*.html (1920x1080 artwork) to PNG with headless Edge.
# Usage: render_art.ps1 [-Name controller.svg] [-Out banner.png]
param([string]$Name = "controller.svg", [string]$Out = "banner.png")
$art = Resolve-Path (Join-Path $PSScriptRoot "..\..\release\art")
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$src = "file:///" + ((Join-Path $art "$Name.html") -replace "\\", "/")
$dst = Join-Path $art $Out
if (Test-Path $dst) { Remove-Item $dst }
$p = Start-Process -FilePath $edge -PassThru -Wait -WindowStyle Hidden -ArgumentList @(
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
    "--user-data-dir=$env:TEMP\edge-render", "--window-size=1920,1080", "--screenshot=$dst", $src)
if (Test-Path $dst) { "rendered $dst" } else { "render failed" }
