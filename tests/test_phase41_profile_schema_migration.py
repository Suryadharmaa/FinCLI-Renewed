from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.modules.user_profile import UserProfileService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


def render_text(renderable: object) -> str:
    console = Console(record=True, width=120)
    console.print(renderable)
    return console.export_text()


def create_legacy_profile_table(db_file: Path) -> None:
    connection = sqlite3.connect(db_file)
    with connection:
        connection.executescript(
            """
            CREATE TABLE user_profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name TEXT NOT NULL,
                equity_amount REAL NOT NULL,
                equity_currency TEXT NOT NULL,
                equity_usd REAL NOT NULL,
                leverage TEXT NOT NULL,
                experience_years REAL NOT NULL,
                gameplay TEXT NOT NULL,
                rules_text TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO user_profile
                (id, name, equity_amount, equity_currency, equity_usd, leverage, experience_years, gameplay, rules_text)
            VALUES
                (1, 'Surya', 1000, 'USD', 1000, '1:1000', 4, 'intra_day', 'legacy rules');
            """
        )
    connection.close()


def test_database_migrates_legacy_user_profile_schema(tmp_path: Path) -> None:
    db_file = tmp_path / "fincli.db"
    create_legacy_profile_table(db_file)

    db = FinCLIDatabase(db_file)
    profile = UserProfileService(db).get()

    assert profile is not None
    assert profile.name == "Surya"
    assert profile.equity == 1000
    assert profile.currency == "USD"
    assert profile.years_in_investment == 4
    assert profile.gameplay == "Intra day"


def test_profile_command_handles_legacy_profile_without_worker_crash(tmp_path: Path) -> None:
    db_file = tmp_path / "fincli.db"
    create_legacy_profile_table(db_file)
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(db_file))

    result = router.route("/profile")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "Surya" in text
    assert "Intra day" in text


def test_router_turns_unexpected_command_exception_into_error_result(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    def broken_profile(args: list[str]):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")

    router._profile = broken_profile  # type: ignore[method-assign]

    result = router.route("/profile")

    assert result.status == "error"
    assert "Unexpected command error" in render_text(result.renderable)


def test_top_level_registry_commands_do_not_raise_unhandled_exceptions(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    commands = sorted({command.name.split()[0] for command in CommandRegistry().all()})

    for command in commands:
        if command == "/exit":
            continue
        result = router.route(command)
        assert result.status in {"ready", "error"}
