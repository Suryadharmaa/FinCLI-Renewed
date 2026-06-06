"""Logging setup for FinCLI."""

from __future__ import annotations

import logging
from pathlib import Path

APP_DIR = Path.home() / ".fincli"
LOG_FILE = APP_DIR / "fincli.log"


def configure_logging() -> None:
    """Configure file logging without leaking to the terminal UI."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
