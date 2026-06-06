"""Simple market structure analysis."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.providers.market.base import Candle


@dataclass(frozen=True, slots=True)
class MarketStructureSummary:
    trend: str
    latest_pattern: str
    break_of_structure: bool
    change_of_character: bool
    support: float | None
    resistance: float | None
    liquidity_area: str | None
    risk_zone: str | None


def phase_one_structure_status() -> str:
    return "Market structure engine active: HH/HL/LH/LL, BOS, CHoCH, liquidity area, and risk zone."


def analyze_market_structure(candles: list[Candle], lookback: int = 20) -> MarketStructureSummary:
    """Detect a compact HH/HL/LH/LL-style market structure summary."""
    if not candles:
        raise ValueError("Data candle kosong.")

    recent = candles[-lookback:]
    highs = [float(candle.high) for candle in recent]
    lows = [float(candle.low) for candle in recent]
    closes = [float(candle.close) for candle in recent]

    previous_high = max(highs[:-1]) if len(highs) > 1 else highs[-1]
    previous_low = min(lows[:-1]) if len(lows) > 1 else lows[-1]
    latest_high = highs[-1]
    latest_low = lows[-1]
    latest_close = closes[-1]

    higher_high = latest_high > previous_high
    higher_low = len(lows) < 3 or latest_low > min(lows[-4:-1])
    lower_high = len(highs) < 3 or latest_high < max(highs[-4:-1])
    lower_low = latest_low < previous_low

    if higher_high and higher_low:
        latest_pattern = "HH/HL"
        trend = "bullish"
    elif lower_high and lower_low:
        latest_pattern = "LH/LL"
        trend = "bearish"
    elif higher_high:
        latest_pattern = "HH"
        trend = "bullish"
    elif lower_low:
        latest_pattern = "LL"
        trend = "bearish"
    else:
        latest_pattern = "range"
        trend = "neutral"

    break_of_structure = latest_close > previous_high or latest_close < previous_low
    prior_window = recent[:-2] if len(recent) >= 5 else recent[:-1]
    prior_bias = _prior_bias(prior_window)
    change_of_character = (prior_bias == "bullish" and trend == "bearish") or (prior_bias == "bearish" and trend == "bullish")

    support = min(lows)
    resistance = max(highs)
    liquidity_area = f"Above {_fmt(resistance)} / below {_fmt(support)}"
    risk_zone = f"Invalidation near {_fmt(support if trend == 'bullish' else resistance)}"

    return MarketStructureSummary(
        trend=trend,
        latest_pattern=latest_pattern,
        break_of_structure=break_of_structure,
        change_of_character=change_of_character,
        support=support,
        resistance=resistance,
        liquidity_area=liquidity_area,
        risk_zone=risk_zone,
    )


def _prior_bias(candles: list[Candle]) -> str:
    if len(candles) < 3:
        return "neutral"
    highs = [float(candle.high) for candle in candles]
    lows = [float(candle.low) for candle in candles]
    if highs[-1] > max(highs[:-1]) and lows[-1] > min(lows[:-1]):
        return "bullish"
    if lows[-1] < min(lows[:-1]) and highs[-1] < max(highs[:-1]):
        return "bearish"
    first_close = float(candles[0].close)
    last_close = float(candles[-1].close)
    if last_close > first_close:
        return "bullish"
    if last_close < first_close:
        return "bearish"
    return "neutral"


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"
