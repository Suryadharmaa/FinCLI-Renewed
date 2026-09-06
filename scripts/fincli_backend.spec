from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPEC).resolve().parents[1]
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    *collect_submodules("keyring.backends"),
    *collect_submodules("fincli"),
]

a = Analysis(
    [str(project_root / "scripts" / "desktop_backend.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "fincli" / "app" / "web" / "static"), "fincli/app/web/static"),
        *collect_data_files("keyring"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "hypothesis", "textual"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# Without COLLECT, PyInstaller emits a single executable with its dependencies embedded.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="fincli-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
