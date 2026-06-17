from __future__ import annotations

from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def render_text(renderable: object) -> str:
    console = Console(record=True, width=120)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))


def test_plain_text_input_returns_error_not_ready(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("help")

    assert result.status == "error"
    assert "Command harus diawali slash" in render_text(result.renderable)


def test_non_string_input_returns_user_facing_error(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route(None)  # type: ignore[arg-type]

    assert result.status == "error"
    assert "Command harus berupa teks" in render_text(result.renderable)


def test_history_recording_failure_does_not_break_command_result(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    def broken_record_event(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("history db unavailable")

    router.history.record_event = broken_record_event  # type: ignore[method-assign]

    result = router.route("/help")

    assert result.status == "ready"
    assert "FinCLI" in render_text(result.renderable)
