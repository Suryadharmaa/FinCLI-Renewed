from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.services.market_overview import build_market_overview
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class OverviewMarketProvider:
    name = "overview"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 150.25, "USD", self.name, datetime(2026, 6, 5, 10, 0, 0), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            Candle(datetime(2026, 1, index + 1), 100 + index, 102 + index, 99 + index, 101 + index, 1_000 + index)
            for index in range(20)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [
            NewsItem("Company raises guidance", "UnitTest News", "https://example.com", datetime(2026, 6, 5), "Positive outlook")
        ]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(
            symbol=symbol.upper(),
            provider=self.name,
            currency="USD",
            market_cap=1_000_000,
            pe_ratio=21.5,
            eps=6.2,
            sector="Technology",
            industry="Software",
        )


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_build_market_overview_includes_data_quality() -> None:
    router = CommandRouter(market_provider=OverviewMarketProvider())

    overview = router._run_async(build_market_overview("AAPL", router.market_service, "1d"))

    assert overview.symbol == "AAPL"
    assert overview.data_quality.score >= 80
    assert overview.quote.price == 150.25
    assert overview.technical.rsi is not None
    assert overview.structure.trend == "bullish"
    assert overview.news
    assert overview.fundamentals is not None


def test_market_command_outputs_professional_overview(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=OverviewMarketProvider(),
    )

    result = router.route("/market AAPL 1d")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "Market Overview: AAPL" in output
    assert "Data Quality" in output
    assert "RSI" in output
    assert "Market Structure" in output
    assert "Company raises guidance" in output
    assert "P/E" in output
