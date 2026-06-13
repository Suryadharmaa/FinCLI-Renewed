from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_method_candles() -> list[Candle]:
    start = datetime(2026, 1, 1)
    closes = [100, 102, 101, 104, 103, 106, 105, 108, 107, 110, 109, 112, 111, 114, 113, 116, 115, 118, 117, 121]
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        low = close - (2.0 if index != len(closes) - 1 else 1.0)
        high = close + (2.0 if index != len(closes) - 1 else 5.0)
        open_ = close - 0.8
        volume = 1_000 + index * 30
        if index == len(closes) - 1:
            volume = 2_800
            open_ = 117
        candles.append(Candle(start + timedelta(days=index), open_, high, low, close, volume))
    return candles


class CapturingAIProvider:
    name = "capture-ai"

    def __init__(self) -> None:
        self.last_prompt = ""

    async def complete(self, request: AIRequest) -> AIResponse:
        self.last_prompt = request.prompt
        return AIResponse(provider=self.name, model=request.model, content="Signal: CAUTION\nSL:\nTP1:\nTP2:\nTP3:\nReason:")


class MethodMarketProvider:
    name = "method-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, 121, "USD", self.name, datetime(2026, 6, 7), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return make_method_candles()

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol, self.name, "USD")


def test_trading_methods_detect_snr_break_volume_and_gap() -> None:
    from fincli.app.analysis.trading_methods import analyze_trading_methods, format_trading_methods_context

    methods = analyze_trading_methods(make_method_candles())
    context = format_trading_methods_context(methods)

    assert methods.nearest_support is not None
    assert methods.nearest_resistance is not None
    assert methods.volume_oscillator_percent is not None
    assert "SNR/Pivot" in context
    assert "Volume" in context
    assert "Gap" in context


def test_analyze_prompt_includes_trading_methods_context(tmp_path: Path) -> None:
    ai = CapturingAIProvider()
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=MethodMarketProvider(),
        ai_provider=ai,
    )

    result = router.route("/analyze XAUUSD 1d")

    assert result.status == "ready"
    assert "Trading Method Context" in ai.last_prompt
    assert "SNR/Pivot" in ai.last_prompt
    assert "Volume" in ai.last_prompt
    assert "Gap" in ai.last_prompt
