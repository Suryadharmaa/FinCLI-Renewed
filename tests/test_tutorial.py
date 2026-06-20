"""Tests for the /tutorial command."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_tutorial_menu_shows_all_lessons(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial").renderable)
    assert "Tutorial" in output
    assert "Welcome" in output
    assert "Market Data" in output
    assert "Technical" in output
    assert "Portfolio" in output
    assert "Trading" in output
    assert "Alerts" in output
    assert "Export" in output


def test_tutorial_lesson_1(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 1").renderable)
    assert "Welcome" in output
    assert "/profile set" in output
    assert "/doctor" in output


def test_tutorial_lesson_2(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 2").renderable)
    assert "Market Data" in output
    assert "/market" in output
    assert "/research" in output


def test_tutorial_lesson_3(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 3").renderable)
    assert "Technical" in output
    assert "/technical" in output
    assert "/mtf" in output


def test_tutorial_lesson_4(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 4").renderable)
    assert "Portfolio" in output
    assert "/portfolio add" in output
    assert "/portfolio risk" in output


def test_tutorial_lesson_5(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 5").renderable)
    assert "Paper Trading" in output
    assert "/trading paper" in output


def test_tutorial_lesson_6(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 6").renderable)
    assert "Alerts" in output
    assert "/alert add" in output
    assert "/watchlist add" in output


def test_tutorial_lesson_7(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 7").renderable)
    assert "Export" in output
    assert "/backtest" in output
    assert "/export" in output


def test_tutorial_next_advances_lessons(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output1 = render_text(router.route("/tutorial next").renderable)
    assert "1/7" in output1 or "Welcome" in output1
    output2 = render_text(router.route("/tutorial next").renderable)
    assert "2/7" in output2 or "Market Data" in output2


def test_tutorial_reset_resets_progress(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/tutorial next")
    router.route("/tutorial next")
    output = render_text(router.route("/tutorial reset").renderable)
    assert "reset" in output.lower()


def test_tutorial_keyword_aliases(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial market").renderable)
    assert "Market Data" in output
    output = render_text(router.route("/tutorial trading").renderable)
    assert "Paper Trading" in output


def test_tutorial_tip_shown(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    output = render_text(router.route("/tutorial 1").renderable)
    assert "Tip" in output
