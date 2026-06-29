"""Runtime environment checks used by /doctor and startup guards."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
from pathlib import Path
import platform
import sys

from fincli import __version__


@dataclass(frozen=True, slots=True)
class RuntimeCheck:
    """Single display-safe runtime diagnostic result."""

    name: str
    status: str
    detail: str


REQUIRED_MODULES: tuple[tuple[str, str], ...] = (
    ("textual", "Textual TUI runtime"),
    ("rich", "terminal rendering"),
    ("httpx", "HTTP client"),
    ("pydantic", "data validation"),
    ("yfinance", "Yahoo Finance fallback"),
    ("pandas", "tabular market data"),
    ("numpy", "technical calculations"),
)


def check_runtime_environment() -> list[RuntimeCheck]:
    """Return launch-critical checks without exposing local secrets."""

    checks = [
        _python_version_check(),
        _package_version_check(),
        _npm_runtime_check(),
    ]
    checks.extend(_dependency_checks())
    checks.append(_user_config_dir_check())
    return checks


def startup_dependency_error(exc: ImportError) -> str:
    """Build a friendly startup message when a runtime dependency is missing."""

    missing = getattr(exc, "name", None) or "unknown"
    return (
        f"FinCLI failed to load Python dependency: {missing}\n\n"
        "Quick fix:\n"
        "- npm global: npm install -g @drico2008/fincli@latest --registry=https://registry.npmjs.org/\n"
        "- local dev : pip install -e \".[dev]\"\n\n"
        "If using npm global and the error persists, uninstall and reinstall:\n"
        "npm uninstall -g @drico2008/fincli && npm install -g @drico2008/fincli@latest"
    )


def _python_version_check() -> RuntimeCheck:
    version = platform.python_version()
    if sys.version_info >= (3, 11):
        return RuntimeCheck("Python", "ok", f"{version} ({sys.executable})")
    return RuntimeCheck("Python", "error", f"{version}; FinCLI requires Python 3.11+")


def _package_version_check() -> RuntimeCheck:
    try:
        installed = metadata.version("fincli")
    except metadata.PackageNotFoundError:
        return RuntimeCheck("Package Metadata", "warning", f"source import version={__version__}; package metadata not installed")
    if installed == __version__:
        return RuntimeCheck("Package Metadata", "ok", f"fincli {installed}")
    return RuntimeCheck("Package Metadata", "warning", f"package={installed}; import={__version__}")


def _dependency_checks() -> list[RuntimeCheck]:
    checks: list[RuntimeCheck] = []
    for module_name, purpose in REQUIRED_MODULES:
        if util.find_spec(module_name) is None:
            checks.append(RuntimeCheck(f"Dependency:{module_name}", "error", f"missing; required for {purpose}"))
        else:
            checks.append(RuntimeCheck(f"Dependency:{module_name}", "ok", purpose))
    return checks


def _npm_runtime_check() -> RuntimeCheck:
    executable = Path(sys.executable)
    if ".npm-python" not in {part.lower() for part in executable.parts}:
        return RuntimeCheck("npm Runtime", "info", "not running inside npm wrapper venv")
    if executable.exists():
        return RuntimeCheck("npm Runtime", "ok", str(executable))
    return RuntimeCheck("npm Runtime", "error", f"missing python executable: {executable}")


def _user_config_dir_check() -> RuntimeCheck:
    config_dir = Path.home() / ".fincli"
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        probe = config_dir / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return RuntimeCheck("User Config Dir", "error", f"{config_dir}: {exc}")
    return RuntimeCheck("User Config Dir", "ok", str(config_dir))
