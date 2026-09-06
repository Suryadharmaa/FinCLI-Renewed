"""Shared local storage paths and desktop data migration."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

LEGACY_APP_DIR = Path.home() / ".fincli"


def _desktop_app_dir() -> Path:
    configured = os.getenv("FINCLI_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if base:
        return Path(base) / "FinCLI"
    return LEGACY_APP_DIR


APP_DIR = _desktop_app_dir() if os.getenv("FINCLI_DESKTOP") == "1" else LEGACY_APP_DIR
CONFIG_FILE = APP_DIR / "config.json"


def migrate_legacy_data() -> bool:
    """Copy non-secret legacy data into the desktop data root once.

    Secrets are deliberately excluded so the secrets module can migrate them
    into the OS credential store using the legacy encryption key when needed.
    Existing desktop files always win; user data is never overwritten.
    """
    if APP_DIR == LEGACY_APP_DIR or not LEGACY_APP_DIR.is_dir():
        return False
    APP_DIR.mkdir(parents=True, exist_ok=True)
    excluded = {"secrets.env", ".secrets_key", "secrets_metadata.json"}
    copied = False
    for source in LEGACY_APP_DIR.iterdir():
        if source.name in excluded:
            continue
        target = APP_DIR / source.name
        if target.exists():
            continue
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            copied = True
        except OSError:
            # Startup must remain usable if one optional cache/log is locked.
            continue
    return copied


if APP_DIR != LEGACY_APP_DIR:
    migrate_legacy_data()
