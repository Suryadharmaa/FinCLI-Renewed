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

    $version = (Get-Content "$root/package.json" | ConvertFrom-Json).version
    $installer = Join-Path $root "desktop/src-tauri/target/release/bundle/nsis/FinCLI_${version}_x64-setup.exe"
    if (-not (Test-Path $installer)) {
        throw "Windows installer was not produced: $installer"
    }

    $releaseDir = Join-Path $root "release/v$version"
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    Copy-Item -LiteralPath $portable -Destination (Join-Path $releaseDir "fincli.exe") -Force
    Copy-Item -LiteralPath $installer -Destination (Join-Path $releaseDir (Split-Path $installer -Leaf)) -Force

    $releaseFiles = Get-ChildItem -LiteralPath $releaseDir -File -Filter "*.exe" | Sort-Object Name
    $checksums = foreach ($file in $releaseFiles) {
        $fileHash = Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256
        "$($fileHash.Hash)  $($file.Name)"
    }
    Set-Content -LiteralPath (Join-Path $releaseDir "SHA256SUMS.txt") -Value $checksums -Encoding ascii
    Write-Host "Publish-ready release: $releaseDir"
} finally {
    Pop-Location
}
