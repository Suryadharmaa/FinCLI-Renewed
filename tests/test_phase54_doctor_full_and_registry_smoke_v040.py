from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse, BaseAIProvider
from fincli.app.providers.market.base import BaseMarketProvider, Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.services.web_research import WebSearchResult
from fincli.app.storage.database import FinCLIDatabase


class SmokeMarketProvider(BaseMarketProvider):
    name = "smoke"
    realtime = False

    async def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, realtime=False, status="ok", message="smoke provider ready")

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol.upper(), price=100.0, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        now = datetime.now(UTC)
        return [
            Candle(timestamp=now, open=95 + index, high=101 + index, low=94 + index, close=100 + index, volume=10_000 + index)
            for index in range(90)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{symbol.upper()} smoke news",
                source="smoke",
                url="https://example.com/news",
                published_at=datetime.now(UTC),
                summary="Smoke news summary",
            )
        ][:limit]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(
            symbol=symbol.upper(),
            provider=self.name,
            currency="USD",
            market_cap=1_000_000,
            pe_ratio=12.5,
            eps=2.1,
            revenue=500_000,
            sector="Technology",
            industry="Software",
        )


class SmokeAIProvider(BaseAIProvider):
    name = "smoke-ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(content="Smoke AI response", provider=self.name, model=request.model)


class SmokeWebResearch:
    async def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        return [WebSearchResult(title="Smoke source", url="https://example.com", snippet=query)]

    async def research(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        return [WebSearchResult(title="Smoke source", url="https://example.com", snippet=query, content="Smoke context")]


def _render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path, monkeypatch) -> CommandRouter:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    router = CommandRouter(db=FinCLIDatabase(tmp_path / "fincli.db"), market_provider=SmokeMarketProvider(), ai_provider=SmokeAIProvider())
    router.web_research = SmokeWebResearch()
    return router


def test_doctor_full_reports_provider_data_and_command_coverage(tmp_path: Path, monkeypatch) -> None:
    router = make_router(tmp_path, monkeypatch)

    result = router.route("/doctor full")
    text = _render_text(result.renderable)

    assert result.status == "ready"
    assert "FinCLI Doctor Full" in text
    assert "Database Schema" in text
    assert "Market Cache" in text
    assert "Provider:smoke" in text
    assert "Command Coverage" in text
    assert "Capability Matrix" in text
    assert "Capability:/research" in text


def test_doctor_full_live_runs_optional_quote_check(tmp_path: Path, monkeypatch) -> None:
    router = make_router(tmp_path, monkeypatch)

    result = router.route("/doctor full --live MSFT")
    text = _render_text(result.renderable)

    assert result.status == "ready"
    assert "Live Quote Test" in text
    assert "MSFT" in text


def test_registry_commands_have_local_smoke_coverage(tmp_path: Path, monkeypatch) -> None:
    router = make_router(tmp_path, monkeypatch)
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    commands = _smoke_commands(router, export_dir)
    registry_names = {command.name for command in CommandRegistry().all()}

    assert registry_names == set(commands)

    failures: list[str] = []
    for name, raw in commands.items():
        if name in {"/ai", "/analyze", "/journal review"}:
            router.ai_provider = SmokeAIProvider()
        if name in {"/scan", "/scan export"}:
            router.route("/watchlist add AAPL")
        result = router.route(raw)
        if name == "/ai_model key":
            router.ai_provider = SmokeAIProvider()
        if result.status == "error":
            failures.append(f"{name} -> {raw} returned error: {_render_text(result.renderable)}")

    assert not failures, "\n".join(failures)


def _smoke_commands(router: CommandRouter, export_dir: Path) -> dict[str, str]:
    return {
        "/help": "/help",
        "/dashboard": "/dashboard",
        "/ai_model": "/ai_model",
        "/ai_model key": "/ai_model key groq smoke-key",
        "/news_model": "/news_model",
        "/news_model list": "/news_model list",
        "/news_model search": "/news_model search rss",
        "/news_model use": "/news_model use google_news_rss",
        "/news_model priority": "/news_model priority google_news_rss,yfinance",
        "/news_model key": "/news_model key marketaux smoke-key",
        "/symbol": "/symbol XAUUSD",
        "/symbol resolve": "/symbol resolve XAUUSD --asset commodity",
        "/research": "/research AAPL",
        "/macro": "/macro Indonesia",
        "/profile": "/profile",
        "/profile set": '/profile set "Smoke User" 500 USD 1:100 2',
        "/doctor": "/doctor full",
        "/setup": "/setup",
        "/secrets status": "/secrets status",
        "/secrets clear": "/secrets clear",
        "/privacy status": "/privacy status",
        "/privacy purge": "/privacy purge",
        "/agent": "/agent list",
        "/agent show": "/agent show buffett",
        "/connector": "/connector list macro",
        "/connector search": "/connector search yahoo",
        "/plugin": "/plugin list",
        "/plugin status": "/plugin status",
        "/market": "/market AAPL 1d",
        "/quote": "/quote AAPL",
        "/news": "/news AAPL",
        "/technical": "/technical AAPL 1d",
        "/structure": "/structure AAPL 1d",
        "/mtf": "/mtf AAPL 1d,1h",
        "/backtest": "/backtest AAPL sma_cross 1d",
        "/trading": "/trading",
        "/yahoo": "/yahoo AAPL statistics",
        "/funda": "/funda AAPL",
        "/web": "/web sources market risk",
        "/ai": "/ai ringkas risiko AAPL",
        "/analyze": "/analyze AAPL 1d",
        "/watchlist": "/watchlist",
        "/watchlist add": "/watchlist add AAPL",
        "/watchlist remove": "/watchlist remove AAPL",
        "/portfolio": "/portfolio",
        "/portfolio add": "/portfolio add AAPL 10 100",
        "/portfolio remove": "/portfolio remove AAPL",
        "/portfolio performance": "/portfolio performance",
        "/portfolio risk": "/portfolio risk",
        "/tx": "/tx list",
        "/tx add": "/tx add buy AAPL 10 100",
        "/journal": "/journal",
        "/journal add": '/journal add AAPL bullish "Smoke journal"',
        "/journal stats": "/journal stats",
        "/journal review": "/journal review",
        "/alert": "/alert",
        "/alert add": "/alert add AAPL above 120 smoke",
        "/alert check": "/alert check",
        "/history": "/history",
        "/history sessions": "/history sessions",
        "/history show": f"/history show {router.session_id}",
        "/history save": '/history save "Smoke Session"',
        "/history delete": f"/history delete {router.session_id}",
        "/config": "/config",
        "/scan": "/scan watchlist trend=bullish",
        "/scan export": f"/scan export csv {export_dir / 'scan.csv'} trend=bullish 1d",
        "/report market": f"/report market AAPL md {export_dir / 'market.md'} 1d",
        "/calendar": "/calendar week US high",
        "/calendar export": f"/calendar export csv {export_dir / 'calendar.csv'} week US high",
        "/provider status": "/provider status",
        "/provider metrics": "/provider metrics",
        "/provider list": "/provider list",
        "/provider entitlement": "/provider entitlement",
        "/provider test": "/provider test AAPL",
        "/provider key status": "/provider key status",
        "/cache stats": "/cache stats",
        "/cache clear": "/cache clear",
        "/export journal": f"/export journal csv {export_dir / 'journal.csv'}",
        "/export portfolio": f"/export portfolio json {export_dir / 'portfolio.json'}",
        "/clear": "/clear",
        "/exit": "/exit",
    }
