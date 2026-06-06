from pathlib import Path

from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_router(tmp_path: Path) -> CommandRouter:
    config = ConfigManager(tmp_path / "config.json")
    db = FinCLIDatabase(tmp_path / "fincli.db")
    return CommandRouter(config=config, db=db)


def test_registry_suggests_slash_commands() -> None:
    registry = CommandRegistry()
    suggestions = registry.suggest("/wat")
    assert suggestions
    assert suggestions[0].name.startswith("/watchlist")


def test_router_handles_unknown_command(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    result = router.route("/missing")
    assert result.status == "error"


def test_watchlist_add_and_list(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    add_result = router.route("/watchlist add AAPL")
    list_result = router.route("/watchlist")
    assert add_result.status == "ready"
    assert list_result.status == "ready"
    rows = router.watchlist.list()
    assert rows[0]["symbol"] == "AAPL"


def test_portfolio_add_and_list(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/portfolio add BTC-USD 0.05 65000")
    rows = router.portfolio.list()
    assert rows[0]["symbol"] == "BTC-USD"
    assert rows[0]["quantity"] == 0.05
