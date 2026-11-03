# Presses keys in the game window (hardware scan codes via SendInput - games read those) and can take a
# screenshot afterwards. Used to test menus without a person at the controller.
# Usage: gamekeys.ps1 -Keys "esc","wait:1500","down","down","enter","hold:right:1500" [-Shot out.png] [-Delay 250]
param([string[]]$Keys = @(), [string]$Shot = "", [int]$Delay = 250, [string]$Title = "Red Dead Redemption 2")
Add-Type @"
using System; using System.Runtime.InteropServices;
public class GK {
  [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
  [StructLayout(LayoutKind.Explicit, Size=40)] public struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KEYBDINPUT ki; }
  [DllImport("user32.dll", SetLastError=true)] public static extern uint SendInput(uint n, INPUT[] inputs, int size);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  public static void Hold(ushort scan, bool extended, int ms) {
    INPUT[] i = new INPUT[1];
    uint ext = extended ? 1u : 0u;
    i[0].type = 1; i[0].ki.wScan = scan; i[0].ki.dwFlags = 0x0008 | ext;
    SendInput(1, i, Marshal.SizeOf(typeof(INPUT)));
    System.Threading.Thread.Sleep(ms);
    i[0].ki.dwFlags = 0x0008 | 0x0002 | ext;
    SendInput(1, i, Marshal.SizeOf(typeof(INPUT)));
  }
  public static void Key(ushort scan, bool extended) {
    INPUT[] i = new INPUT[2];
    uint ext = extended ? 1u : 0u;
    i[0].type = 1; i[0].ki.wScan = scan; i[0].ki.dwFlags = 0x0008 | ext;            // KEYEVENTF_SCANCODE
    i[1].type = 1; i[1].ki.wScan = scan; i[1].ki.dwFlags = 0x0008 | 0x0002 | ext;   // + KEYUP
    SendInput(1, new INPUT[] { i[0] }, Marshal.SizeOf(typeof(INPUT)));
    System.Threading.Thread.Sleep(60);
    SendInput(1, new INPUT[] { i[1] }, Marshal.SizeOf(typeof(INPUT)));
  }
}
"@
# scan code, extended
$map = @{
  "esc" = @(0x01, $false); "enter" = @(0x1C, $false); "space" = @(0x39, $false); "backspace" = @(0x0E, $false)
  "up" = @(0x48, $true); "down" = @(0x50, $true); "left" = @(0x4B, $true); "right" = @(0x4D, $true)
  "w" = @(0x11, $false); "a" = @(0x1E, $false); "s" = @(0x1F, $false); "d" = @(0x20, $false)
  "e" = @(0x12, $false); "q" = @(0x10, $false); "tab" = @(0x0F, $false); "p" = @(0x19, $false)
  "3" = @(0x04, $false); "4" = @(0x05, $false); "5" = @(0x06, $false); "f9" = @(0x43, $false); "f10" = @(0x44, $false); "f11" = @(0x57, $false); "z" = @(0x2C, $false); "x" = @(0x2D, $false); "c" = @(0x2E, $false)
}
$g = Get-Process -Name RDR2 -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $g) { "game not running"; exit 1 }
[void][GK]::ShowWindow($g.MainWindowHandle, 9)
[void][GK]::SetForegroundWindow($g.MainWindowHandle)
Start-Sleep -Milliseconds 400
foreach ($k in $Keys) {
  if ($k -like "wait:*") { Start-Sleep -Milliseconds ([int]$k.Substring(5)); continue }
  if ($k -like "hold:*") {                                  # hold:<key>:<ms> - key held down that long
    $p = $k.Split(":"); $m = $map[$p[1].ToLower()]
    if ($m) { [GK]::Hold([uint16]$m[0], [bool]$m[1], [int]$p[2]) }
    Start-Sleep -Milliseconds $Delay; continue
  }
  $m = $map[$k.ToLower()]
  if (-not $m) { "unknown key $k"; continue }
  [GK]::Key([uint16]$m[0], [bool]$m[1])
  Start-Sleep -Milliseconds $Delay
}
if ($Shot) {
  Start-Sleep -Milliseconds 300
  & (Join-Path $PSScriptRoot "screenshot.ps1") -Title "$Title*" -Out $Shot
}
