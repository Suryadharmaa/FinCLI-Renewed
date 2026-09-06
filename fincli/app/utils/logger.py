"""Logging setup for FinCLI."""

from __future__ import annotations

import logging
import os

from fincli.app.storage.config_paths import APP_DIR

LOG_FILE = APP_DIR / "logs" / "backend.log" if os.getenv("FINCLI_DESKTOP") == "1" else APP_DIR / "fincli.log"


def configure_logging() -> None:
    """Configure file logging without leaking to the terminal UI."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
