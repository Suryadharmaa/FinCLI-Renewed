from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter, _format_calendar, _format_news_desk
from fincli.app.modules.economic_calendar import EconomicEvent
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.reliability import ProviderResult, classify_provider_error
from fincli.app.services.news_aggregator import NewsDesk
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError, RateLimitError


def render_text(renderable) -> str:
    console = Console(record=True, width=180)
    console.print(renderable)
    return console.export_text()


class PartialMarketProvider:
    name = "partial"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 10.5, "USD", self.name, datetime(2026, 6, 13, 8, 0, 0), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            Candle(datetime(2026, 1, index + 1), 10 + index, 11 + index, 9 + index, 10.5 + index, 1_000)
            for index in range(20)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol.upper(), self.name, "USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="partial provider healthy")


def test_provider_error_classifier_returns_granular_statuses() -> None:
    assert classify_provider_error(RateLimitError("HTTP 429")) == "rate_limited"
    assert classify_provider_error(ProviderError("HTTP 401 unauthorized")) == "auth_failed"
    assert classify_provider_error(ProviderError("HTTP 403 plan entitlement missing")) == "entitlement_missing"
    assert classify_provider_error(ProviderError("empty response")) == "empty_data"


def test_provider_result_contract_is_stable() -> None:
    result = ProviderResult(
        provider="finnhub",
        operation="calendar",
        status="entitlement_missing",
        realtime_label="delayed",
        message="HTTP 403",
        missing_fields=("actual", "estimate"),
    )

    assert result.provider == "finnhub"
    assert result.status == "entitlement_missing"
    assert result.missing_fields == ("actual", "estimate")


def test_market_command_surfaces_partial_data_reliability(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=PartialMarketProvider(),
    )

    result = router.route("/market TEST 1d")

    output = render_text(result.renderable)
    assert "Reliability=partial_data" in output
    assert "Missing=news" in output


def test_provider_status_shows_recent_provider_result(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=PartialMarketProvider(),
    )
    router.route("/market TEST 1d")

    result = router.route("/provider status")

    output = render_text(result.renderable)
    assert "Recent provider results" in output
    assert "partial_data" in output


def test_calendar_output_labels_schedule_only_fallback() -> None:
    table = _format_calendar(
        [
            EconomicEvent(
                time=None,
                country="Global",
                impact="high",
                event="Central bank rate decisions",
                actual=None,
                estimate=None,
                previous=None,
                unit="category",
            )
        ],
        datetime(2026, 6, 13).date(),
        datetime(2026, 6, 20).date(),
        "fallback",
        "Using static macro fallback.",
    )

    output = render_text(table)
    assert "schedule_only" in output


def test_news_output_labels_partial_fallback() -> None:
    desk = NewsDesk(
        symbol="AAPL",
        provider_chain=("bad_provider", "google_news_rss"),
        items=[
            NewsItem(
                title="Apple shares rise on demand outlook",
                source="Google News RSS",
                url="https://example.com",
                published_at=datetime(2026, 6, 13),
                summary="Demand outlook improves.",
            )
        ],
        note="Provider-backed news. Fallback used after 1 provider error(s).",
        errors=("bad_provider: auth_failed",),
        reliability_status="partial_data",
    )

    output = render_text(_format_news_desk(desk))
    assert "Reliability: partial_data" in output
    assert "Errors: 1" in output
