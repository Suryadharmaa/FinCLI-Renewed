$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    & "$root/scripts/build_desktop_backend.ps1"
    Push-Location "$root/desktop"
    try {
        & npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw "Desktop npm installation failed: $LASTEXITCODE" }
        if (-not (Test-Path "src-tauri/icons/icon.ico")) {
            & npm.cmd run tauri:icons
            if ($LASTEXITCODE -ne 0) { throw "Desktop icon generation failed: $LASTEXITCODE" }
        }
        $backend = (Resolve-Path "$root/desktop/src-tauri/binaries/fincli-backend-x86_64-pc-windows-msvc.exe").Path
        $env:FINCLI_BACKEND_BINARY = $backend
        & npm.cmd run tauri:build
        if ($LASTEXITCODE -ne 0) { throw "Desktop Tauri build failed: $LASTEXITCODE" }
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

    # Validate the packaged backend and real desktop lifecycle before replacing artifacts.
    & "$root/scripts/smoke_desktop_backend.ps1"
    & "$root/scripts/smoke_desktop_app.ps1"

    $rootExecutable = Join-Path $root "FinCLI.exe"
    Copy-Item -LiteralPath $portable -Destination $rootExecutable -Force
    Set-Content -LiteralPath "$rootExecutable.sha256" -Value "$($hash.Hash.ToLowerInvariant())  FinCLI.exe" -Encoding ascii
    $sourceCommit = (& git -C $root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Cannot resolve build source commit." }
    $manifest = [ordered]@{
        version = $version
        source_commit = $sourceCommit
        sha256 = $hash.Hash.ToLowerInvariant()
        size_bytes = (Get-Item -LiteralPath $rootExecutable).Length
        build_run = $env:GITHUB_RUN_ID
        checks = @("packaged-backend", "desktop-startup", "single-instance", "desktop-shutdown")
    }
    $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root "FinCLI.build.json") -Encoding utf8
    Write-Host "Root portable app: $rootExecutable"

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
