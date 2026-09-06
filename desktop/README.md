# FinCLI Desktop

The Windows desktop app is a Tauri shell around the existing FastAPI workspace.
The Python backend is built as a PyInstaller one-file executable and embedded
inside the Tauri binary. At runtime the app extracts it into a private
temporary folder, starts it on a loopback-only ephemeral port, and removes it
when the app exits.

For end users, the intended entrypoint is the portable single-file app:
`fincli.exe`. Python, Node, npm, and a separate backend file are not required.

## Local build

1. Install Rust, the Windows WebView2 runtime, and Tauri prerequisites on the build machine only.
2. From the repository root run `powershell -ExecutionPolicy Bypass -File scripts/build_desktop.ps1`.

The script builds the Python payload, embeds it into Tauri, builds the frontend,
and prints a SHA-256 checksum for the final executable.

The release build is single-file portable output at
`desktop/src-tauri/target/release/fincli.exe`. An NSIS bundle remains available
for managed deployment, but it is optional. WebView2 remains the only Windows
system runtime prerequisite.

The app stores user data in `%LOCALAPPDATA%\FinCLI` and automatically copies
non-secret data from the legacy `%USERPROFILE%\.fincli` directory. API keys
remain in Windows Credential Manager.

To smoke-test the packaged backend before the Tauri build, run
`powershell -ExecutionPolicy Bypass -File scripts/smoke_desktop_backend.ps1`.
After the release build, run
`powershell -ExecutionPolicy Bypass -File scripts/smoke_desktop_app.ps1` to
verify that the native app starts its embedded backend.
