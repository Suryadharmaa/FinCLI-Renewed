$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & "$root/scripts/build_desktop_backend.ps1"
    Push-Location "$root/desktop"
    try {
        & npm.cmd ci
        if (-not (Test-Path "src-tauri/icons/icon.ico")) {
            & npm.cmd run tauri:icons
        }
        $backend = (Resolve-Path "$root/desktop/src-tauri/binaries/fincli-backend-x86_64-pc-windows-msvc.exe").Path
        $env:FINCLI_BACKEND_BINARY = $backend
        & npm.cmd run tauri:build
    } finally {
        Pop-Location
    }
    $portable = Join-Path $root "desktop/src-tauri/target/release/fincli.exe"
    if (-not (Test-Path $portable)) {
        throw "Portable fincli.exe was not produced: $portable"
    }
    $hash = Get-FileHash $portable -Algorithm SHA256
    Write-Host "Portable release: $portable"
    Write-Host "SHA256: $($hash.Hash)"
} finally {
    Pop-Location
}
