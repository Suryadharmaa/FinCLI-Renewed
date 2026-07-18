from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.provider_metrics import ProviderMetricsStore
from fincli.app.utils.errors import ProviderError

if TYPE_CHECKING:
    from pathlib import Path


class CapturingAI:
    name = "capturing-ai"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request: AIRequest) -> AIResponse:
        self.prompts.append(request.prompt)
        return AIResponse(provider=self.name, model=request.model, content="Signal: CAUTION\nReason: grounded.")


class GroundingProvider:
    name = "grounding-provider"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 100.0, "USD", self.name, datetime(2026, 6, 14), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            Candle(datetime(2026, 1, index + 1), 90 + index, 92 + index, 88 + index, 91 + index, 1_000 + index)
            for index in range(30)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        raise ProviderError("fundamentals unavailable")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


class PersistentFailingProvider:
    name = "persist_fail"

    async def quote(self, symbol: str) -> Quote:
        raise ProviderError("HTTP 429 rate limit")


class PersistentWorkingProvider:
    name = "persist_work"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 42.0, "USD", self.name, datetime(2026, 6, 14), "delayed")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_analyze_prompt_includes_grounding_guard_context(tmp_path: Path) -> None:
    ai = CapturingAI()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=GroundingProvider(),
        ai_provider=ai,
    )
    router.route("/market AAPL 1d")

    result = router.route("/analyze AAPL 1d")

    assert result.status == "ready"
    prompt = ai.prompts[-1]
    assert "Trust:" in prompt
    assert "Data Quality:" in prompt
    assert "Provider Reliability:" in prompt
    assert "Missing Data:" in prompt
    assert "Data Trust Gate:" in prompt
    assert "Provider Metrics:" in prompt


def test_provider_metrics_persist_to_sqlite_across_services(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    store = ProviderMetricsStore(db)
    service = MarketDataService([PersistentFailingProvider(), PersistentWorkingProvider()], metrics_store=store)

    quote = service.run(service.quote("AAPL"))
    snapshot = ProviderMetricsStore(db).snapshot()

    assert quote.provider == "persist_work"
    assert snapshot["persist_fail"].calls == 1
    assert snapshot["persist_fail"].errors == 1
    assert snapshot["persist_fail"].fallbacks == 1
    assert snapshot["persist_work"].calls == 1
    assert snapshot["persist_work"].successes == 1


def test_provider_metrics_command_shows_persistent_totals(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=GroundingProvider(),
        ai_provider=CapturingAI(),
    )
    router.market_service = MarketDataService(
        [PersistentFailingProvider(), PersistentWorkingProvider()],
        metrics_store=ProviderMetricsStore(router.db),
    )
    router.route("/provider test AAPL")

    result = router.route("/provider metrics")

    output = render_text(result.renderable)
    assert "Session Calls" in output
    assert "All-Time Calls" in output
    assert "persist_fail" in output
    assert "persist_work" in output

