"""PyInstaller entrypoint for the embedded FinCLI desktop backend."""

from fincli.app.web.server import main

if __name__ == "__main__":
    main()
