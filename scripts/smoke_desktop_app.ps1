$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $root "desktop/src-tauri/target/release/fincli.exe"
if (-not (Test-Path $executable)) {
    throw "Portable FinCLI executable not found: $executable"
}

$app = Start-Process -FilePath $executable -PassThru
$backend = $null
$second = $null
try {
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        Start-Sleep -Milliseconds 500
        $backend = Get-CimInstance Win32_Process -Filter "Name = 'fincli-backend.exe'" | Where-Object { $_.CommandLine -like '*--desktop*' } | Select-Object -First 1
        if ($backend) { break }
        if ($app.HasExited) { throw "FinCLI exited before starting its embedded backend (code $($app.ExitCode))." }
    }
    if (-not $backend) { throw "Embedded backend did not start within 60 seconds." }
    if ($backend.CommandLine -notmatch "--port\s+(\d+)") { throw "Could not determine the embedded backend port." }
    $port = [int]$Matches[1]
    $response = $null
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/health" -f $port) -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { break }
        } catch { }
    }
    if ($null -eq $response) { throw "Embedded backend health endpoint did not become ready." }
    if ($response.StatusCode -ne 200) { throw "Desktop backend health check failed: $($response.StatusCode)" }
    $second = Start-Process -FilePath $executable -PassThru
    if (-not $second.WaitForExit(10000)) { throw "Second FinCLI instance did not exit." }
    Write-Host "SMOKE_OK $($response.Content) app=$($app.Id) backend=$($backend.ProcessId) port=$port"
} finally {
    if ($app -and -not $app.HasExited) {
        $app.CloseMainWindow() | Out-Null
        $null = $app.WaitForExit(10000)
    }
    $backendStopped = $false
    if ($backend) {
        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            if (-not (Get-Process -Id $backend.ProcessId -ErrorAction SilentlyContinue)) { $backendStopped = $true; break }
            Start-Sleep -Milliseconds 250
        }
    }
    if ($backend -and -not $backendStopped -and (Get-Process -Id $backend.ProcessId -ErrorAction SilentlyContinue)) {
        taskkill.exe /PID $backend.ProcessId /T /F 2>$null | Out-Null
    }
    if ($second -and -not $second.HasExited) { taskkill.exe /PID $second.Id /T /F 2>$null | Out-Null }
    if ($app -and -not $app.HasExited) { taskkill.exe /PID $app.Id /T /F 2>$null | Out-Null }
    if ($backend -and -not $backendStopped) { throw "Embedded backend did not stop cleanly with the desktop app." }
}
