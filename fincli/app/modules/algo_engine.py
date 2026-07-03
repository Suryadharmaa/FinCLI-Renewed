"""Algo trading strategy engine (Phase 0.7.0).

Runs strategies against market data and produces signals. Integrates with the
paper trading engine for automated order placement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fincli.app.analysis.indicators import summarize_technical_indicators
from fincli.app.utils.errors import CommandError

if TYPE_CHECKING:
    from fincli.app.providers.market.base import Candle
    from fincli.app.services.market_data import MarketDataService

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
    params: tuple[str, ...] = ()  # customizable parameter names


# Default parameter definitions for each strategy
STRATEGY_PARAMS: dict[str, dict[str, Any]] = {
    "sma_cross": {"fast_period": 10, "slow_period": 30},
    "rsi_reversion": {"oversold": 30, "overbought": 70},
    "momentum": {"rsi_threshold": 50},
    "bollinger_squeeze": {"period": 20, "num_std": 2.0, "squeeze_threshold": 0.04},
    "macd_divergence": {},
    "volume_breakout": {"volume_multiplier": 2.0, "lookback": 20},
    "mean_reversion": {"lookback": 30, "z_threshold": 2.0},
}


# ---------------------------------------------------------------------------
# Strategy Engine
# ---------------------------------------------------------------------------

BUILTIN_STRATEGIES: tuple[StrategyInfo, ...] = (
    StrategyInfo("sma_cross", "SMA crossover: buy when fast SMA crosses above slow SMA, sell on cross below.", ("equity", "etf", "crypto", "forex"), ("fast_period", "slow_period")),
    StrategyInfo("rsi_reversion", "RSI mean reversion: buy when RSI < 30 (oversold), sell when RSI > 70 (overbought).", ("equity", "etf", "crypto"), ("oversold", "overbought")),
    StrategyInfo("momentum", "Momentum: buy when RSI and MACD both bullish, sell when both bearish.", ("equity", "etf", "crypto"), ("rsi_threshold",)),
    StrategyInfo("bollinger_squeeze", "Bollinger squeeze: buy when price breaks above upper band after squeeze, sell on lower band break.", ("equity", "etf", "crypto"), ("period", "num_std", "squeeze_threshold")),
    StrategyInfo("macd_divergence", "MACD divergence: buy when MACD histogram turns positive, sell when negative.", ("equity", "etf", "crypto", "forex")),
    StrategyInfo("volume_breakout", "Volume breakout: buy on volume spike + price above resistance, sell on volume spike + price below support.", ("equity", "etf", "crypto"), ("volume_multiplier", "lookback")),
    StrategyInfo("mean_reversion", "Z-score mean reversion: buy when Z-score < -2, sell when Z-score > 2.", ("equity", "etf", "crypto", "forex"), ("lookback", "z_threshold")),
)


class StrategyEngine:
    """Registry and runner for trading strategies."""

    def __init__(self, market_service: MarketDataService) -> None:
        self.market_service = market_service
        self._strategies: dict[str, Any] = {
            "sma_cross": self._sma_cross,
            "rsi_reversion": self._rsi_reversion,
            "momentum": self._momentum,
            "bollinger_squeeze": self._bollinger_squeeze,
            "macd_divergence": self._macd_divergence,
            "volume_breakout": self._volume_breakout,
            "mean_reversion": self._mean_reversion,
        }

    def list_strategies(self) -> tuple[StrategyInfo, ...]:
        return BUILTIN_STRATEGIES

    def default_params(self, strategy_name: str) -> dict[str, Any]:
        """Get default parameters for a strategy."""
        normalized = strategy_name.strip().lower()
        return dict(STRATEGY_PARAMS.get(normalized, {}))

    async def run(
        self,
        strategy_name: str,
        symbol: str,
        timeframe: str = "1d",
        quantity: float = 1.0,
        params: dict[str, Any] | None = None,
    ) -> StrategyResult:
        normalized = strategy_name.strip().lower()
        if normalized not in self._strategies:
            raise CommandError(f"Unknown strategy: {strategy_name}. Use: {', '.join(sorted(self._strategies))}.")

        # Merge default params with user overrides
        effective_params = self.default_params(normalized)
        if params:
            effective_params.update(params)

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
        return fn(symbol.upper(), candles, quantity, effective_params)

    def _sma_cross(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        p = params or {}
        fast_period = int(p.get("fast_period", 10))
        slow_period = int(p.get("slow_period", 30))
        fast = _sma(candles, fast_period)
        slow = _sma(candles, slow_period)
        if len(fast) < 2 or len(slow) < 2:
            return StrategyResult("sma_cross", symbol, "hold", 0, "Not enough data for SMA calculation.")

        prev_fast, cur_fast = fast[-2], fast[-1]
        prev_slow, cur_slow = slow[-2], slow[-1]

        if prev_fast <= prev_slow and cur_fast > cur_slow:
            return StrategyResult("sma_cross", symbol, "buy", 70, f"SMA bullish crossover: fast({fast_period}) {cur_fast:.2f} crossed above slow({slow_period}) {cur_slow:.2f}.", quantity)
        if prev_fast >= prev_slow and cur_fast < cur_slow:
            return StrategyResult("sma_cross", symbol, "sell", 70, f"SMA bearish crossover: fast({fast_period}) {cur_fast:.2f} crossed below slow({slow_period}) {cur_slow:.2f}.", quantity)
        return StrategyResult("sma_cross", symbol, "hold", 30, f"No crossover. Fast({fast_period})={cur_fast:.2f}, Slow({slow_period})={cur_slow:.2f}.")

    def _rsi_reversion(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        p = params or {}
        oversold = float(p.get("oversold", 30))
        overbought = float(p.get("overbought", 70))
        summary = summarize_technical_indicators(candles)
        rsi = summary.rsi
        if rsi is None:
            return StrategyResult("rsi_reversion", symbol, "hold", 0, "RSI not available.")

        if rsi < oversold:
            return StrategyResult("rsi_reversion", symbol, "buy", 65, f"RSI oversold at {rsi:.1f} < {oversold:.0f}. Mean reversion buy signal.", quantity)
        if rsi > overbought:
            return StrategyResult("rsi_reversion", symbol, "sell", 65, f"RSI overbought at {rsi:.1f} > {overbought:.0f}. Mean reversion sell signal.", quantity)
        return StrategyResult("rsi_reversion", symbol, "hold", 20, f"RSI neutral at {rsi:.1f}. No signal.")

    def _momentum(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        p = params or {}
        rsi_threshold = float(p.get("rsi_threshold", 50))
        summary = summarize_technical_indicators(candles)
        rsi = summary.rsi
        macd = summary.macd
        macd_signal = summary.macd_signal

        if rsi is None or macd is None or macd_signal is None:
            return StrategyResult("momentum", symbol, "hold", 0, "Insufficient indicator data.")

        rsi_bullish = rsi > rsi_threshold
        macd_bullish = macd > macd_signal

        if rsi_bullish and macd_bullish:
            conf = min(80, 50 + int((rsi - rsi_threshold) / 2))
            return StrategyResult("momentum", symbol, "buy", conf, f"Momentum bullish: RSI {rsi:.1f} > {rsi_threshold:.0f}, MACD {macd:.4f} > signal {macd_signal:.4f}.", quantity)
        if not rsi_bullish and not macd_bullish:
            conf = min(80, 50 + int((rsi_threshold - rsi) / 2))
            return StrategyResult("momentum", symbol, "sell", conf, f"Momentum bearish: RSI {rsi:.1f} < {rsi_threshold:.0f}, MACD {macd:.4f} < signal {macd_signal:.4f}.", quantity)
        return StrategyResult("momentum", symbol, "hold", 25, f"Momentum mixed: RSI {rsi:.1f}, MACD {macd:.4f} vs signal {macd_signal:.4f}.")

    def _bollinger_squeeze(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        p = params or {}
        period = int(p.get("period", 20))
        num_std = float(p.get("num_std", 2.0))
        squeeze_threshold = float(p.get("squeeze_threshold", 0.04))

        closes = [c.close for c in candles]
        if len(closes) < period:
            return StrategyResult("bollinger_squeeze", symbol, "hold", 0, f"Insufficient data for Bollinger Bands (need {period} candles).")

        upper, middle, lower = _bollinger_bands(candles, period, num_std)
        if len(upper) < 2:
            return StrategyResult("bollinger_squeeze", symbol, "hold", 0, "Not enough data for Bollinger calculation.")

        cur_close = closes[-1]
        prev_close = closes[-2]
        cur_upper = upper[-1]
        cur_lower = lower[-1]
        cur_middle = middle[-1]

        band_width = (cur_upper - cur_lower) / cur_middle if cur_middle > 0 else 0
        is_squeeze = band_width < squeeze_threshold

        if prev_close <= upper[-2] and cur_close > cur_upper:
            conf = 75 if is_squeeze else 60
            return StrategyResult("bollinger_squeeze", symbol, "buy", conf,
                f"Bollinger breakout above upper band. Price {cur_close:.2f} > upper {cur_upper:.2f}. "
                f"Band width {band_width:.1%} ({'squeeze' if is_squeeze else 'normal'}).", quantity)
        if prev_close >= lower[-2] and cur_close < cur_lower:
            conf = 75 if is_squeeze else 60
            return StrategyResult("bollinger_squeeze", symbol, "sell", conf,
                f"Bollinger breakout below lower band. Price {cur_close:.2f} < lower {cur_lower:.2f}. "
                f"Band width {band_width:.1%} ({'squeeze' if is_squeeze else 'normal'}).", quantity)

        return StrategyResult("bollinger_squeeze", symbol, "hold", 20,
            f"Price {cur_close:.2f} within bands [{cur_lower:.2f}, {cur_upper:.2f}]. Band width {band_width:.1%}.")

    def _macd_divergence(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        summary = summarize_technical_indicators(candles)
        macd = summary.macd
        macd_signal = summary.macd_signal

        if macd is None or macd_signal is None:
            return StrategyResult("macd_divergence", symbol, "hold", 0, "MACD data not available.")

        histogram = macd - macd_signal

        closes = [c.close for c in candles]
        if len(closes) < 35:
            return StrategyResult("macd_divergence", symbol, "hold", 0, "Insufficient data for MACD divergence.")

        if histogram > 0 and macd > 0:
            conf = min(75, 50 + int(abs(histogram) * 1000))
            return StrategyResult("macd_divergence", symbol, "buy", conf,
                f"MACD histogram positive: {histogram:.4f}. MACD {macd:.4f} > signal {macd_signal:.4f}.", quantity)
        if histogram < 0 and macd < 0:
            conf = min(75, 50 + int(abs(histogram) * 1000))
            return StrategyResult("macd_divergence", symbol, "sell", conf,
                f"MACD histogram negative: {histogram:.4f}. MACD {macd:.4f} < signal {macd_signal:.4f}.", quantity)

        return StrategyResult("macd_divergence", symbol, "hold", 20,
            f"MACD histogram {histogram:.4f}. No clear divergence.")

    def _volume_breakout(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        p = params or {}
        volume_multiplier = float(p.get("volume_multiplier", 2.0))
        lookback = int(p.get("lookback", 20))

        if len(candles) < lookback:
            return StrategyResult("volume_breakout", symbol, "hold", 0, f"Insufficient data for volume breakout (need {lookback} candles).")

        summary = summarize_technical_indicators(candles)
        cur_close = candles[-1].close
        cur_volume = candles[-1].volume

        avg_volume = sum(c.volume for c in candles[-lookback:]) / lookback
        volume_ratio = cur_volume / avg_volume if avg_volume > 0 else 0

        support = summary.support
        resistance = summary.resistance

        if support is None or resistance is None:
            return StrategyResult("volume_breakout", symbol, "hold", 0, "Support/resistance levels not available.")

        is_volume_spike = volume_ratio > volume_multiplier

        if is_volume_spike and cur_close > resistance:
            conf = min(80, 50 + int(volume_ratio * 10))
            return StrategyResult("volume_breakout", symbol, "buy", conf,
                f"Volume breakout: price {cur_close:.2f} > resistance {resistance:.2f} on {volume_ratio:.1f}x volume.", quantity)
        if is_volume_spike and cur_close < support:
            conf = min(80, 50 + int(volume_ratio * 10))
            return StrategyResult("volume_breakout", symbol, "sell", conf,
                f"Volume breakdown: price {cur_close:.2f} < support {support:.2f} on {volume_ratio:.1f}x volume.", quantity)

        return StrategyResult("volume_breakout", symbol, "hold", 20,
            f"Price {cur_close:.2f}, volume {volume_ratio:.1f}x avg. Support {support:.2f}, resistance {resistance:.2f}.")

    def _mean_reversion(self, symbol: str, candles: list[Candle], quantity: float, params: dict[str, Any] | None = None) -> StrategyResult:
        p = params or {}
        lookback = int(p.get("lookback", 30))
        z_threshold = float(p.get("z_threshold", 2.0))

        if len(candles) < lookback:
            return StrategyResult("mean_reversion", symbol, "hold", 0, f"Insufficient data for Z-score calculation (need {lookback} candles).")

        closes = [c.close for c in candles]
        mean = sum(closes[-lookback:]) / lookback
        variance = sum((x - mean) ** 2 for x in closes[-lookback:]) / lookback
        std = variance ** 0.5

        if std == 0:
            return StrategyResult("mean_reversion", symbol, "hold", 0, "Zero price volatility.")

        z_score = (closes[-1] - mean) / std

        if z_score < -z_threshold:
            conf = min(80, 50 + int(abs(z_score) * 10))
            return StrategyResult("mean_reversion", symbol, "buy", conf,
                f"Z-score {z_score:.2f} < -{z_threshold:.1f}. Price {closes[-1]:.2f} far below {lookback}d mean {mean:.2f}. Oversold.", quantity)
        if z_score > z_threshold:
            conf = min(80, 50 + int(abs(z_score) * 10))
            return StrategyResult("mean_reversion", symbol, "sell", conf,
                f"Z-score {z_score:.2f} > {z_threshold:.1f}. Price {closes[-1]:.2f} far above {lookback}d mean {mean:.2f}. Overbought.", quantity)

        return StrategyResult("mean_reversion", symbol, "hold", 20,
            f"Z-score {z_score:.2f}. Price {closes[-1]:.2f} near {lookback}d mean {mean:.2f}.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sma(candles: list[Candle], period: int) -> list[float]:
    closes = [c.close for c in candles]
    if len(closes) < period:
        return []
    result: list[float] = []
    for i in range(period - 1, len(closes)):
        result.append(sum(closes[i - period + 1 : i + 1]) / period)
    return result


def _bollinger_bands(candles: list[Candle], period: int = 20, num_std: float = 2.0) -> tuple[list[float], list[float], list[float]]:
    """Calculate Bollinger Bands (upper, middle, lower)."""
    closes = [c.close for c in candles]
    if len(closes) < period:
        return [], [], []

    upper: list[float] = []
    middle: list[float] = []
    lower: list[float] = []

    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        std = variance ** 0.5
        middle.append(sma)
        upper.append(sma + num_std * std)
        lower.append(sma - num_std * std)

    return upper, middle, lower
