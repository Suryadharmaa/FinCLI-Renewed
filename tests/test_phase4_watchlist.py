from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class CountingMarketProvider:
    name = "counting"

    def __init__(self) -> None:
        self.quote_calls = 0

    async def quote(self, symbol: str) -> Quote:
        self.quote_calls += 1
        prices = {"AAPL": 120.0, "MSFT": 250.0}
        return Quote(
            symbol=symbol.upper(),
            price=prices[symbol.upper()],
            currency="USD",
            provider=self.name,
            timestamp=datetime(2026, 6, 4, 12, 0, 0),
            status="delayed",
        )


def test_watchlist_view_includes_quote_summary_and_uses_cache(tmp_path: Path) -> None:
    provider = CountingMarketProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=provider,
    )
    router.route("/watchlist add AAPL")
    router.route("/watchlist add MSFT")

    first = router.route("/watchlist")
    second = router.route("/watchlist")

    console = Console(record=True, width=140)
    console.print(first.renderable)
    output = console.export_text()
    assert "Price" in output
    assert "120.0000" in output
    assert "250.0000" in output
    assert second.status == "ready"
    assert provider.quote_calls == 2
