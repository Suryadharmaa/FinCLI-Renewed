"""Run the FinCLI web server directly."""

from __future__ import annotations

import argparse

from fincli.app.web.manager import WebServerManager


def main() -> None:
    parser = argparse.ArgumentParser(description="FinCLI local web server")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    manager = WebServerManager()
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Web dependencies missing. Install with: pip install -e ".[web]"') from exc
    uvicorn.run("fincli.app.web.api:create_app", factory=True, host=manager.config.settings.web.host, port=manager.config.settings.web.port, reload=args.reload)


if __name__ == "__main__":
    main()
