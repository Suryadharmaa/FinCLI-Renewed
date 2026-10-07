$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$output = Join-Path $root 'screenshots'
New-Item -ItemType Directory -Force $output | Out-Null
$manifest = Get-Content "$root/FinCLI.build.json" -Raw | ConvertFrom-Json
if ((Get-FileHash "$root/FinCLI.exe" -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) { throw 'Executable checksum mismatch.' }
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class FinCLICapture {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hDC, uint flags);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int cmd);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int w, int h, uint flags);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extra);
}
'@
function Capture-Window([IntPtr]$handle, [string]$name) {
    $rect = New-Object FinCLICapture+RECT
    [FinCLICapture]::GetWindowRect($handle, [ref]$rect) | Out-Null
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $dc = $graphics.GetHdc()
        try { $printed = [FinCLICapture]::PrintWindow($handle, $dc, 2) } finally { $graphics.ReleaseHdc($dc) }
        $bitmap.Save((Join-Path $output "$name-window.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
        $bitmap.Save((Join-Path $output "$name-screen.png"), [System.Drawing.Imaging.ImageFormat]::Png)
        Write-Host "CAPTURED $name ${width}x${height} PrintWindow=$printed"
    } finally { $graphics.Dispose(); $bitmap.Dispose() }
}
function Find-Nav([IntPtr]$handle, [string]$name) {
    $element = [System.Windows.Automation.AutomationElement]::FromHandle($handle)
    $condition = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button)
    $buttons = $element.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    foreach ($button in $buttons) {
        if ($button.Current.Name -match "^[^a-zA-Z]*$name`$" -and -not $button.Current.IsOffscreen) { return $button }
    }
    return $null
}
function Invoke-Nav($button) {
    $pattern = $null
    if ($button.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke(); return }
    $rect = $button.Current.BoundingRectangle
    [FinCLICapture]::SetCursorPos([int]($rect.Left + $rect.Width/2), [int]($rect.Top + $rect.Height/2)) | Out-Null
    [FinCLICapture]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
    [FinCLICapture]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
}
$env:FINCLI_DATA_DIR = Join-Path $env:RUNNER_TEMP ('FinCLI-capture-' + [guid]::NewGuid().ToString('N'))
$app = $null
try {
    $app = Start-Process "$root/FinCLI.exe" -PassThru
    $handle = [IntPtr]::Zero
    for ($i=0; $i -lt 100; $i++) {
        Start-Sleep -Milliseconds 500
        $app.Refresh()
        if ($app.HasExited) { throw "FinCLI exited: $($app.ExitCode)" }
        $handle = $app.MainWindowHandle
        if ($handle -ne [IntPtr]::Zero) { break }
    }
    if ($handle -eq [IntPtr]::Zero) { throw 'No FinCLI window.' }
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $width = [Math]::Min(1440, $screen.Width - 16)
    $height = [Math]::Min(920, $screen.Height - 40)
    [FinCLICapture]::ShowWindow($handle, 9) | Out-Null
    [FinCLICapture]::SetWindowPos($handle, [IntPtr]::Zero, 8, 8, $width, $height, 0) | Out-Null
    [FinCLICapture]::SetForegroundWindow($handle) | Out-Null
    Start-Sleep -Seconds 8
    $workspace = $null
    for ($i=0; $i -lt 40; $i++) {
        $workspace = Find-Nav $handle 'Workspace'
        if ($workspace) { break }
        Start-Sleep -Milliseconds 500
    }
    Capture-Window $handle 'FinCLI-Home'
    if (-not $workspace) { throw 'Workspace navigation unavailable; startup screenshot retained.' }
    Invoke-Nav $workspace
    Start-Sleep -Seconds 4
    Capture-Window $handle 'FinCLI-Workspace'
    $research = Find-Nav $handle 'Research'
    if ($research) {
        Invoke-Nav $research
        Start-Sleep -Seconds 2
        Capture-Window $handle 'FinCLI-Research'
    }
    $manifest | ConvertTo-Json | Set-Content (Join-Path $output 'source-build.json') -Encoding utf8
} finally {
    if ($app -and -not $app.HasExited) {
        $app.CloseMainWindow() | Out-Null
        if (-not $app.WaitForExit(10000)) { taskkill.exe /PID $app.Id /T /F | Out-Null }
    }
}
