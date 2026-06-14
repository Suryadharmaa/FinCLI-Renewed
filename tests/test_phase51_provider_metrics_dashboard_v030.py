from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import ProviderStatus, Quote
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError


class FailingQuoteProvider:
    name = "failing"

    async def quote(self, symbol: str) -> Quote:
        raise ProviderError("HTTP 429 rate limit")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="rate_limited", message="rate limit")


class WorkingQuoteProvider:
    name = "working"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 123.0, "USD", self.name, datetime(2026, 6, 13), "delayed")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=180)
    console.print(renderable)
    return console.export_text()


def test_market_data_service_tracks_provider_metrics_for_fallback() -> None:
    service = MarketDataService([FailingQuoteProvider(), WorkingQuoteProvider()])

    quote = service.run(service.quote("AAPL"))
    metrics = service.provider_metrics_snapshot()

    assert quote.provider == "working"
    assert metrics["failing"].calls == 1
    assert metrics["failing"].errors == 1
    assert metrics["failing"].fallbacks == 1
    assert metrics["failing"].success_rate == 0.0
    assert metrics["working"].calls == 1
    assert metrics["working"].successes == 1
    assert metrics["working"].success_rate == 100.0
    assert metrics["working"].avg_latency_ms >= 0.0


def test_provider_metrics_command_outputs_dashboard_rows(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=WorkingQuoteProvider(),
    )
    router.market_service = MarketDataService([FailingQuoteProvider(), WorkingQuoteProvider()])
    router.route("/provider test AAPL")

    result = router.route("/provider metrics")

    output = render_text(result.renderable)
    assert "Provider Metrics Dashboard" in output
    assert "Success Rate" in output
    assert "Avg Latency" in output
    assert "Fallback Count" in output
    assert "Error Count" in output
    assert "failing" in output
    assert "working" in output

