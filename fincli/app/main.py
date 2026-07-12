"""FinCLI application entrypoint."""

from __future__ import annotations

import sys

from fincli.app.diagnostics.runtime import startup_dependency_error
from fincli.app.utils.logger import configure_logging


def main() -> None:
    """Run the FinCLI TUI application."""
    configure_logging()
    if "--web" in sys.argv:
        from fincli.app.web.server import main as web_main

        sys.argv = [sys.argv[0], *[arg for arg in sys.argv[1:] if arg != "--web"]]
        web_main()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "web":
        _run_web_command(sys.argv[2:])
        return
    try:
        from fincli.app.tui.layout import FinCLIApp
    except ImportError as exc:
        print(startup_dependency_error(exc))
        raise SystemExit(1) from exc
    FinCLIApp().run()


def _run_web_command(args: list[str]) -> None:
    from fincli.app.web.manager import WebServerManager

    manager = WebServerManager()
    action = args[0].lower() if args else "status"
    if action == "start":
        status = manager.start()
        print(f"FinCLI Web starting at {status['url']}")
        print("Use `fincli web token rotate` if you need a new access token.")
    elif action == "stop":
        print("FinCLI Web stopped." if manager.stop() else "FinCLI Web is not running.")
    elif action == "restart":
        print(f"FinCLI Web restarting at {manager.restart()['url']}")
    elif action == "open":
        print(f"Opened {manager.open()}")
    elif action == "token" and len(args) > 1 and args[1].lower() == "rotate":
        print(f"New local access token: {manager.rotate_token()}")
    elif action == "logs":
        print(manager.logs())
    else:
        status = manager.status()
        print(f"FinCLI Web: {'running' if status['running'] else 'stopped'}")
        print(f"URL: {status['url']} | Auth: {'required' if status['auth'] else 'disabled'}")


if __name__ == "__main__":
    main()
