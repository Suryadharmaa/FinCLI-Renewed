from __future__ import annotations

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.diagnostics.runtime import check_runtime_environment, startup_dependency_error


def _render_text(renderable: object) -> str:
    console = Console(record=True, width=140)
    console.print(renderable)
    return console.export_text()


def test_runtime_environment_reports_launch_dependencies() -> None:
    checks = check_runtime_environment()
    names = {check.name for check in checks}

    assert "Python" in names
    assert "Package Metadata" in names
    assert "User Config Dir" in names
    assert "Dependency:textual" in names
    assert "Dependency:rich" in names
    assert all(check.status in {"ok", "warning", "info", "error"} for check in checks)


def test_doctor_includes_runtime_dependency_checks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FINCLI_CONFIG_HOME", str(tmp_path))
    router = CommandRouter()

    result = router.route("/doctor")
    text = _render_text(result.renderable)

    assert result.status == "ready"
    assert "Dependency:textual" in text
    assert "Package Metadata" in text
    assert "User Config Dir" in text


def test_startup_dependency_error_is_actionable() -> None:
    error = startup_dependency_error(ImportError("No module named textual", name="textual"))

    assert "textual" in error
    assert "npm install -g @drico2008/fincli@latest" in error
    assert "pip install -e" in error
