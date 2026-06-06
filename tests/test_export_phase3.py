from datetime import datetime
from pathlib import Path

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


def make_router(tmp_path: Path) -> CommandRouter:
    config = ConfigManager(tmp_path / "config.json")
    db = FinCLIDatabase(tmp_path / "fincli.db")
    return CommandRouter(config=config, db=db, market_provider=FakeMarketProvider())


def test_export_portfolio_json_writes_file(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    target = tmp_path / "portfolio.json"
    router.route("/portfolio add AAPL 2 100")

    result = router.route(f"/export portfolio json {target}")

    assert result.status == "ready"
    assert target.exists()
    assert '"symbol": "AAPL"' in target.read_text(encoding="utf-8")


def test_export_journal_csv_writes_file(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    target = tmp_path / "journal.csv"
    router.route('/journal add AAPL bullish "Breakout setup"')

    result = router.route(f"/export journal csv {target}")

    assert result.status == "ready"
    content = target.read_text(encoding="utf-8")
    assert "instrument,bias" in content
    assert "AAPL,bullish" in content
