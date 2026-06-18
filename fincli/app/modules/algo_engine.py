"""Algo trading strategy engine (Phase 0.7.0).

Runs strategies against market data and produces signals. Integrates with the
paper trading engine for automated order placement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fincli.app.analysis.indicators import summarize_technical_indicators
from fincli.app.providers.market.base import Candle
from fincli.app.services.market_data import MarketDataService
from fincli.app.utils.errors import CommandError


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategyResult:
    """Result of a strategy run."""

    strategy: str
    symbol: str
    signal: str  # buy, sell, hold
    confidence: int  # 0-100
    reason: str
    suggested_qty: float = 0.0


@dataclass(frozen=True, slots=True)
class StrategyInfo:
    """Metadata about a registered strategy."""

    name: str
    description: str
    asset_classes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Strategy Engine
# ---------------------------------------------------------------------------

BUILTIN_STRATEGIES: tuple[StrategyInfo, ...] = (
    StrategyInfo("sma_cross", "SMA crossover: buy when fast SMA crosses above slow SMA, sell on cross below.", ("equity", "etf", "crypto", "forex")),
    StrategyInfo("rsi_reversion", "RSI mean reversion: buy when RSI < 30 (oversold), sell when RSI > 70 (overbought).", ("equity", "etf", "crypto")),
    StrategyInfo("momentum", "Momentum: buy when RSI and MACD both bullish, sell when both bearish.", ("equity", "etf", "crypto")),
)


class StrategyEngine:
    """Registry and runner for trading strategies."""

    def __init__(self, market_service: MarketDataService) -> None:
        self.market_service = market_service
        self._strategies: dict[str, Any] = {
            "sma_cross": self._sma_cross,
            "rsi_reversion": self._rsi_reversion,
            "momentum": self._momentum,
        }

    def list_strategies(self) -> tuple[StrategyInfo, ...]:
        return BUILTIN_STRATEGIES

    async def run(self, strategy_name: str, symbol: str, timeframe: str = "1d", quantity: float = 1.0) -> StrategyResult:
        normalized = strategy_name.strip().lower()
        if normalized not in self._strategies:
            raise CommandError(f"Strategi tidak dikenal: {strategy_name}. Gunakan: {', '.join(sorted(self._strategies))}.")

        candles = await self.market_service.history(symbol.upper(), period="6mo", interval=timeframe)
        if not candles or len(candles) < 30:
            return StrategyResult(
                strategy=normalized,
                symbol=symbol.upper(),
                signal="hold",
                confidence=0,
                reason=f"Insufficient data: {len(candles)} candles (need >= 30).",
            )

        fn = self._strategies[normalized]
        return fn(symbol.upper(), candles, quantity)

    def _sma_cross(self, symbol: str, candles: list[Candle], quantity: float) -> StrategyResult:
        fast = _sma(candles, 10)
        slow = _sma(candles, 30)
        if len(fast) < 2 or len(slow) < 2:
            return StrategyResult("sma_cross", symbol, "hold", 0, "Not enough data for SMA calculation.")

        prev_fast, cur_fast = fast[-2], fast[-1]
        prev_slow, cur_slow = slow[-2], slow[-1]

        if prev_fast <= prev_slow and cur_fast > cur_slow:
            return StrategyResult("sma_cross", symbol, "buy", 70, f"SMA bullish crossover: fast {cur_fast:.2f} crossed above slow {cur_slow:.2f}.", quantity)
        if prev_fast >= prev_slow and cur_fast < cur_slow:
            return StrategyResult("sma_cross", symbol, "sell", 70, f"SMA bearish crossover: fast {cur_fast:.2f} crossed below slow {cur_slow:.2f}.", quantity)
        return StrategyResult("sma_cross", symbol, "hold", 30, f"No crossover. Fast={cur_fast:.2f}, Slow={cur_slow:.2f}.")

    def _rsi_reversion(self, symbol: str, candles: list[Candle], quantity: float) -> StrategyResult:
        summary = summarize_technical_indicators(candles)
        rsi = summary.rsi
        if rsi is None:
            return StrategyResult("rsi_reversion", symbol, "hold", 0, "RSI not available.")

        if rsi < 30:
            return StrategyResult("rsi_reversion", symbol, "buy", 65, f"RSI oversold at {rsi:.1f} < 30. Mean reversion buy signal.", quantity)
        if rsi > 70:
            return StrategyResult("rsi_reversion", symbol, "sell", 65, f"RSI overbought at {rsi:.1f} > 70. Mean reversion sell signal.", quantity)
        return StrategyResult("rsi_reversion", symbol, "hold", 20, f"RSI neutral at {rsi:.1f}. No signal.")

    def _momentum(self, symbol: str, candles: list[Candle], quantity: float) -> StrategyResult:
        summary = summarize_technical_indicators(candles)
        rsi = summary.rsi
        macd = summary.macd
        macd_signal = summary.macd_signal

        if rsi is None or macd is None or macd_signal is None:
            return StrategyResult("momentum", symbol, "hold", 0, "Insufficient indicator data.")

        rsi_bullish = rsi > 50
        macd_bullish = macd > macd_signal

        if rsi_bullish and macd_bullish:
            conf = min(80, 50 + int((rsi - 50) / 2))
            return StrategyResult("momentum", symbol, "buy", conf, f"Momentum bullish: RSI {rsi:.1f} > 50, MACD {macd:.4f} > signal {macd_signal:.4f}.", quantity)
        if not rsi_bullish and not macd_bullish:
            conf = min(80, 50 + int((50 - rsi) / 2))
            return StrategyResult("momentum", symbol, "sell", conf, f"Momentum bearish: RSI {rsi:.1f} < 50, MACD {macd:.4f} < signal {macd_signal:.4f}.", quantity)
        return StrategyResult("momentum", symbol, "hold", 25, f"Momentum mixed: RSI {rsi:.1f}, MACD {macd:.4f} vs signal {macd_signal:.4f}.")


# ---------------------------------------------------------------------------
# SMA helper
# ---------------------------------------------------------------------------


def _sma(candles: list[Candle], period: int) -> list[float]:
    closes = [c.close for c in candles]
    if len(closes) < period:
        return []
    result: list[float] = []
    for i in range(period - 1, len(closes)):
        result.append(sum(closes[i - period + 1 : i + 1]) / period)
    return result
