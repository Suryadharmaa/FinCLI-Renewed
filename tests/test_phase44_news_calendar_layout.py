from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.economic_calendar import EconomicEvent, ProviderError
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


class DatedNewsProvider:
    name = "dated-news"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, 100.0, "USD", self.name, datetime.now(), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime.now(), 1, 2, 1, 2, 100)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        now = datetime.now()
        return [
            NewsItem(
                "TSLA recent delivery update",
                "UnitTest Wire",
                "https://example.com/recent-long-url-that-should-not-render-in-table",
                now - timedelta(days=2),
                "Recent delivery data improved.",
            ),
            NewsItem(
                "TSLA stale production story",
                "UnitTest Wire",
                "https://example.com/old",
                now - timedelta(days=15),
                "Old production story.",
            ),
        ][:limit]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol, self.name, "USD")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=DatedNewsProvider(),
    )


def test_news_uses_analysis_column_not_url_column_and_supports_lookback(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/news TSLA 7d")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "Analysis" in text
    assert "URL" not in text
    assert "https://example.com" not in text
    assert "TSLA recent delivery update" in text
    assert "TSLA stale production story" not in text
    assert "Lookback: 7d" in text


def test_news_rejects_lookback_above_30_days(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/news TSLA 31d")

    assert result.status == "error"
    assert "max 30d" in render_text(result.renderable)


def test_calendar_country_filter_keeps_fallback_calendar_when_provider_fails(tmp_path: Path, monkeypatch) -> None:
    from fincli.app.modules.economic_calendar import EconomicCalendarService, PublicEconomicCalendarService

    async def fail_finnhub(self, start, end):
        raise ProviderError("Finnhub economic calendar unavailable.")

    async def fail_public(self, start, end):
        raise ProviderError("Public economic calendar unavailable.")

    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "empty-secrets.env")
    monkeypatch.setattr(
        "fincli.app.cli.router.read_secrets",
        lambda: {"FINNHUB_API_KEY": "bad-key"},
    )
    monkeypatch.setattr(EconomicCalendarService, "events", fail_finnhub)
    monkeypatch.setattr(PublicEconomicCalendarService, "events", fail_public)
    router = make_router(tmp_path)

    result = router.route("/calendar week US high")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "Economic Calendar" in text
    assert "Central bank rate decisions" in text
    assert "Tidak ada event yang cocok" not in text


def test_calendar_static_fallback_message_is_not_raw_http_error(tmp_path: Path, monkeypatch) -> None:
    from fincli.app.modules.economic_calendar import EconomicCalendarService, PublicEconomicCalendarService

    async def fail_finnhub(self, start, end):
        raise ProviderError("Finnhub economic calendar gagal: HTTP 403.")

    async def fail_public(self, start, end):
        raise ProviderError("Public economic calendar gagal: HTTP 429.")

    monkeypatch.setattr(
        "fincli.app.cli.router.read_secrets",
        lambda: {"FINNHUB_API_KEY": "valid-but-calendar-blocked"},
    )
    monkeypatch.setattr(EconomicCalendarService, "events", fail_finnhub)
    monkeypatch.setattr(PublicEconomicCalendarService, "events", fail_public)
    router = make_router(tmp_path)

    result = router.route("/calendar week US high")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "Central bank rate decisions" in text
    assert "HTTP 403" not in text
    assert "HTTP 429" not in text
    assert "static macro fallback" in text


def test_calendar_uses_public_provider_before_static_fallback(tmp_path: Path, monkeypatch) -> None:
    from fincli.app.modules.economic_calendar import EconomicCalendarService, PublicEconomicCalendarService

    async def fail_finnhub(self, start, end):
        raise ProviderError("Finnhub economic calendar gagal: HTTP 401.")

    async def public_events(self, start, end):
        return [
            EconomicEvent(
                "US CPI",
                "US",
                "high",
                datetime(2026, 6, 14, 12, 30),
                estimate="3.1%",
                previous="3.0%",
                unit="public calendar",
            )
        ]

    monkeypatch.setattr(
        "fincli.app.cli.router.read_secrets",
        lambda: {"FINNHUB_API_KEY": "valid-but-no-calendar-entitlement"},
    )
    monkeypatch.setattr(EconomicCalendarService, "events", fail_finnhub)
    monkeypatch.setattr(PublicEconomicCalendarService, "events", public_events)
    router = make_router(tmp_path)

    result = router.route("/calendar week US high")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "US CPI" in text
    assert "public" in text
    assert "Central bank rate decisions" not in text


def test_calendar_shows_value_columns_for_provider_calendar_view(tmp_path: Path, monkeypatch) -> None:
    from fincli.app.modules.economic_calendar import EconomicCalendarService, PublicEconomicCalendarService

    async def fail_finnhub(self, start, end):
        raise ProviderError("Finnhub economic calendar unavailable.")

    async def public_events(self, start, end):
        return [
            EconomicEvent(
                "FOMC Press Release",
                "US",
                "high",
                datetime(2026, 6, 15, 12, 0),
                unit="fred release calendar",
            )
        ]

    monkeypatch.setattr(
        "fincli.app.cli.router.read_secrets",
        lambda: {"FINNHUB_API_KEY": "valid-but-no-calendar-entitlement"},
    )
    monkeypatch.setattr(EconomicCalendarService, "events", fail_finnhub)
    monkeypatch.setattr(PublicEconomicCalendarService, "events", public_events)
    router = make_router(tmp_path)

    result = router.route("/calendar week US high")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "FOMC Press Release" in text
    assert "Actual" in text
    assert "Forecast" in text
    assert "Prev" in text
