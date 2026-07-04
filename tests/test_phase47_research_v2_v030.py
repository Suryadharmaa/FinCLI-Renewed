from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


class ResearchAI:
    name = "research-ai"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request: AIRequest) -> AIResponse:
        self.prompts.append(request.prompt)
        return AIResponse(
            provider=self.name,
            model=request.model,
            content="Snapshot: strong trend with defined risk.\nSignal: CAUTION\nRisk: wait for confirmation.",
        )


class ResearchProvider:
    name = "research-provider"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 150.0, "USD", self.name, datetime(2026, 6, 13, 9, 0), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        candles: list[Candle] = []
        for index in range(140):
            close = 100 + index * 0.5
            candles.append(Candle(datetime(2026, 1, 1), close - 1, close + 2, close - 2, close, 5_000 + index))
        return candles

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [NewsItem("Company raises outlook", "UnitTest", "https://example.com", datetime(2026, 6, 13), "Bullish context")]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol.upper(), self.name, "USD", pe_ratio=20.0, eps=5.0, sector="Technology")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=150)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> tuple[CommandRouter, ResearchAI]:
    ai = ResearchAI()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ResearchProvider(),
        ai_provider=ai,
    )
    return router, ai


def test_research_quick_uses_v2_compact_sections(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path)

    result = router.route("/research AAPL")

    output = render_text(result.renderable)
    assert "Research Center: AAPL | snapshot" in output
    assert "Snapshot" in output
    assert "Signal" in output
    assert "Risk" in output
    assert "Missing Data" in output
    assert "Source Quality" in output
    assert len(output.splitlines()) < 50


def test_research_deep_prompt_mentions_v2_contract(tmp_path: Path) -> None:
    router, ai = make_router(tmp_path)

    result = router.route("/research AAPL --deep")

    output = render_text(result.renderable)
    assert "AI Summary" in output
    assert ai.prompts
    assert "Research Engine v3" in ai.prompts[-1]
    assert "snapshot, signal, risk, missing data, source quality" in ai.prompts[-1]


def test_research_report_mode_returns_report_oriented_output(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path)

    result = router.route("/research AAPL --report")

    output = render_text(result.renderable)
    assert "Research Center: AAPL | report" in output
    assert "Report Notes" in output
    assert "Not financial advice" in output

