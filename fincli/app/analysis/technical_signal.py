"""Rule-based technical signal evaluation for FinCLI."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.analysis.indicators import TechnicalSummary
from fincli.app.analysis.market_structure import MarketStructureSummary
from fincli.app.providers.market.base import Candle


@dataclass(frozen=True, slots=True)
class TechnicalSignal:
    label: str
    score: int
    confidence: str
    reasons: tuple[str, ...]
    risk_notes: tuple[str, ...]
    invalidation: str


def evaluate_technical_signal(
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
    candles: list[Candle],
) -> TechnicalSignal:
    """Evaluate a transparent buy/sell/caution candidate signal.

    This is a deterministic decision aid, not a financial recommendation.
    It intentionally favors CAUTION when evidence is mixed or risk flags are high.
    """

    bullish = 0
    bearish = 0
    reasons: list[str] = []
    risk_notes: list[str] = []

    latest_close = technical.latest_close
    atr_pct = _atr_percent(technical.atr, latest_close)
    avg_volume = _average_volume(candles[-20:])
    latest_volume = technical.volume_latest

    if technical.trend_bias == "bullish":
        bullish += 2
        reasons.append("Trend bias bullish: price/MA alignment supports upside continuation.")
    elif technical.trend_bias == "bearish":
        bearish += 2
        reasons.append("Trend bias bearish: price/MA alignment supports downside continuation.")
    else:
        risk_notes.append("Trend bias neutral: no clean directional edge from moving averages.")

    if structure.trend == "bullish":
        bullish += 2
        reasons.append(f"Market structure bullish: latest pattern {structure.latest_pattern}.")
    elif structure.trend == "bearish":
        bearish += 2
        reasons.append(f"Market structure bearish: latest pattern {structure.latest_pattern}.")
    else:
        risk_notes.append(f"Market structure neutral/ranging: latest pattern {structure.latest_pattern}.")

    if technical.sma_fast is not None and technical.sma_slow is not None:
        if latest_close > technical.sma_fast > technical.sma_slow:
            bullish += 1
            reasons.append("SMA stack bullish: close > SMA fast > SMA slow.")
        elif latest_close < technical.sma_fast < technical.sma_slow:
            bearish += 1
            reasons.append("SMA stack bearish: close < SMA fast < SMA slow.")
        else:
            risk_notes.append("SMA stack mixed: moving-average confirmation is incomplete.")

    if technical.macd is not None and technical.macd_signal is not None:
        if technical.macd > technical.macd_signal and technical.macd > 0:
            bullish += 1
            reasons.append("MACD bullish: MACD is above signal and positive.")
        elif technical.macd < technical.macd_signal and technical.macd < 0:
            bearish += 1
            reasons.append("MACD bearish: MACD is below signal and negative.")
        elif technical.macd > technical.macd_signal:
            bullish += 1
            reasons.append("MACD improving: MACD is above signal, but trend strength still needs confirmation.")
        elif technical.macd < technical.macd_signal:
            bearish += 1
            reasons.append("MACD weakening: MACD is below signal, but downside strength still needs confirmation.")

    if technical.rsi is not None:
        if 45 <= technical.rsi <= 68:
            bullish += 1
            reasons.append("RSI constructive: momentum is positive without extreme overbought pressure.")
        elif 32 <= technical.rsi <= 55:
            bearish += 1 if technical.trend_bias == "bearish" else 0
            reasons.append("RSI defensive: momentum is not strongly bullish.")
        elif technical.rsi > 75:
            bearish += 1
            risk_notes.append("RSI overbought: upside may be extended; chase risk is elevated.")
        elif technical.rsi < 25:
            bullish += 1
            risk_notes.append("RSI oversold: downside may be extended; shorting risk is elevated.")

    if technical.support is not None and technical.resistance is not None:
        range_width = max(technical.resistance - technical.support, 0.0)
        if range_width > 0:
            position = (latest_close - technical.support) / range_width
            if position <= 0.35:
                bullish += 1
                reasons.append("Price is closer to support than resistance, improving long risk/reward if support holds.")
            elif position >= 0.65:
                bearish += 1
                risk_notes.append("Price is closer to resistance than support; breakout confirmation is needed.")

    if avg_volume is not None and latest_volume is not None and avg_volume > 0:
        volume_ratio = latest_volume / avg_volume
        if volume_ratio >= 1.2:
            if bullish >= bearish:
                bullish += 1
                reasons.append("Volume confirmation: latest volume is above recent average.")
            else:
                bearish += 1
                reasons.append("Volume confirmation: selling pressure has above-average participation.")
        elif volume_ratio < 0.7:
            risk_notes.append("Low participation: latest volume is below recent average.")

    if structure.change_of_character:
        risk_notes.append("Change of character detected: direction may be transitioning, avoid overconfidence.")
    if atr_pct is not None:
        if atr_pct >= 5:
            risk_notes.append(f"High volatility: ATR is about {atr_pct:.2f}% of price.")
        elif atr_pct <= 0.5:
            risk_notes.append(f"Low volatility: ATR is about {atr_pct:.2f}% of price; false breakouts possible.")

    net_score = bullish - bearish
    label = "CAUTION"
    if net_score >= 4 and len(risk_notes) <= 2:
        label = "BEST TO BUY"
    elif net_score <= -4 and len(risk_notes) <= 2:
        label = "BEST TO SELL"

    confidence = _confidence(abs(net_score), risk_notes)
    invalidation = _invalidation(label, technical, structure)

    if not reasons:
        reasons.append("No dominant technical edge found from current indicators.")
    if not risk_notes:
        risk_notes.append("No major rule-based risk flag, but market conditions can change quickly.")

    return TechnicalSignal(
        label=label,
        score=net_score,
        confidence=confidence,
        reasons=tuple(reasons[:6]),
        risk_notes=tuple(risk_notes[:5]),
        invalidation=invalidation,
    )


def format_signal(signal: TechnicalSignal) -> str:
    reasons = "\n".join(f"- {reason}" for reason in signal.reasons)
    risk_notes = "\n".join(f"- {note}" for note in signal.risk_notes)
    return (
        f"Signal: {signal.label}\n"
        f"Signal Score: {signal.score}\n"
        f"Confidence: {signal.confidence}\n"
        "Signal Reasoning:\n"
        f"{reasons}\n"
        "Signal Risk Notes:\n"
        f"{risk_notes}\n"
        f"Invalidation / Caution Level: {signal.invalidation}\n"
        "Signal Disclaimer: scenario-based technical signal, not financial advice."
    )


def _confidence(score_abs: int, risk_notes: list[str]) -> str:
    if score_abs >= 6 and len(risk_notes) <= 1:
        return "high"
    if score_abs >= 4 and len(risk_notes) <= 3:
        return "medium"
    return "low"


def _invalidation(label: str, technical: TechnicalSummary, structure: MarketStructureSummary) -> str:
    if label == "BEST TO BUY":
        return f"Bias weakens below support {_fmt(technical.support or structure.support)} or if RSI/MACD momentum rolls over."
    if label == "BEST TO SELL":
        return f"Bias weakens above resistance {_fmt(technical.resistance or structure.resistance)} or if MACD/structure flips bullish."
    return "Wait for cleaner trend, structure confirmation, or better location near support/resistance."


def _atr_percent(atr: float | None, price: float | None) -> float | None:
    if atr is None or price is None or price == 0:
        return None
    return abs(atr / price) * 100


def _average_volume(candles: list[Candle]) -> float | None:
    if not candles:
        return None
    volumes = [float(candle.volume) for candle in candles]
    return sum(volumes) / len(volumes)


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"
