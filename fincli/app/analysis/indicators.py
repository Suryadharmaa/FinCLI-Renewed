"""Technical indicator calculations."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.providers.market.base import Candle


@dataclass(frozen=True, slots=True)
class TechnicalSummary:
    latest_close: float
    sma_fast: float | None
    sma_slow: float | None
    ema_fast: float | None
    rsi: float | None
    macd: float | None
    macd_signal: float | None
    bollinger_upper: float | None
    bollinger_lower: float | None
    atr: float | None
    support: float | None
    resistance: float | None
    volume_latest: float | None
    trend_bias: str


def phase_one_indicator_status() -> str:
    return "Indicator engine active: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, volume, support, and resistance."


def summarize_technical_indicators(candles: list[Candle]) -> TechnicalSummary:
    """Calculate a compact technical summary from OHLCV candles."""
    if not candles:
        raise ValueError("Data candle kosong.")

    closes = [float(candle.close) for candle in candles]
    highs = [float(candle.high) for candle in candles]
    lows = [float(candle.low) for candle in candles]
    volumes = [float(candle.volume) for candle in candles]

    sma_fast = _sma(closes, 5)
    sma_slow = _sma(closes, 20)
    ema_fast_series = _ema_series(closes, 12)
    ema_slow_series = _ema_series(closes, 26)
    ema_fast = ema_fast_series[-1] if ema_fast_series else None
    rsi = _rsi(closes, 14)
    macd, macd_signal = _macd(ema_fast_series, ema_slow_series)
    bollinger_upper, bollinger_lower = _bollinger(closes, 20)
    atr = _atr(highs, lows, closes, 14)
    support = min(lows[-20:]) if lows else None
    resistance = max(highs[-20:]) if highs else None

    trend_bias = "neutral"
    if sma_fast is not None and sma_slow is not None:
        if closes[-1] > sma_fast > sma_slow:
            trend_bias = "bullish"
        elif closes[-1] < sma_fast < sma_slow:
            trend_bias = "bearish"

    return TechnicalSummary(
        latest_close=closes[-1],
        sma_fast=sma_fast,
        sma_slow=sma_slow,
        ema_fast=ema_fast,
        rsi=rsi,
        macd=macd,
        macd_signal=macd_signal,
        bollinger_upper=bollinger_upper,
        bollinger_lower=bollinger_lower,
        atr=atr,
        support=support,
        resistance=resistance,
        volume_latest=volumes[-1] if volumes else None,
        trend_bias=trend_bias,
    )


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _ema_series(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (span + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append((value * alpha) + (result[-1] * (1 - alpha)))
    return result


def _rsi(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-window - 1 : -1], values[-window:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100 - (100 / (1 + rs))


def _macd(ema_fast: list[float], ema_slow: list[float]) -> tuple[float | None, float | None]:
    if not ema_fast or not ema_slow:
        return None, None
    length = min(len(ema_fast), len(ema_slow))
    macd_series = [ema_fast[-length + index] - ema_slow[-length + index] for index in range(length)]
    signal = _ema_series(macd_series, 9)
    return macd_series[-1], signal[-1] if signal else None


def _bollinger(values: list[float], window: int) -> tuple[float | None, float | None]:
    if len(values) < window:
        return None, None
    subset = values[-window:]
    mean = sum(subset) / window
    variance = sum((value - mean) ** 2 for value in subset) / window
    stddev = variance**0.5
    return mean + (2 * stddev), mean - (2 * stddev)


def _atr(highs: list[float], lows: list[float], closes: list[float], window: int) -> float | None:
    if len(highs) <= window or len(lows) <= window or len(closes) <= window:
        return None
    true_ranges: list[float] = []
    for index in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return sum(true_ranges[-window:]) / window
