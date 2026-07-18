"""Analysis prompt orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fincli.app.analysis.ai_prompts import MARKET_ANALYSIS_PROMPT
from fincli.app.analysis.technical_debate import format_debate, run_technical_debate
from fincli.app.analysis.technical_signal import format_signal
from fincli.app.analysis.trading_methods import analyze_trading_methods, format_trading_methods_context

if TYPE_CHECKING:
    from fincli.app.analysis.indicators import TechnicalSummary
    from fincli.app.analysis.market_structure import MarketStructureSummary
    from fincli.app.providers.market.base import Candle


def market_analysis_prompt() -> str:
    """Return the configured market analysis prompt template."""
    return MARKET_ANALYSIS_PROMPT.strip()


def build_market_analysis_prompt(
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    technical: TechnicalSummary,
    structure: MarketStructureSummary | None = None,
    news_context: str = "No news/fundamental context provided.",
    user_gameplay_context: str = "User Gameplay Profile: not configured.",
    trading_methods_context: str = "",
    grounding_context: str = "",
) -> str:
    """Build a structured AI prompt from market data and computed indicators."""
    recent = candles[-8:]
    ohlcv_header = "Datetime           | O       | H       | L       | C       | Volume"
    ohlcv_lines = [
        (
            f"{candle.timestamp.strftime('%Y-%m-%d %H:%M'):18s} | "
            f"{candle.open:7.2f} | {candle.high:7.2f} | {candle.low:7.2f} | "
            f"{candle.close:7.2f} | {_compact_vol(candle.volume)}"
        )
        for candle in recent
    ]
    indicators = (
        f"Close={_fmt(technical.latest_close)} Trend={technical.trend_bias} "
        f"SMA({_fmt(technical.sma_fast)},{_fmt(technical.sma_slow)}) "
        f"EMA={_fmt(technical.ema_fast)} RSI={_fmt(technical.rsi)} "
        f"MACD({_fmt(technical.macd)},{_fmt(technical.macd_signal)}) "
        f"BB({_fmt(technical.bollinger_lower)},{_fmt(technical.bollinger_upper)}) "
        f"ATR={_fmt(technical.atr)} S={_fmt(technical.support)} R={_fmt(technical.resistance)}"
    )
    debate = run_technical_debate(technical, structure, candles) if structure is not None else None
    struct_text = _format_structure(structure)
    signal_text = format_signal(debate.judge_signal) if debate is not None else "N/A"
    methods = trading_methods_context or format_trading_methods_context(analyze_trading_methods(candles))
    return (
        f"{market_analysis_prompt()}\n\n"
        f"Symbol: {symbol} | TF: {timeframe} | Candles: {len(candles)}\n\n"
        f"Trust:\n{grounding_context or 'unknown'}\n\n"
        f"OHLCV (last {len(recent)}):\n{ohlcv_header}\n{chr(10).join(ohlcv_lines)}\n\n"
        f"Indicators: {indicators}\n\n"
        f"Structure: {struct_text}\n\n"
        f"Signal: {signal_text}\n\n"
        f"Debate: {format_debate(debate) if debate is not None else 'N/A'}\n\n"
        f"Methods: {methods}\n\n"
        f"Profile: {user_gameplay_context}\n\n"
        f"News: {news_context}"
    )


def build_technical_ai_summary(symbol: str, timeframe: str, candles: list[Candle]) -> str:
    """Build a concise technical summary intended as AI assistant context."""
    from fincli.app.analysis.indicators import summarize_technical_indicators
    from fincli.app.analysis.market_structure import analyze_market_structure

    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)
    debate = run_technical_debate(technical, structure, candles)
    signal = debate.judge_signal
    return (
        f"Context: {symbol} {timeframe} | {len(candles)} candles\n"
        f"Close={_fmt(technical.latest_close)} Trend={technical.trend_bias} "
        f"RSI={_fmt(technical.rsi)} MACD={_fmt(technical.macd)}/{_fmt(technical.macd_signal)} "
        f"S/R={_fmt(technical.support)}/{_fmt(technical.resistance)} ATR={_fmt(technical.atr)}\n"
        f"Structure: {structure.trend}; {structure.latest_pattern}\n"
        f"Signal: {signal.label} score={signal.score} conf={signal.confidence} | {'; '.join(signal.reasons[:3])}\n"
        f"Risk: vol={_fmt(technical.atr)} liq={structure.liquidity_area or 'N/A'} zone={structure.risk_zone or 'N/A'}\n"
        "Informational only, not financial advice."
    )


def _compact_vol(volume: float) -> str:
    if volume >= 1_000_000:
        return f"{volume / 1_000_000:.1f}M"
    if volume >= 1_000:
        return f"{volume / 1_000:.0f}K"
    return f"{volume:.0f}"


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _format_structure(structure: MarketStructureSummary | None) -> str:
    if structure is None:
        return "N/A"
    return (
        f"{structure.trend} | {structure.latest_pattern} | "
        f"BOS={structure.break_of_structure} CHoCH={structure.change_of_character} | "
        f"S={_fmt(structure.support)} R={_fmt(structure.resistance)} | "
        f"liq={structure.liquidity_area or 'N/A'} risk={structure.risk_zone or 'N/A'}"
    )
