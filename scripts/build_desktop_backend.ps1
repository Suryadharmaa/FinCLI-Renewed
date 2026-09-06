$ErrorActionPreference = "Stop"

$python = Get-Command python -ErrorAction Stop
& $python.Source -m pip install ".[desktop]"
if ($LASTEXITCODE -ne 0) { throw "Desktop dependency installation failed with exit code $LASTEXITCODE." }
& $python.Source -m PyInstaller --clean --noconfirm scripts/fincli_backend.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller backend build failed with exit code $LASTEXITCODE." }

$target = "desktop/src-tauri/binaries/fincli-backend-x86_64-pc-windows-msvc.exe"
New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
Copy-Item -Force dist/fincli-backend.exe $target
Write-Host "Embedded desktop backend ready: $target"
Write-Host "Next: from desktop run npm.cmd ci, npm.cmd run tauri:icons, and npm.cmd run tauri:build"
