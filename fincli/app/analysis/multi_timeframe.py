"""Multi-timeframe technical alignment analysis."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.analysis.market_structure import MarketStructureSummary, analyze_market_structure
from fincli.app.providers.market.base import Candle


class HistoryProvider(Protocol):
    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        """Fetch candles for a symbol/timeframe."""


@dataclass(frozen=True, slots=True)
class TimeframeAnalysis:
    timeframe: str
    status: str
    candles: int
    latest_close: float | None
    trend_bias: str
    structure_trend: str
    rsi: float | None
    macd: float | None
    support: float | None
    resistance: float | None
    note: str = ""


@dataclass(frozen=True, slots=True)
class MultiTimeframeAnalysis:
    symbol: str
    frames: list[TimeframeAnalysis]
    alignment: str
    score: int
    bias: str
    risk_note: str


async def analyze_multi_timeframe(
    symbol: str,
    provider: HistoryProvider,
    timeframes: tuple[str, ...] = ("1d", "1h", "15m"),
) -> MultiTimeframeAnalysis:
    tasks = [_analyze_frame(symbol, provider, timeframe) for timeframe in timeframes]
    frames = list(await asyncio.gather(*tasks))
    score = sum(_frame_score(frame) for frame in frames if frame.status == "ready")
    ready_count = sum(1 for frame in frames if frame.status == "ready")

    if ready_count == 0:
        return MultiTimeframeAnalysis(
            symbol=symbol.upper(),
            frames=frames,
            alignment="unavailable",
            score=0,
            bias="caution",
            risk_note="No timeframe returned enough data. Check provider, symbol format, and interval support.",
        )

    if score >= max(2, ready_count):
        bias = "bullish"
    elif score <= -max(2, ready_count):
        bias = "bearish"
    else:
        bias = "mixed/caution"

    alignment = _alignment_label(frames)
    risk_note = _risk_note(frames, bias)
    return MultiTimeframeAnalysis(symbol=symbol.upper(), frames=frames, alignment=alignment, score=score, bias=bias, risk_note=risk_note)


async def _analyze_frame(symbol: str, provider: HistoryProvider, timeframe: str) -> TimeframeAnalysis:
    try:
        candles = await provider.history(symbol, period=_period_for_timeframe(timeframe), interval=timeframe)
        if len(candles) < 20:
            return TimeframeAnalysis(
                timeframe=timeframe,
                status="insufficient",
                candles=len(candles),
                latest_close=candles[-1].close if candles else None,
                trend_bias="neutral",
                structure_trend="neutral",
                rsi=None,
                macd=None,
                support=None,
                resistance=None,
                note="Need at least 20 candles for stable multi-timeframe summary.",
            )
        technical = summarize_technical_indicators(candles)
        structure = analyze_market_structure(candles)
        return _frame_from_summary(timeframe, candles, technical, structure)
    except Exception as exc:  # noqa: BLE001
        return TimeframeAnalysis(
            timeframe=timeframe,
            status="unavailable",
            candles=0,
            latest_close=None,
            trend_bias="neutral",
            structure_trend="neutral",
            rsi=None,
            macd=None,
            support=None,
            resistance=None,
            note=str(exc),
        )


def _frame_from_summary(
    timeframe: str,
    candles: list[Candle],
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
) -> TimeframeAnalysis:
    return TimeframeAnalysis(
        timeframe=timeframe,
        status="ready",
        candles=len(candles),
        latest_close=technical.latest_close,
        trend_bias=technical.trend_bias,
        structure_trend=structure.trend,
        rsi=technical.rsi,
        macd=technical.macd,
        support=technical.support,
        resistance=technical.resistance,
    )


def _period_for_timeframe(timeframe: str) -> str:
    normalized = timeframe.lower()
    if normalized in {"1m", "5m", "15m", "30m", "1h", "4h"}:
        return "60d"
    if normalized in {"1w", "w"}:
        return "2y"
    return "1y"


def _frame_score(frame: TimeframeAnalysis) -> int:
    score = 0
    if frame.trend_bias == "bullish":
        score += 1
    elif frame.trend_bias == "bearish":
        score -= 1
    if frame.structure_trend == "bullish":
        score += 1
    elif frame.structure_trend == "bearish":
        score -= 1
    if frame.rsi is not None:
        if frame.rsi > 70:
            score -= 1
        elif frame.rsi < 30:
            score += 1
    return score


def _alignment_label(frames: list[TimeframeAnalysis]) -> str:
    ready = [frame for frame in frames if frame.status == "ready"]
    if not ready:
        return "unavailable"
    trends = {frame.trend_bias for frame in ready}
    structures = {frame.structure_trend for frame in ready}
    if len(trends) == 1 and len(structures) == 1 and next(iter(trends)) == next(iter(structures)):
        return f"aligned {next(iter(trends))}"
    if all(frame.trend_bias in {"bullish", "neutral"} and frame.structure_trend in {"bullish", "neutral"} for frame in ready):
        return "mostly bullish"
    if all(frame.trend_bias in {"bearish", "neutral"} and frame.structure_trend in {"bearish", "neutral"} for frame in ready):
        return "mostly bearish"
    return "mixed"


def _risk_note(frames: list[TimeframeAnalysis], bias: str) -> str:
    unavailable = [frame.timeframe for frame in frames if frame.status != "ready"]
    if unavailable:
        return f"{bias}; verify unavailable/insufficient timeframe(s): {', '.join(unavailable)}."
    if bias == "mixed/caution":
        return "Timeframes disagree. Prefer confirmation over directional conviction."
    return f"{bias}; still validate support/resistance and news/fundamental context before acting."
