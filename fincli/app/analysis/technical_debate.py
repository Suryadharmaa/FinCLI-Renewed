"""Multi-perspective technical debate for signal validation."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.analysis.indicators import TechnicalSummary
from fincli.app.analysis.market_structure import MarketStructureSummary
from fincli.app.analysis.technical_signal import TechnicalSignal, evaluate_technical_signal
from fincli.app.providers.market.base import Candle


@dataclass(frozen=True, slots=True)
class ChooserCase:
    name: str
    stance: str
    score: int
    evidence: list[str]
    objections: list[str]


@dataclass(frozen=True, slots=True)
class TechnicalDebate:
    bull_case: ChooserCase
    bear_case: ChooserCase
    caution_case: ChooserCase
    judge_signal: TechnicalSignal
    judge_reasoning: list[str]


def run_technical_debate(
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
    candles: list[Candle],
) -> TechnicalDebate:
    """Run bull/bear/caution choosers and a deterministic judge.

    The judge intentionally rewards aligned evidence and penalizes unresolved conflict.
    This keeps /technical from presenting buy/sell labels without an explicit audit trail.
    """

    bull_case = _build_bull_case(technical, structure, candles)
    bear_case = _build_bear_case(technical, structure, candles)
    caution_case = _build_caution_case(technical, structure, candles, bull_case, bear_case)
    base_signal = evaluate_technical_signal(technical, structure, candles)
    judge_signal, judge_reasoning = _judge(base_signal, bull_case, bear_case, caution_case, technical, structure)
    return TechnicalDebate(
        bull_case=bull_case,
        bear_case=bear_case,
        caution_case=caution_case,
        judge_signal=judge_signal,
        judge_reasoning=judge_reasoning,
    )


def format_debate(debate: TechnicalDebate) -> str:
    return (
        "Technical Debate:\n"
        f"{_format_case(debate.bull_case)}\n"
        f"{_format_case(debate.bear_case)}\n"
        f"{_format_case(debate.caution_case)}\n"
        f"Judge Verdict: {debate.judge_signal.label}\n"
        f"Judge Score: {debate.judge_signal.score}\n"
        f"Judge Confidence: {debate.judge_signal.confidence}\n"
        "Judge Reasoning:\n"
        f"{chr(10).join(f'- {reason}' for reason in debate.judge_reasoning)}"
    )


def _build_bull_case(
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
    candles: list[Candle],
) -> ChooserCase:
    score = 0
    evidence: list[str] = []
    objections: list[str] = []

    if technical.trend_bias == "bullish":
        score += 2
        evidence.append("Trend bias bullish from moving-average alignment.")
    else:
        objections.append(f"Trend bias is {technical.trend_bias}, not bullish.")

    if structure.trend == "bullish":
        score += 2
        evidence.append(f"Market structure supports upside: {structure.latest_pattern}.")
    else:
        objections.append(f"Market structure is {structure.trend}.")

    if technical.macd is not None and technical.macd_signal is not None and technical.macd > technical.macd_signal:
        score += 1
        evidence.append("MACD is above signal, showing improving momentum.")
    if technical.rsi is not None and 45 <= technical.rsi <= 70:
        score += 1
        evidence.append("RSI is constructive without severe overbought pressure.")
    elif technical.rsi is not None and technical.rsi > 75:
        objections.append("RSI is extended; bullish continuation needs confirmation.")

    if _volume_ratio(candles) >= 1.15:
        score += 1
        evidence.append("Latest volume is above recent average.")

    if not evidence:
        evidence.append("Bull chooser found no strong upside evidence.")
    return ChooserCase("Bull Chooser", "buy candidate", score, evidence[:5], objections[:4])


def _build_bear_case(
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
    candles: list[Candle],
) -> ChooserCase:
    score = 0
    evidence: list[str] = []
    objections: list[str] = []

    if technical.trend_bias == "bearish":
        score += 2
        evidence.append("Trend bias bearish from moving-average alignment.")
    else:
        objections.append(f"Trend bias is {technical.trend_bias}, not bearish.")

    if structure.trend == "bearish":
        score += 2
        evidence.append(f"Market structure supports downside: {structure.latest_pattern}.")
    else:
        objections.append(f"Market structure is {structure.trend}.")

    if technical.macd is not None and technical.macd_signal is not None and technical.macd < technical.macd_signal:
        score += 1
        evidence.append("MACD is below signal, showing weakening momentum.")
    if technical.rsi is not None and technical.rsi > 75:
        score += 1
        evidence.append("RSI is overbought; pullback risk is elevated.")
    elif technical.rsi is not None and technical.rsi < 30:
        objections.append("RSI is oversold; bearish continuation may be crowded.")

    if _volume_ratio(candles) >= 1.15 and technical.trend_bias == "bearish":
        score += 1
        evidence.append("Above-average volume supports bearish participation.")

    if not evidence:
        evidence.append("Bear chooser found no strong downside evidence.")
    return ChooserCase("Bear Chooser", "sell candidate", score, evidence[:5], objections[:4])


def _build_caution_case(
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
    candles: list[Candle],
    bull_case: ChooserCase,
    bear_case: ChooserCase,
) -> ChooserCase:
    score = 0
    evidence: list[str] = []
    objections: list[str] = []

    if abs(bull_case.score - bear_case.score) <= 2:
        score += 2
        evidence.append("Bull and bear evidence are close enough to treat the setup as conflicted.")
    if technical.trend_bias == "neutral" or structure.trend == "neutral":
        score += 2
        evidence.append("Trend or structure is neutral/ranging.")
    if structure.change_of_character:
        score += 2
        evidence.append("Change of character detected; market may be transitioning.")
    if technical.rsi is not None and (technical.rsi > 75 or technical.rsi < 25):
        score += 1
        evidence.append("RSI is at an extreme; chase risk is elevated.")
    if _atr_percent(technical.atr, technical.latest_close) >= 5:
        score += 1
        evidence.append("ATR is high relative to price; volatility risk is elevated.")
    if _volume_ratio(candles) < 0.75:
        score += 1
        evidence.append("Volume participation is below recent average.")

    if score < 2:
        objections.append("Caution chooser found limited risk flags.")
    if not evidence:
        evidence.append("No dominant caution flag, but confirmation is still required.")
    return ChooserCase("Caution Chooser", "wait/avoid overconfidence", score, evidence[:5], objections[:4])


def _judge(
    base_signal: TechnicalSignal,
    bull_case: ChooserCase,
    bear_case: ChooserCase,
    caution_case: ChooserCase,
    technical: TechnicalSummary,
    structure: MarketStructureSummary,
) -> tuple[TechnicalSignal, list[str]]:
    reasoning: list[str] = []
    net = bull_case.score - bear_case.score

    if caution_case.score >= 4 and abs(net) <= 3:
        reasoning.append("Caution wins because directional evidence is mixed while risk flags are elevated.")
        return _replace_signal(base_signal, "CAUTION", net, "medium"), reasoning

    if bull_case.score >= bear_case.score + 3 and caution_case.score <= 3:
        reasoning.append("Bull wins because upside evidence is materially stronger than downside evidence.")
        reasoning.append("Judge still requires confirmation near key levels and invalidation below support.")
        return _replace_signal(base_signal, "BEST TO BUY", max(net, base_signal.score), base_signal.confidence), reasoning

    if bear_case.score >= bull_case.score + 3 and caution_case.score <= 3:
        reasoning.append("Bear wins because downside evidence is materially stronger than upside evidence.")
        reasoning.append("Judge still requires confirmation near key levels and invalidation above resistance.")
        return _replace_signal(base_signal, "BEST TO SELL", min(net, base_signal.score), base_signal.confidence), reasoning

    reasoning.append("Caution wins because bull/bear arguments are mixed or confirmation quality is insufficient.")
    if technical.trend_bias != structure.trend:
        reasoning.append("Trend bias and market structure conflict, so judge avoids a strong directional label.")
    return _replace_signal(base_signal, "CAUTION", net, "low"), reasoning


def _replace_signal(signal: TechnicalSignal, label: str, score: int, confidence: str) -> TechnicalSignal:
    return TechnicalSignal(
        label=label,
        score=score,
        confidence=confidence,
        reasons=signal.reasons,
        risk_notes=signal.risk_notes,
        invalidation=signal.invalidation,
    )


def _format_case(case: ChooserCase) -> str:
    evidence = "\n".join(f"  + {item}" for item in case.evidence)
    objections = "\n".join(f"  - {item}" for item in case.objections) if case.objections else "  - No major objection."
    return (
        f"{case.name}: {case.stance} | Score {case.score}\n"
        f"Evidence:\n{evidence}\n"
        f"Objections:\n{objections}"
    )


def _volume_ratio(candles: list[Candle]) -> float:
    recent = candles[-20:]
    if len(recent) < 2:
        return 1.0
    volumes = [float(candle.volume) for candle in recent]
    average = sum(volumes) / len(volumes)
    if average == 0:
        return 1.0
    return volumes[-1] / average


def _atr_percent(atr: float | None, price: float | None) -> float:
    if atr is None or price is None or price == 0:
        return 0.0
    return abs(atr / price) * 100
