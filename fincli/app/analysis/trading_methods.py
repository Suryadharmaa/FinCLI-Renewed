"""Trading-method context inspired by common SNR, volume, pivot, and gap workflows."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.providers.market.base import Candle


@dataclass(frozen=True, slots=True)
class TradingMethodContext:
    nearest_support: float | None
    nearest_resistance: float | None
    support_break: bool
    resistance_break: bool
    bull_wick: bool
    bear_wick: bool
    volume_oscillator_percent: float | None
    volume_confirmation: str
    pivot_highs: list[float]
    pivot_lows: list[float]
    latest_gap: str
    method_notes: list[str]


def analyze_trading_methods(candles: list[Candle], left: int = 3, right: int = 3) -> TradingMethodContext:
    if not candles:
        raise ValueError("Candle data is empty.")

    pivot_highs, pivot_lows = _pivots(candles, left, right)
    recent = candles[-20:]
    latest = candles[-1]
    previous = candles[-2] if len(candles) >= 2 else candles[-1]
    support = _nearest_below(pivot_lows, latest.close) or min(float(candle.low) for candle in recent)
    resistance = _nearest_above(pivot_highs, latest.close) or max(float(candle.high) for candle in recent)
    volume_osc = _volume_oscillator(candles)
    volume_ok = volume_osc is not None and volume_osc > 20

    support_break = latest.close < support and volume_ok
    resistance_break = latest.close > resistance and volume_ok
    body = abs(latest.close - latest.open)
    upper_wick = latest.high - max(latest.open, latest.close)
    lower_wick = min(latest.open, latest.close) - latest.low
    bull_wick = latest.close > resistance and lower_wick > body
    bear_wick = latest.close < support and upper_wick > body
    latest_gap = _latest_gap(previous, latest)

    notes = [
        "SNR uses pivot highs/lows and recent range when pivots are sparse.",
        "Break confirmation requires close beyond level plus volume oscillator above 20%.",
        "Wick labels flag rejection risk around levels.",
        "Gap context is descriptive; confirm with liquidity and follow-through.",
    ]
    return TradingMethodContext(
        nearest_support=support,
        nearest_resistance=resistance,
        support_break=support_break,
        resistance_break=resistance_break,
        bull_wick=bull_wick,
        bear_wick=bear_wick,
        volume_oscillator_percent=volume_osc,
        volume_confirmation="confirmed" if volume_ok else "not confirmed",
        pivot_highs=pivot_highs[-5:],
        pivot_lows=pivot_lows[-5:],
        latest_gap=latest_gap,
        method_notes=notes,
    )


def format_trading_methods_context(context: TradingMethodContext) -> str:
    return (
        "Trading Method Context:\n"
        f"- SNR/Pivot: support={_fmt(context.nearest_support)}, resistance={_fmt(context.nearest_resistance)}, "
        f"pivot_highs={_fmt_list(context.pivot_highs)}, pivot_lows={_fmt_list(context.pivot_lows)}\n"
        f"- Break Logic: resistance_break={context.resistance_break}, support_break={context.support_break}, "
        f"bull_wick={context.bull_wick}, bear_wick={context.bear_wick}\n"
        f"- Volume: oscillator={_fmt(context.volume_oscillator_percent)}%, confirmation={context.volume_confirmation}\n"
        f"- Gap: {context.latest_gap}\n"
        f"- Method Notes: {'; '.join(context.method_notes)}"
    )


def _pivots(candles: list[Candle], left: int, right: int) -> tuple[list[float], list[float]]:
    highs: list[float] = []
    lows: list[float] = []
    if len(candles) < left + right + 1:
        return highs, lows
    for index in range(left, len(candles) - right):
        window = candles[index - left : index + right + 1]
        current = candles[index]
        if current.high == max(candle.high for candle in window):
            highs.append(float(current.high))
        if current.low == min(candle.low for candle in window):
            lows.append(float(current.low))
    return highs, lows


def _nearest_below(levels: list[float], price: float) -> float | None:
    candidates = [level for level in levels if level <= price]
    return max(candidates) if candidates else None


def _nearest_above(levels: list[float], price: float) -> float | None:
    candidates = [level for level in levels if level >= price]
    return min(candidates) if candidates else None


def _volume_oscillator(candles: list[Candle]) -> float | None:
    volumes = [float(candle.volume) for candle in candles]
    if len(volumes) < 10:
        return None
    short = _ema(volumes, 5)[-1]
    long = _ema(volumes, 10)[-1]
    if long == 0:
        return None
    return 100 * (short - long) / long


def _ema(values: list[float], span: int) -> list[float]:
    alpha = 2 / (span + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append((value * alpha) + result[-1] * (1 - alpha))
    return result


def _latest_gap(previous: Candle, latest: Candle) -> str:
    if latest.low > previous.high:
        return f"gap up above previous high {_fmt(previous.high)}"
    if latest.high < previous.low:
        return f"gap down below previous low {_fmt(previous.low)}"
    return "no open gap against previous candle"


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _fmt_list(values: list[float]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(_fmt(value) for value in values) + "]"
