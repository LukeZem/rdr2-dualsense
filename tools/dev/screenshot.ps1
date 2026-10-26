# Screenshot a window by title (DPI-aware). Usage: screenshot.ps1 -Title "*Trigger Lab*" -Out file.png
param([string]$Title = "*Trigger Lab*", [string]$Out = "$env:TEMP\shot.png")
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Win { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
public struct R { public int L, T, Rt, B; } }
"@
[Win]::SetProcessDPIAware() | Out-Null
$w = Get-Process | Where-Object { $_.MainWindowTitle -like $Title } | Select-Object -First 1
if (-not $w) { "window not found"; exit 1 }
$h = $w.MainWindowHandle
[Win]::ShowWindow($h, 9) | Out-Null; [Win]::SetForegroundWindow($h) | Out-Null; Start-Sleep -Milliseconds 900
$r = New-Object Win+R; [Win]::GetWindowRect($h, [ref]$r) | Out-Null
$bmp = New-Object System.Drawing.Bitmap ([int]($r.Rt - $r.L)), ([int]($r.B - $r.T))
$g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
$small = New-Object System.Drawing.Bitmap $bmp, ([int]($bmp.Width * 0.6)), ([int]($bmp.Height * 0.6))
$small.Save($Out); "$Out $($bmp.Width)x$($bmp.Height)"
