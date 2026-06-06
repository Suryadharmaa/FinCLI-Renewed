from datetime import datetime
from pathlib import Path

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class CapturingAIProvider:
    name = "capture-ai"

    def __init__(self) -> None:
        self.last_prompt = ""

    async def complete(self, request: AIRequest) -> AIResponse:
        self.last_prompt = request.prompt
        return AIResponse(provider=self.name, model=request.model, content="Market Summary: context received")


class ContextMarketProvider:
    name = "context-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol.upper(), price=100.0, currency="USD", provider=self.name, timestamp=datetime.now(), status="delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            Candle(datetime(2026, 1, index + 1), 100 + index, 102 + index, 99 + index, 101 + index, 1_000)
            for index in range(20)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [NewsItem("Earnings beat expectations", "UnitTest News", "https://example.com", datetime(2026, 6, 4), "Revenue improved")]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD", market_cap=1_000_000, pe_ratio=20.5, sector="Technology")


def test_analyze_prompt_includes_news_fundamental_and_structure_context(tmp_path: Path) -> None:
    ai = CapturingAIProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ContextMarketProvider(),
        ai_provider=ai,
    )

    result = router.route("/analyze AAPL 1d")

    assert result.status == "ready"
    assert "Earnings beat expectations" in ai.last_prompt
    assert "P/E Ratio: 20.5000" in ai.last_prompt
    assert "Market Structure" in ai.last_prompt
    assert "Liquidity Area" in ai.last_prompt
