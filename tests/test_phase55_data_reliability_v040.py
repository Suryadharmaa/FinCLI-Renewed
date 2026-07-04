from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import (
    BaseMarketProvider,
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderStatus,
    Quote,
)
from fincli.app.services.market_data import MarketDataService


class SlowProvider(BaseMarketProvider):
    name = "slow"

    async def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, realtime=False, status="ok", message="slow")

    async def quote(self, symbol: str) -> Quote:
        await asyncio.sleep(0.2)
        return Quote(symbol=symbol, price=1, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return []

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol, provider=self.name, currency="USD")


class FastProvider(SlowProvider):
    name = "fast"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol, price=2, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="delayed")


def _render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_market_service_timeout_budget_falls_back_to_next_provider() -> None:
    service = MarketDataService([SlowProvider(), FastProvider()], provider_timeout_seconds=0.05)

    quote = asyncio.run(service.quote("AAPL"))

    assert quote.provider == "fast"
    statuses = [(item.provider, item.status) for item in service.provider_results]
    assert ("slow", "network_error") in statuses
    assert ("fast", "ok") in statuses


def test_news_and_calendar_outputs_show_standard_data_quality(tmp_path, monkeypatch) -> None:
    from fincli.app.storage.database import FinCLIDatabase
    from tests.test_phase54_doctor_full_and_registry_smoke_v040 import (
        SmokeAIProvider,
        SmokeMarketProvider,
        SmokeWebResearch,
    )

    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    router = CommandRouter(db=FinCLIDatabase(tmp_path / "fincli.db"), market_provider=SmokeMarketProvider(), ai_provider=SmokeAIProvider())
    router.web_research = SmokeWebResearch()

    news = _render_text(router.route("/news AAPL").renderable)
    calendar = _render_text(router.route("/calendar week US high").renderable)

    assert "Data Quality:" in news
    assert "Data Quality:" in calendar
    assert "missing=" in news
    assert "missing=" in calendar
