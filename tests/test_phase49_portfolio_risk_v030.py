from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.portfolio_risk import build_portfolio_risk
from fincli.app.providers.market.base import ProviderStatus, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


class PortfolioRiskProvider:
    name = "portfolio-risk"

    async def quote(self, symbol: str) -> Quote:
        prices = {"AAPL": 150.0, "MSFT": 110.0, "BTC-USD": 20_000.0, "EURUSD=X": 1.1}
        return Quote(symbol.upper(), prices.get(symbol.upper(), 100.0), "USD", self.name, datetime(2026, 6, 13), "delayed")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_portfolio_risk_engine_calculates_exposure_concentration_and_health() -> None:
    positions = [
        {"symbol": "AAPL", "quantity": 10, "average_price": 100, "currency": "USD"},
        {"symbol": "BTC-USD", "quantity": 0.1, "average_price": 30_000, "currency": "USD"},
    ]
    values = {"AAPL": (150.0, 500.0, 50.0), "BTC-USD": (20_000.0, -1_000.0, -33.333)}

    report = build_portfolio_risk(positions, values, realized_pnl=250.0)

    assert report.total_market_value == 3500.0
    assert report.unrealized_pnl == -500.0
    assert report.realized_pnl == 250.0
    assert report.total_pnl == -250.0
    assert report.exposure_by_asset_class["crypto"].market_value == 2000.0
    assert report.concentration.top_symbol == "BTC-USD"
    assert report.concentration.top_weight > 50
    assert report.health.score < 90


def test_portfolio_risk_command_outputs_v2_sections(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=PortfolioRiskProvider(),
    )
    router.route("/portfolio add AAPL 10 100")
    router.route("/portfolio add BTC-USD 0.1 30000")
    router.route("/tx add sell AAPL 2 120")

    result = router.route("/portfolio risk")

    output = render_text(result.renderable)
    assert "Portfolio Risk v2" in output
    assert "Health Score" in output
    assert "Exposure by Asset Class" in output
    assert "Concentration Risk" in output
    assert "Realized PnL" in output
    assert "Unrealized PnL" in output

