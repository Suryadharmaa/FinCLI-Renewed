"""Focused tests for the v1.8.4 provider trust command."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse, BaseAIProvider
from fincli.app.providers.market.base import (
    BaseMarketProvider,
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


class TrustMarketProvider(BaseMarketProvider):
    name = "trust_test"
    realtime = False

    def __init__(self, price: float | None = 100.0) -> None:
        self.price = price

    async def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, realtime=False, status="ok", message="ready")

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol.upper(),
            price=self.price,
            currency="USD",
            provider=self.name,
            timestamp=datetime.now(UTC),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        now = datetime.now(UTC)
        return [
            Candle(timestamp=now, open=100.0, high=101.0, low=99.0, close=100.0, volume=10_000.0)
            for _ in range(10)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [NewsItem(title=f"{symbol} news", source=self.name, url=None, published_at=datetime.now(UTC))]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD", market_cap=1_000_000)

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=False,
            operations=("quote", "history", "news", "fundamentals"),
            asset_classes=("stock",),
        )


class TrustAIProvider(BaseAIProvider):
    name = "trust_ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(content="trust ai", provider=self.name, model=request.model)


def _router(tmp_path: Path, provider: TrustMarketProvider | None = None) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=provider or TrustMarketProvider(),
        ai_provider=TrustAIProvider(),
    )


def _render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_provider_trust_without_calls_renders_not_enough_data(tmp_path: Path) -> None:
    router = _router(tmp_path)

    output = _render_text(router.route("/provider trust").renderable)

    assert "Limited" in output
    assert "not enough data" in output.lower()
    assert "AI Confidence Limit" in output


def test_provider_trust_healthy_chain_renders_strong(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.route("/provider test AAPL")

    output = _render_text(router.route("/provider trust").renderable)

    assert "Strong" in output
    assert "trust_test/quote" in output
    assert "80%" in output


def test_provider_trust_degraded_metrics_lower_trust_level(tmp_path: Path) -> None:
    router = _router(tmp_path)
    router.route("/provider test AAPL")
    metric = router.market_service.provider_metrics["trust_test"]
    metric.record(success=False, latency_ms=2_000.0, fallback=True)
    metric.record(success=False, latency_ms=2_500.0, fallback=True)
    metric.consecutive_failures = 2

    output = _render_text(router.route("/provider trust").renderable)

    assert "Limited" in output
    assert "fallback" in output.lower()
    assert "45%" in output


def test_provider_trust_missing_quote_price_blocks_directional_trust(tmp_path: Path) -> None:
    router = _router(tmp_path, TrustMarketProvider(price=None))
    router.route("/provider test AAPL")

    output = _render_text(router.route("/provider trust").renderable)

    assert "Blocked" in output
    assert "price" in output
    assert "20%" in output
