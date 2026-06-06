from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class DashboardMarketProvider:
    name = "dashboard-market"

    async def quote(self, symbol: str) -> Quote:
        prices = {"AAPL": 120.0, "MSFT": 250.0}
        return Quote(symbol.upper(), prices.get(symbol.upper(), 100.0), "USD", self.name, datetime(2026, 6, 5), "delayed")


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=DashboardMarketProvider(),
    )


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_dashboard_command_outputs_compact_professional_summary(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/watchlist add AAPL")
    router.route("/watchlist add MSFT")
    router.route("/tx add buy AAPL 2 100")
    router.journal.add("AAPL", bias="bullish", result="win", emotion="calm", lesson="follow plan", tags="plan")

    result = router.route("/dashboard")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "FinCLI Dashboard" in output
    assert "Provider Chain" in output
    assert "Watchlist" in output
    assert "Portfolio" in output
    assert "Journal" in output
    assert "AAPL" in output
    assert "Unrealized PnL" in output


def test_dashboard_handles_empty_local_data(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/dashboard")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "Watchlist" in output
    assert "0 symbol" in output
    assert "No local portfolio positions" in output
