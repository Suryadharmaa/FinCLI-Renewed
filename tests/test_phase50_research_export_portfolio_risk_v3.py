from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.portfolio_risk import build_portfolio_risk
from fincli.app.modules.user_profile import UserProfile
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class Phase50AI:
    name = "phase50-ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(provider=self.name, model=request.model, content="AI report context.")


class Phase50Provider:
    name = "phase50-provider"

    async def quote(self, symbol: str) -> Quote:
        prices = {"AAPL": 150.0, "BTC-USD": 20_000.0, "EURUSD=X": 1.2}
        return Quote(symbol.upper(), prices.get(symbol.upper(), 100.0), "USD", self.name, datetime(2026, 6, 13), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            Candle(datetime(2026, 1, index + 1), 100 + index, 102 + index, 99 + index, 101 + index, 1_000 + index)
            for index in range(30)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [NewsItem("Company expands outlook", "UnitTest", "https://example.com", datetime(2026, 6, 13), "Context.")]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol.upper(), self.name, "USD", pe_ratio=18.0, eps=4.5, sector="Technology")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="healthy")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=Phase50Provider(),
        ai_provider=Phase50AI(),
    )


def test_research_report_exports_markdown(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    target = tmp_path / "research.md"

    result = router.route(f"/research AAPL --report --export md {target}")

    output = render_text(result.renderable)
    text = target.read_text(encoding="utf-8")
    assert "Research export complete" in output
    assert "# FinCLI Research Report: AAPL" in text
    assert "Signal:" in text
    assert "Source Quality:" in text
    assert "Not financial advice" in text


def test_research_report_exports_json(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    target = tmp_path / "research.json"

    result = router.route(f"/research AAPL --report --export json {target}")

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert result.status == "ready"
    assert payload["symbol"] == "AAPL"
    assert payload["mode"] == "report"
    assert "snapshot" in payload
    assert "source_quality" in payload


def test_portfolio_risk_v3_uses_profile_budget_currency_and_drawdown() -> None:
    positions = [
        {"symbol": "AAPL", "quantity": 10, "average_price": 100, "currency": "USD"},
        {"symbol": "BTC-USD", "quantity": 0.2, "average_price": 25_000, "currency": "USD"},
        {"symbol": "EURUSD=X", "quantity": 1_000, "average_price": 1.1, "currency": "EUR"},
    ]
    values = {
        "AAPL": (150.0, 500.0, 50.0),
        "BTC-USD": (20_000.0, -1_000.0, -20.0),
        "EURUSD=X": (1.2, 100.0, 9.09),
    }
    profile = UserProfile("Budi", 350.0, "USD", "1:100", 1.5, "Scalper")

    report = build_portfolio_risk(positions, values, realized_pnl=50.0, profile=profile)

    assert report.currency_exposure["USD"].market_value == 5500.0
    assert report.currency_exposure["EUR"].market_value == 1200.0
    assert report.drawdown_estimate < 0
    assert report.risk_budget.profile_gameplay == "Scalper"
    assert report.risk_budget.risk_per_trade <= 3.5
    assert any(w.asset_class == "crypto" for w in report.asset_class_warnings)


def test_portfolio_risk_command_outputs_v3_sections(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route('/profile set "Budi" 350 USD 1:100 1.5')
    router.route("/portfolio add AAPL 10 100")
    router.route("/portfolio add BTC-USD 0.2 25000")

    result = router.route("/portfolio risk")

    output = render_text(result.renderable)
    assert "Portfolio Risk v3" in output
    assert "Drawdown Estimate" in output
    assert "Currency Exposure" in output
    assert "Asset-Class Cap Warning" in output
    assert "Risk Budget" in output

