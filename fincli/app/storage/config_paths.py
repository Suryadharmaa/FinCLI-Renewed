"""Shared local storage paths."""

from __future__ import annotations

from pathlib import Path

APP_DIR = Path.home() / ".fincli"
CONFIG_FILE = APP_DIR / "config.json"
