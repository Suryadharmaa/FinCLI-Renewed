"""Analysis prompt orchestration."""

from __future__ import annotations

from fincli.app.analysis.ai_prompts import MARKET_ANALYSIS_PROMPT
from fincli.app.analysis.indicators import TechnicalSummary
from fincli.app.analysis.market_structure import MarketStructureSummary
from fincli.app.analysis.technical_debate import format_debate, run_technical_debate
from fincli.app.analysis.technical_signal import format_signal
from fincli.app.analysis.trading_methods import analyze_trading_methods, format_trading_methods_context
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
) -> str:
    """Build a structured AI prompt from market data and computed indicators."""
    recent = candles[-10:]
    ohlcv_lines = [
        (
            f"- {candle.timestamp.isoformat(timespec='seconds')}: "
            f"O={candle.open:.4f} H={candle.high:.4f} L={candle.low:.4f} "
            f"C={candle.close:.4f} V={candle.volume:.0f}"
        )
        for candle in recent
    ]
    indicator_lines = [
        f"Latest Close: {_fmt(technical.latest_close)}",
        f"Trend Bias: {technical.trend_bias}",
        f"SMA 5: {_fmt(technical.sma_fast)}",
        f"SMA 20: {_fmt(technical.sma_slow)}",
        f"EMA 12: {_fmt(technical.ema_fast)}",
        f"RSI 14: {_fmt(technical.rsi)}",
        f"MACD: {_fmt(technical.macd)}",
        f"MACD Signal: {_fmt(technical.macd_signal)}",
        f"Bollinger Upper: {_fmt(technical.bollinger_upper)}",
        f"Bollinger Lower: {_fmt(technical.bollinger_lower)}",
        f"ATR 14: {_fmt(technical.atr)}",
        f"Support: {_fmt(technical.support)}",
        f"Resistance: {_fmt(technical.resistance)}",
    ]
    debate = run_technical_debate(technical, structure, candles) if structure is not None else None
    return (
        f"{market_analysis_prompt()}\n\n"
        f"Instrument: {symbol}\n"
        f"Timeframe: {timeframe}\n"
        f"Data Quality: {len(candles)} candles available from provider.\n\n"
        "Recent OHLCV:\n"
        f"{chr(10).join(ohlcv_lines)}\n\n"
        "Computed Indicators:\n"
        f"{chr(10).join(indicator_lines)}\n\n"
        "Market Structure:\n"
        f"{_format_structure(structure)}\n\n"
        "Signal Assessment:\n"
        f"{format_signal(debate.judge_signal) if debate is not None else 'No signal assessment available.'}\n\n"
        "Technical Debate:\n"
        f"{format_debate(debate) if debate is not None else 'No technical debate available.'}\n\n"
        "Trading Method Context:\n"
        f"{trading_methods_context or format_trading_methods_context(analyze_trading_methods(candles))}\n\n"
        "User Gameplay Context:\n"
        f"{user_gameplay_context}\n\n"
        "News/Fundamental Context:\n"
        f"{news_context}\n"
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
        "AI Assistance Summary:\n"
        f"Instrument: {symbol}\n"
        f"Timeframe: {timeframe}\n"
        f"Data Quality: {len(candles)} candles\n"
        f"Latest Close: {_fmt(technical.latest_close)}\n"
        f"Trend Bias: {technical.trend_bias}\n"
        f"RSI 14: {_fmt(technical.rsi)}\n"
        f"MACD/Signal: {_fmt(technical.macd)} / {_fmt(technical.macd_signal)}\n"
        f"Support/Resistance: {_fmt(technical.support)} / {_fmt(technical.resistance)}\n"
        f"ATR 14: {_fmt(technical.atr)}\n"
        f"Market Structure: {structure.trend}; {structure.latest_pattern}\n"
        f"Signal: {signal.label} | Score {signal.score} | Confidence {signal.confidence}\n"
        f"Signal Reasoning: {'; '.join(signal.reasons[:3])}\n"
        f"Debate Judge: {signal.label}; {'; '.join(debate.judge_reasoning[:2])}\n"
        f"Risk Notes: volatility={_fmt(technical.atr)}, liquidity={structure.liquidity_area or 'N/A'}, risk_zone={structure.risk_zone or 'N/A'}\n"
        "Use this as context for scenario analysis. This is informational, not financial advice."
    )


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _format_structure(structure: MarketStructureSummary | None) -> str:
    if structure is None:
        return "No market structure context provided."
    return (
        f"Trend: {structure.trend}\n"
        f"Latest Pattern: {structure.latest_pattern}\n"
        f"Break of Structure: {structure.break_of_structure}\n"
        f"Change of Character: {structure.change_of_character}\n"
        f"Support: {_fmt(structure.support)}\n"
        f"Resistance: {_fmt(structure.resistance)}\n"
        f"Liquidity Area: {structure.liquidity_area or 'N/A'}\n"
        f"Risk Zone: {structure.risk_zone or 'N/A'}"
    )
