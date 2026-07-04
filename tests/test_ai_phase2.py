from datetime import datetime
from pathlib import Path

from fincli.app.analysis.assistant_context import extract_market_symbols
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class FakeAIProvider:
    name = "fake-ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        assert request.prompt
        return AIResponse(provider=self.name, model=request.model, content="Market Summary: fake response")


class CapturingAIProvider:
    name = "capture-ai"

    def __init__(self) -> None:
        self.last_prompt = ""
        self.calls = 0

    async def complete(self, request: AIRequest) -> AIResponse:
        self.calls += 1
        self.last_prompt = request.prompt
        return AIResponse(provider=self.name, model=request.model, content="Market Summary: context received")


class FakeMarketProvider:
    name = "fake-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol.upper(),
            price=100.0,
            currency="USD",
            provider=self.name,
            timestamp=datetime(2026, 6, 4, 12, 0, 0),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            Candle(
                timestamp=datetime(2026, 1, index + 1),
                open=float(100 + index),
                high=float(102 + index),
                low=float(99 + index),
                close=float(101 + index),
                volume=1_000,
            )
            for index in range(20)
        ]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [
            NewsItem(
                title=f"{symbol.upper()} market update",
                source="UnitTest News",
                url=None,
                published_at=datetime(2026, 6, 4, 12, 0, 0),
                summary="Provider context reached free chat.",
            )
        ]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(
            symbol=symbol.upper(),
            provider=self.name,
            currency="USD",
            market_cap=1_000_000_000,
            pe_ratio=21.5,
            eps=4.2,
            sector="Technology",
            industry="Software",
        )


def make_router(tmp_path: Path) -> CommandRouter:
    config = ConfigManager(tmp_path / "config.json")
    db = FinCLIDatabase(tmp_path / "fincli.db")
    return CommandRouter(config=config, db=db, market_provider=FakeMarketProvider(), ai_provider=FakeAIProvider())


def test_ai_command_uses_ai_provider(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/ai ringkas risiko AAPL")

    assert result.status == "ready"
    assert "fake response" in str(result.renderable)
    assert "fake-ai" in str(result.renderable)


def test_ai_freechat_adds_fincli_market_context(tmp_path: Path) -> None:
    ai = CapturingAIProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeMarketProvider(),
        ai_provider=ai,
    )

    result = router.route("/ai ringkas risiko AAPL")

    assert result.status == "ready"
    assert ai.calls == 1
    assert "You are FinCLI AI Assistance" in ai.last_prompt
    assert "Symbol: AAPL" in ai.last_prompt
    assert "Quote: price=100.0000 USD" in ai.last_prompt
    assert "Technical:" in ai.last_prompt
    assert "Fundamentals:" in ai.last_prompt
    assert "AAPL market update" in ai.last_prompt


def test_ai_freechat_blocks_coding_without_provider_call(tmp_path: Path) -> None:
    ai = CapturingAIProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeMarketProvider(),
        ai_provider=ai,
    )

    result = router.route("/ai buat kode python untuk fetch saham")

    assert result.status == "ready"
    assert ai.calls == 0
    output = str(result.renderable)
    assert "don't handle coding" in output
    assert "FinCLI" in output


def test_ai_symbol_extraction_ignores_plain_greetings() -> None:
    assert extract_market_symbols("hello") == []
    assert extract_market_symbols("are you fast") == []
    assert extract_market_symbols("ringkas risiko AAPL") == ["AAPL"]
    assert extract_market_symbols("analisa eurusd dan xauusd") == ["EURUSD", "XAUUSD"]


def test_analyze_command_builds_market_analysis_prompt(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/analyze AAPL 1d")

    assert result.status == "ready"
    output = str(result.renderable)
    assert "AAPL" in output
    assert "Market Summary" in output
    assert "bukan nasihat keuangan" in output
