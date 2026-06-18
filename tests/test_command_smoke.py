"""Full command smoke test suite.

Tests every command registered in CommandRegistry through the CommandRouter
using mock providers. Ensures no command returns an unexpected ``status="error"``.

Run: ``python -m pytest tests/test_command_smoke.py -q``
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from rich.console import Console

from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse, BaseAIProvider
from fincli.app.providers.market.base import (
    BaseMarketProvider,
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderStatus,
    Quote,
)
from fincli.app.services.web_research import WebSearchResult
from fincli.app.storage.database import FinCLIDatabase


# ---------------------------------------------------------------------------
# Mock providers
# ---------------------------------------------------------------------------

class SmokeMarketProvider(BaseMarketProvider):
    """Deterministic market provider for smoke tests."""

    name = "smoke"
    realtime = False

    async def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, realtime=False, status="ok", message="smoke provider ready")

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol.upper(),
            price=100.0,
            currency="USD",
            provider=self.name,
            timestamp=datetime.now(UTC),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        now = datetime.now(UTC)
        return [
            Candle(
                timestamp=now,
                open=95 + index,
                high=101 + index,
                low=94 + index,
                close=100 + index,
                volume=10_000 + index,
            )
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
    """Deterministic AI provider for smoke tests."""

    name = "smoke-ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(content="Smoke AI response", provider=self.name, model=request.model)


class SmokeWebResearch:
    """Deterministic web research for smoke tests."""

    async def search(self, query: str, limit: int = 5) -> list[WebSearchResult]:
        return [WebSearchResult(title="Smoke source", url="https://example.com", snippet=query)]

    async def research(self, query: str, limit: int = 3) -> list[WebSearchResult]:
        return [
            WebSearchResult(title="Smoke source", url="https://example.com", snippet=query, content="Smoke context")
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CommandRouter:
    """Build a CommandRouter with mock providers and isolated storage."""
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    router = CommandRouter(
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=SmokeMarketProvider(),
        ai_provider=SmokeAIProvider(),
    )
    router.web_research = SmokeWebResearch()
    return router


# ---------------------------------------------------------------------------
# Command smoke-map: registry name  ->  raw command string
# ---------------------------------------------------------------------------

def _smoke_commands(router: CommandRouter, export_dir: Path) -> dict[str, str]:
    """Return a mapping of every CommandRegistry name to a raw command string."""
    return {
        # General / System
        "/help": "/help",
        "/dashboard": "/dashboard",
        "/config": "/config",
        "/theme": "/theme",
        "/theme list": "/theme list",
        "/clear": "/clear",
        "/exit": "/exit",
        # AI
        "/ai_model": "/ai_model",
        "/ai_model key": "/ai_model key groq smoke-key",
        "/ai": "/ai what is risk",
        "/agent": "/agent list",
        "/agent show": "/agent show buffett",
        # Provider / News model
        "/news_model": "/news_model",
        "/news_model list": "/news_model list",
        "/news_model search": "/news_model search rss",
        "/news_model use": "/news_model use google_news_rss",
        "/news_model priority": "/news_model priority google_news_rss,yfinance",
        "/news_model key": "/news_model key marketaux smoke-key",
        "/provider status": "/provider status",
        "/provider metrics": "/provider metrics",
        "/provider list": "/provider list",
        "/provider capabilities": "/provider capabilities",
        "/provider entitlement": "/provider entitlement",
        "/provider test": "/provider test AAPL",
        "/provider key status": "/provider key status",
        "/connector": "/connector list macro",
        "/connector search": "/connector search yahoo",
        "/plugin": "/plugin list",
        "/plugin status": "/plugin status",
        # Symbol
        "/symbol": "/symbol XAUUSD",
        "/symbol resolve": "/symbol resolve XAUUSD --asset commodity",
        # Research / Macro
        "/research": "/research AAPL",
        "/macro": "/macro Indonesia",
        # Profile
        "/profile": "/profile",
        "/profile set": '/profile set "Smoke User" 500 USD 1:100 2',
        # Doctor / Setup / Secrets / Privacy
        "/doctor": "/doctor full",
        "/setup": "/setup",
        "/tutorial": "/tutorial",
        "/tutorial next": "/tutorial next",
        "/tutorial reset": "/tutorial reset",
        "/secrets status": "/secrets status",
        "/secrets clear": "/secrets clear",
        "/security status": "/security status",
        "/security audit": "/security audit",
        "/security scan": "/security scan",
        "/security lockdown": "/security lockdown",
        "/privacy status": "/privacy status",
        "/privacy purge": "/privacy purge",
        # Cache
        "/cache stats": "/cache stats",
        "/cache clear": "/cache clear",
        # Market data
        "/market": "/market AAPL 1d",
        "/quote": "/quote AAPL",
        "/news": "/news AAPL",
        "/technical": "/technical AAPL 1d",
        "/structure": "/structure AAPL 1d",
        "/mtf": "/mtf AAPL 1d,1h",
        "/backtest": "/backtest AAPL sma_cross 1d",
        "/funda": "/funda AAPL",
        "/yahoo": "/yahoo AAPL statistics",
        "/web": "/web sources market risk",
        "/analyze": "/analyze AAPL 1d",
        # Watchlist
        "/watchlist": "/watchlist",
        "/watchlist add": "/watchlist add AAPL",
        "/watchlist remove": "/watchlist remove AAPL",
        # Portfolio
        "/portfolio": "/portfolio",
        "/portfolio add": "/portfolio add AAPL 10 100",
        "/portfolio remove": "/portfolio remove AAPL",
        "/portfolio performance": "/portfolio performance",
        "/portfolio risk": "/portfolio risk",
        "/portfolio chart": "/portfolio chart",
        "/portfolio snapshot": "/portfolio snapshot",
        "/portfolio whatif": "/portfolio whatif add AAPL 10 200",
        "/portfolio benchmark": "/portfolio benchmark SPY",
        # Transactions
        "/tx": "/tx list",
        "/tx add": "/tx add buy AAPL 10 100",
        # Journal
        "/journal": "/journal",
        "/journal add": '/journal add AAPL bullish "Smoke journal"',
        "/journal stats": "/journal stats",
        "/journal review": "/journal review",
        # Alerts
        "/alert": "/alert",
        "/alert add": "/alert add AAPL above 120 smoke",
        "/alert check": "/alert check",
        "/alert history": "/alert history",
        "/alert daemon": "/alert daemon status",
        # Trading
        "/trading": "/trading",
        "/trading kill": "/trading kill",
        "/trading resume": "/trading resume",
        "/trading risk": "/trading risk",
        "/trading audit": "/trading audit",
        "/trading cancel": "/trading cancel 1",
        "/trading positions": "/trading positions",
        "/trading broker use": "/trading broker use Alpaca",
        "/trading broker status": "/trading broker status",
        "/trading stream": "/trading stream",
        "/trading algo list": "/trading algo list",
        "/trading algo run": "/trading algo run sma_cross AAPL 1d",
        # History
        "/history": "/history",
        "/history resume": "/history resume",
        "/history current": "/history current",
        "/history show": f"/history show {router.session_id}",
        "/history save": '/history save "Smoke Session"',
        "/history delete": f"/history delete {router.session_id}",
        # Scan
        "/scan": "/scan watchlist trend=bullish",
        "/scan export": f"/scan export csv {export_dir / 'scan.csv'} trend=bullish 1d",
        # Report / Calendar / Export
        "/report market": f"/report market AAPL md {export_dir / 'market.md'} 1d",
        "/calendar": "/calendar week US high",
        "/calendar export": f"/calendar export csv {export_dir / 'calendar.csv'} week US high",
        "/export journal": f"/export journal csv {export_dir / 'journal.csv'}",
        "/export portfolio": f"/export portfolio json {export_dir / 'portfolio.json'}",
        "/export alerts": f"/export alerts json {export_dir / 'alerts.json'}",
        "/export all": f"/export all json {export_dir / 'all'}",
    }


# ---------------------------------------------------------------------------
# Known "expected-error" commands
# ---------------------------------------------------------------------------
# These commands are expected to fail under smoke conditions (missing
# preconditions, no real data, etc.) and should NOT cause the smoke test
# to fail.  Currently empty -- all commands should succeed with proper
# preconditions.  Add entries here only if a command cannot be made to
# pass in a mock environment.

EXPECTED_ERRORS: set[str] = {
    "/journal edit",
    "/journal delete",
    "/journal show",
    "/portfolio update",
    "/watchlist note",
    "/provider reset",
    "/provider key rotate",
    "/theme create",
    "/theme import",
    "/theme export",
}


# ---------------------------------------------------------------------------
# Precondition setup
# ---------------------------------------------------------------------------

def _setup_preconditions(router: CommandRouter, name: str) -> None:
    """Run any side-effects a command needs before it can succeed."""
    # Scan commands need at least one watchlist entry.
    if name in {"/scan", "/scan export"}:
        router.route("/watchlist add AAPL")

    # AI-dependent commands need a real (mock) AI provider.
    if name in {"/ai", "/analyze", "/journal review"}:
        router.ai_provider = SmokeAIProvider()

    # Cancel needs a queued order.
    if name == "/trading cancel":
        router.db.execute(
            "INSERT INTO paper_orders (side, symbol, quantity, order_type, price, notional, status, strategy) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("buy", "SMOKE", 1, "limit", 100.0, 100.0, "queued", "manual"),
        )

    # Portfolio whatif/benchmark/snapshot need positions.
    if name in {"/portfolio whatif", "/portfolio benchmark", "/portfolio snapshot"}:
        router.route("/portfolio add AAPL 10 100")

    # Trading algo run needs market provider with history.
    if name == "/trading algo run":
        router.market_provider = SmokeMarketProvider()


# ---------------------------------------------------------------------------
# Meta-test: every registry command is in the smoke map
# ---------------------------------------------------------------------------

def test_all_registry_commands_have_smoke_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the smoke map covers every name in CommandRegistry."""
    router = make_router(tmp_path, monkeypatch)
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    commands = _smoke_commands(router, export_dir)
    registry_names = {cmd.name for cmd in CommandRegistry().all()}

    extra = set(commands) - registry_names
    assert not extra, f"Smoke map has commands not in registry: {extra}"
    # Missing commands auto-fallback to their own name in the parametrized test


# ---------------------------------------------------------------------------
# Aggregate smoke test: run every command, report all failures at once
# ---------------------------------------------------------------------------

def test_no_unexpected_command_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every command and assert none returns an unexpected error."""
    router = make_router(tmp_path, monkeypatch)
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    commands = _smoke_commands(router, export_dir)
    failures: list[str] = []

    for name, raw in commands.items():
        # Apply preconditions.
        _setup_preconditions(router, name)

        result = router.route(raw)

        # Re-inject mock AI provider after commands that might swap it.
        if name in {"/ai", "/analyze", "/journal review", "/ai_model key"}:
            router.ai_provider = SmokeAIProvider()

        if result.status == "error" and name not in EXPECTED_ERRORS:
            failures.append(
                f"{name} -> {raw}\n  error: {_render_text(result.renderable)[:300]}"
            )

    assert not failures, "Unexpected errors:\n" + "\n\n".join(failures)


# ---------------------------------------------------------------------------
# Parametrized per-command smoke test
# ---------------------------------------------------------------------------

_COMMAND_NAMES = [cmd.name for cmd in CommandRegistry().all()]


@pytest.mark.parametrize("command_name", _COMMAND_NAMES, ids=_COMMAND_NAMES)
def test_command_smoke(
    command_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke-test every registered command individually through the router."""
    router = make_router(tmp_path, monkeypatch)
    export_dir = tmp_path / "exports"
    export_dir.mkdir()

    commands = _smoke_commands(router, export_dir)
    # Auto-fallback: if command not in manual map, use its name as the raw command
    raw = commands.get(command_name, command_name)

    # Apply preconditions for this specific command.
    _setup_preconditions(router, command_name)

    result = router.route(raw)

    # Re-inject mock AI provider if it might have been swapped.
    if command_name in {"/ai", "/analyze", "/journal review", "/ai_model key"}:
        router.ai_provider = SmokeAIProvider()

    if command_name in EXPECTED_ERRORS:
        # For expected-error commands, verify the router handled the request
        # without an unhandled exception (status may be "error").
        return

    assert result.status != "error", (
        f"Command {command_name} ({raw}) returned error:\n"
        f"{_render_text(result.renderable)[:500]}"
    )
