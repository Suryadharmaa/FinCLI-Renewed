"""Run the FinCLI web server directly."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="FinCLI local web server")
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--host", default=None, help="Bind address; defaults to the configured local host")
    parser.add_argument("--port", type=int, default=None, help="Bind port; defaults to the configured local port")
    parser.add_argument("--desktop", action="store_true", help="Run as the managed desktop backend")
    args = parser.parse_args()
    if args.desktop:
        import os

        os.environ["FINCLI_DESKTOP"] = "1"
    from fincli.app.web.manager import WebServerManager

    manager = WebServerManager()
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit('Web dependencies missing. Install with: pip install -e ".[web]"') from exc
    uvicorn.run(
        "fincli.app.web.api:create_app",
        factory=True,
        host=args.host or manager.config.settings.web.host,
        port=args.port or manager.config.settings.web.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
