$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$executable = Join-Path $root "dist/fincli-backend.exe"
if (-not (Test-Path $executable)) {
    throw "Backend executable not found: $executable"
}

$temp = Join-Path $env:TEMP ("FinCLI-smoke-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force $temp | Out-Null
$oldDesktop = $env:FINCLI_DESKTOP
$oldToken = $env:FINCLI_DESKTOP_TOKEN
$oldData = $env:FINCLI_DATA_DIR
$env:FINCLI_DESKTOP = "1"
$env:FINCLI_DESKTOP_TOKEN = "smoke-token"
$env:FINCLI_DATA_DIR = $temp
$port = 19871
$stdout = Join-Path $temp "backend.stdout.log"
$stderr = Join-Path $temp "backend.stderr.log"
$process = Start-Process -FilePath $executable -ArgumentList @("--desktop", "--host", "127.0.0.1", "--port", $port) -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
try {
    $response = $null
    for ($attempt = 0; $attempt -lt 80; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $response = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/health" -f $port) -UseBasicParsing -TimeoutSec 1
            if ($response.StatusCode -eq 200) { break }
        } catch { }
    }
    if ($null -eq $response -or $response.StatusCode -ne 200) {
        Write-Host (Get-Content $stdout -Raw -ErrorAction SilentlyContinue)
        Write-Host (Get-Content $stderr -Raw -ErrorAction SilentlyContinue)
        throw "Backend health endpoint did not become ready."
    }
    $headers = @{ Authorization = "Bearer smoke-token" }
    $capabilities = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/api/desktop/capabilities" -f $port) -Headers $headers
    $commandHeaders = @{ Authorization = "Bearer smoke-token"; "X-FinCLI-CSRF" = "local-web" }
    $helpBody = @{ message = "/help"; conversation_id = "" } | ConvertTo-Json
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $help = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/api/chat" -f $port) -Method Post -Headers $commandHeaders -ContentType "application/json" -Body $helpBody -TimeoutSec 10
    $timer.Stop()
    $securityBody = @{ message = "/security scan"; conversation_id = "" } | ConvertTo-Json
    $securityTimer = [Diagnostics.Stopwatch]::StartNew()
    $security = Invoke-RestMethod -Uri ("http://127.0.0.1:{0}/api/chat" -f $port) -Method Post -Headers $commandHeaders -ContentType "application/json" -Body $securityBody -TimeoutSec 10
    $securityTimer.Stop()
    $css = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/app.css" -f $port) -UseBasicParsing
    $js = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/app.js" -f $port) -UseBasicParsing
    if ($capabilities.command_count -ne 155) { throw "Desktop capability count mismatch: $($capabilities.command_count)" }
    if ($help.kind -ne "help" -or $help.tables[0].rows.Count -ne 155) { throw "Packaged /help response is incomplete." }
    if ($timer.ElapsedMilliseconds -gt 3000) { throw "Packaged /help exceeded 3 seconds: $($timer.ElapsedMilliseconds)ms" }
    if (-not $security.ok) { throw "Packaged /security scan failed." }
    if ($securityTimer.ElapsedMilliseconds -gt 3000) { throw "Packaged /security scan exceeded 3 seconds: $($securityTimer.ElapsedMilliseconds)ms" }
    if ($css.StatusCode -ne 200 -or $js.StatusCode -ne 200) { throw "Packaged UI assets are not available." }
    if ($js.Content -notmatch "visibleMessages" -or $js.Content -notmatch "replaceLoading" -or $js.Content -match '\$\("#working"\)') { throw "Packaged UI does not contain the state-driven command lifecycle." }
    if ($css.Content -notmatch "--composer-bg" -or $css.Content -notmatch "color-scheme: light" -or $js.Content -notmatch "fincliTheme") { throw "Packaged UI does not contain the complete persistent light theme." }
    $database = Get-ChildItem -LiteralPath $temp -Filter "fincli.db" -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $database) {
        $stdoutText = Get-Content $stdout -Raw -ErrorAction SilentlyContinue
        $stderrText = Get-Content $stderr -Raw -ErrorAction SilentlyContinue
        throw "Portable backend did not create its data directory at $temp. stdout=$stdoutText stderr=$stderrText"
    }
    Write-Host "PACKAGED_OK $($response.Content) commands=$($capabilities.command_count) help=$($timer.ElapsedMilliseconds)ms security=$($securityTimer.ElapsedMilliseconds)ms css=$($css.StatusCode) js=$($js.StatusCode)"
} finally {
    if ($process -and -not $process.HasExited) { taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null }
    if ($null -eq $oldDesktop) { Remove-Item Env:FINCLI_DESKTOP -ErrorAction SilentlyContinue } else { $env:FINCLI_DESKTOP = $oldDesktop }
    if ($null -eq $oldToken) { Remove-Item Env:FINCLI_DESKTOP_TOKEN -ErrorAction SilentlyContinue } else { $env:FINCLI_DESKTOP_TOKEN = $oldToken }
    if ($null -eq $oldData) { Remove-Item Env:FINCLI_DATA_DIR -ErrorAction SilentlyContinue } else { $env:FINCLI_DATA_DIR = $oldData }
    Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
}
