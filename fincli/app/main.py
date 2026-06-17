"""FinCLI application entrypoint."""

from __future__ import annotations

from fincli.app.utils.logger import configure_logging
from fincli.app.diagnostics.runtime import startup_dependency_error


def main() -> None:
    """Run the FinCLI TUI application."""
    configure_logging()
    try:
        from fincli.app.tui.layout import FinCLIApp
    except ImportError as exc:
        print(startup_dependency_error(exc))
        raise SystemExit(1) from exc
    FinCLIApp().run()


if __name__ == "__main__":
    main()
