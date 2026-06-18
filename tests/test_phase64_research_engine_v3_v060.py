from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.services.web_research import WebSearchResult
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class ResearchAI:
    name = "research-ai"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, request: AIRequest) -> AIResponse:
        self.prompts.append(request.prompt)
        return AIResponse(provider=self.name, model=request.model, content="Signal: CAUTION. Grounded in cited sources.")


class NewsProvider:
    name = "news-provider"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 150.0, "USD", self.name, datetime(2026, 6, 13, 9, 0), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime(2026, 1, 1), 100 + index * 0.5, 102 + index, 99 + index, 101 + index * 0.5, 1_000 + index) for index in range(140)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [NewsItem("Company raises outlook", "UnitTest", "https://example.com", datetime(2026, 6, 13), "Bullish")]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol.upper(), self.name, "USD", pe_ratio=20.0, eps=5.0, sector="Technology")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


class NoNewsProvider(NewsProvider):
    name = "no-news-provider"

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []


class FakeWebResearch:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        self.queries.append(query)
        return [WebSearchResult("Macro context headline", "https://news.example/web", "Public web snippet")]


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path, provider: object) -> tuple[CommandRouter, ResearchAI]:
    ai = ResearchAI()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=provider,
        ai_provider=ai,
    )
    return router, ai


def test_research_default_mode_is_snapshot_with_context_and_sources(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path, NewsProvider())

    output = render_text(router.route("/research AAPL").renderable)

    assert "Research Center: AAPL | snapshot | Research Brief v3" in output
    assert "Context" in output
    assert "Sources" in output
    assert "Technology" in output  # sector blended into context


def test_research_deep_prompt_is_v3_and_cites_sources(tmp_path: Path) -> None:
    router, ai = make_router(tmp_path, NewsProvider())

    render_text(router.route("/research AAPL --deep").renderable)

    assert ai.prompts
    prompt = ai.prompts[-1]
    assert "Research Engine v3" in prompt
    assert "Cited Sources:" in prompt
    assert "Context Blend:" in prompt


def test_research_falls_back_to_web_when_no_provider_news(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path, NoNewsProvider())
    web = FakeWebResearch()
    router.web_research = web

    output = render_text(router.route("/research AAPL --deep").renderable)

    assert web.queries  # web fallback was triggered
    assert "[web]" in output


def test_research_report_export_json_includes_sources_and_context(tmp_path: Path) -> None:
    router, _ = make_router(tmp_path, NewsProvider())
    target = tmp_path / "research.json"

    router.route(f"/research AAPL --report --export json {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))

    assert payload["mode"] == "report"
    assert payload["engine"] == "Research Engine v3"
    assert payload["sources"]
    assert payload["context_blend"]
    assert "source_quality" in payload
