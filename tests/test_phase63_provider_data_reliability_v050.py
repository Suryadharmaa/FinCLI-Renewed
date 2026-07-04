from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.reliability import (
    GRANULAR_STATUSES,
    STATUS_DELAYED,
    STATUS_FALLBACK,
    result_style,
)
from fincli.app.services.source_quality import score_source_quality
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


class ReliabilityProvider:
    name = "reliability-provider"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 150.0, "USD", self.name, datetime(2026, 6, 13), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime(2026, 1, index + 1), 100, 102, 99, 101, 1_000) for index in range(30)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol.upper(), self.name, "USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_delayed_and_fallback_statuses_are_registered() -> None:
    assert STATUS_DELAYED == "delayed"
    assert STATUS_FALLBACK == "fallback"
    assert STATUS_DELAYED in GRANULAR_STATUSES
    assert STATUS_FALLBACK in GRANULAR_STATUSES
    # Degraded-but-usable statuses render as a warning style, not a hard error.
    assert result_style(STATUS_DELAYED) == "yellow"
    assert result_style(STATUS_FALLBACK) == "yellow"


def test_source_quality_scores_realtime_fresh_data_higher_than_stale() -> None:
    now = datetime.now(UTC)
    realtime_quote = Quote("AAPL", 150.0, "USD", "live", now, "realtime")
    candles = [Candle(now, 100, 102, 99, 101, 1_000) for _ in range(150)]
    fresh_news = [NewsItem("Fresh headline", "Wire", "https://example.com", now - timedelta(hours=2), "ctx")]
    fundamentals = FundamentalSnapshot("AAPL", "live", "USD", pe_ratio=20.0, sector="Technology")

    strong = score_source_quality(realtime_quote, candles, fresh_news, fundamentals)

    stale_quote = Quote("AAPL", 150.0, "USD", "yf", now, "delayed")
    stale = score_source_quality(stale_quote, candles[:5], [], None)

    assert strong.freshness_score > stale.freshness_score
    assert strong.source_grade == "A"
    assert strong.realtime_label == "ok"
    assert stale.realtime_label == STATUS_DELAYED
    assert "freshness=" in strong.compact()


def test_provider_capabilities_command_renders_matrix(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ReliabilityProvider(),
    )

    output = render_text(router.route("/provider capabilities").renderable)

    assert "Command Capability Matrix" in output
    assert "/research" in output
    assert "command profile" in output


def test_market_overview_includes_source_quality_row(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ReliabilityProvider(),
    )

    output = render_text(router.route("/market AAPL 1d").renderable)

    assert "Source Quality" in output
    assert "grade=" in output
