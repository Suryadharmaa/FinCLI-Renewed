from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console

import fincli
from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class CapturingAIProvider:
    name = "capture-ai"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request: AIRequest) -> AIResponse:
        self.prompts.append(request.prompt)
        return AIResponse(
            provider=self.name,
            model=request.model,
            content=(
                "Summary: concise research output.\n"
                "Signal: CAUTION\n"
                "SL: use profile risk cap\n"
                "TP1: nearest resistance\n"
                "TP2: extension level\n"
                "TP3: trend continuation level\n"
                "Reason: data-driven decision."
            ),
        )


class StableMarketProvider:
    name = "stable-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol.upper(),
            price=150.0,
            currency="USD",
            provider=self.name,
            timestamp=datetime(2026, 6, 7, 9, 0),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        candles: list[Candle] = []
        for index in range(140):
            base = 100.0 + index * 0.4
            candles.append(
                Candle(
                    timestamp=datetime(2026, 1, 1, 9, 0),
                    open=base,
                    high=base + 2,
                    low=base - 1,
                    close=base + 1,
                    volume=1_000 + index * 10,
                )
            )
        return candles

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [
            NewsItem(
                title="Company expands margin outlook",
                source="UnitTest News",
                url="https://example.com/news",
                published_at=datetime(2026, 6, 7, 8, 0),
                summary="Analysts cite stronger demand and margin discipline.",
            )
        ][:limit]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(
            symbol=symbol.upper(),
            provider=self.name,
            currency="USD",
            market_cap=1_000_000_000,
            pe_ratio=22.5,
            eps=6.2,
            revenue=50_000_000,
            beta=1.1,
            sector="Technology",
            industry="Software",
        )


def render_text(renderable: object) -> str:
    console = Console(record=True, width=140)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> tuple[CommandRouter, CapturingAIProvider]:
    ai = CapturingAIProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=StableMarketProvider(),
        ai_provider=ai,
    )
    return router, ai


def test_package_metadata_is_v031() -> None:
    assert fincli.__version__ == "1.8.0"


def test_registry_promotes_research_macro_profile_and_documents_advanced_aliases() -> None:
    names = {command.name for command in CommandRegistry().all()}

    assert {"/research", "/macro", "/profile", "/doctor", "/setup"}.issubset(names)
    assert {"/web", "/market", "/technical"}.issubset(names)


def test_research_quick_returns_compact_decision_table(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path)

    result = router.route("/research AAPL --quick")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "Research Brief" in text
    assert "Decision Points" in text
    assert "Final Summary" in text
    assert len(text.splitlines()) < 45


def test_research_deep_sends_concise_workspace_context_to_ai(tmp_path: Path) -> None:
    router, ai = make_router(tmp_path)

    result = router.route("/research AAPL --deep")

    assert result.status == "ready"
    assert ai.prompts
    prompt = ai.prompts[-1]
    assert "FinCLI Research Workspace" in prompt
    assert "Do not copy the opening summary as the final summary" in prompt
    assert "Company expands margin outlook" in prompt


def test_macro_command_returns_offline_fallback_without_api_keys(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path)

    result = router.route("/macro indonesia")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "Macro Dashboard" in text
    assert "Fallback" in text
    assert "Indonesia" in text


def test_profile_is_saved_and_analyze_prompt_uses_gameplay_context(tmp_path: Path) -> None:
    router, ai = make_router(tmp_path)

    save = router.route('/profile set "Budi" 350 IDR 1:100 1.5')
    analyze = router.route("/analyze XAUUSD 1d")

    assert save.status == "ready"
    assert analyze.status == "ready"
    prompt = ai.prompts[-1]
    assert "User Gameplay Profile" in prompt
    assert "Scalper" in prompt
    assert "Signal:" in prompt
    assert "SL:" in prompt
    assert "TP1:" in prompt
    assert "TP2:" in prompt
    assert "TP3:" in prompt
    assert "Reason:" in prompt
