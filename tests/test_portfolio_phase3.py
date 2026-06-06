from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class FakeMarketProvider:
    name = "fake-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol.upper(),
            price=120.0,
            currency="USD",
            provider=self.name,
            timestamp=datetime(2026, 6, 4, 12, 0, 0),
            status="delayed",
        )


def test_portfolio_view_includes_current_price_and_pnl(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeMarketProvider(),
    )
    router.route("/portfolio add AAPL 2 100")

    result = router.route("/portfolio")

    console = Console(record=True, width=140)
    console.print(result.renderable)
    output = console.export_text()
    assert "Current" in output
    assert "PnL" in output
    assert "40.0000" in output
