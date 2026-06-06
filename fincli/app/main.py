"""FinCLI application entrypoint."""

from __future__ import annotations

from fincli.app.tui.layout import FinCLIApp
from fincli.app.utils.logger import configure_logging


def main() -> None:
    """Run the FinCLI TUI application."""
    configure_logging()
    FinCLIApp().run()


if __name__ == "__main__":
    main()
