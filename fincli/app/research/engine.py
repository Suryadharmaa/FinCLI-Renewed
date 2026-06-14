"""Research workspace orchestration."""

from __future__ import annotations

from fincli.app.providers.ai.base import AIRequest, BaseAIProvider
from fincli.app.research.models import ResearchBrief
from fincli.app.research.prompt_builder import build_research_prompt
from fincli.app.services.market_data import MarketDataService
from fincli.app.services.market_overview import MarketOverview, build_market_overview


class ResearchEngine:
    """Build compact research briefs around the existing market overview service."""

    def __init__(self, market_service: MarketDataService, ai_provider: BaseAIProvider | None = None, model: str = "") -> None:
        self.market_service = market_service
        self.ai_provider = ai_provider
        self.model = model

    async def build(self, symbol: str, timeframe: str = "1d", mode: str = "quick") -> ResearchBrief:
        overview = await build_market_overview(symbol.upper(), self.market_service, timeframe)
        brief = _brief_from_overview(overview, mode)
        if mode == "deep" and self.ai_provider is not None:
            prompt = build_research_prompt(brief)
            response = await self.ai_provider.complete(AIRequest(prompt=prompt, model=self.model))
            return ResearchBrief(
                symbol=brief.symbol,
                mode=brief.mode,
                overview=brief.overview,
                snapshot=brief.snapshot,
                signal=brief.signal,
                risk=brief.risk,
                missing_data=brief.missing_data,
                source_quality=brief.source_quality,
                decision_points=brief.decision_points,
                risks=brief.risks,
                final_summary=brief.final_summary,
                ai_summary=response.content,
                report_notes=brief.report_notes,
            )
        return brief


def _brief_from_overview(overview: MarketOverview, mode: str) -> ResearchBrief:
    technical = overview.technical
    structure = overview.structure
    fundamentals = overview.fundamentals
    decision_points = [
        f"Price {overview.quote.price} {overview.quote.currency} via {overview.quote.provider} ({overview.quote.status}).",
        f"Trend bias {technical.trend_bias}; structure {structure.trend} with {structure.latest_pattern}.",
        f"Key levels: support {technical.support}, resistance {technical.resistance}, ATR {technical.atr}.",
        f"Momentum: RSI {technical.rsi}, MACD {technical.macd}/{technical.macd_signal}.",
    ]
    if fundamentals is not None:
        decision_points.append(
            f"Fundamentals: P/E {fundamentals.pe_ratio}, EPS {fundamentals.eps}, sector {fundamentals.sector or 'N/A'}."
        )
    if overview.news:
        decision_points.append(f"Latest news: {overview.news[0].title} ({overview.news[0].source}).")

    missing_data = ", ".join(overview.data_quality.missing_fields) if overview.data_quality.missing_fields else "none"
    source_quality = (
        f"{overview.data_quality.score}/100 | reliability={overview.data_quality.reliability_status} | "
        f"provider={overview.data_quality.provider}"
    )
    signal = _research_signal(overview)
    risk = _research_risk(overview)
    snapshot = (
        f"{overview.symbol}: {technical.trend_bias} trend, {structure.trend} structure, "
        f"price {overview.quote.price} {overview.quote.currency}, data {overview.data_quality.score}/100."
    )

    risks = [
        f"Source quality: {source_quality}.",
        "Use confirmation and invalidation; do not treat this brief as financial advice.",
    ]
    if structure.change_of_character:
        risks.append("Change of character detected; directional confidence should be reduced.")
    if technical.rsi is not None and (technical.rsi > 75 or technical.rsi < 25):
        risks.append("RSI is at an extreme; avoid chasing without confirmation.")

    final_summary = _final_summary(overview, signal, risk, missing_data)
    report_notes = (
        f"Snapshot: {snapshot}",
        f"Signal: {signal}",
        f"Risk: {risk}",
        f"Missing data: {missing_data}",
        f"Source quality: {source_quality}",
        "Not financial advice.",
    )
    return ResearchBrief(
        symbol=overview.symbol,
        mode=mode,
        overview=overview,
        snapshot=snapshot,
        signal=signal,
        risk=risk,
        missing_data=missing_data,
        source_quality=source_quality,
        decision_points=decision_points[:6],
        risks=risks[:4],
        final_summary=final_summary,
        report_notes=report_notes,
    )


def _research_signal(overview: MarketOverview) -> str:
    trend = overview.technical.trend_bias.lower()
    structure = overview.structure.trend.lower()
    rsi = overview.technical.rsi
    if overview.data_quality.reliability_status != "ok":
        return "CAUTION - data incomplete; verify provider source first."
    if trend == "bullish" and structure == "bullish" and (rsi is None or rsi < 75):
        return "BULLISH WATCH - only after support/retest confirmation."
    if trend == "bearish" and structure == "bearish" and (rsi is None or rsi > 25):
        return "BEARISH WATCH - only after resistance/rejection confirmation."
    return "CAUTION - mixed or extended setup; wait for confirmation."


def _research_risk(overview: MarketOverview) -> str:
    risks: list[str] = []
    if overview.structure.change_of_character:
        risks.append("CHoCH detected")
    if overview.technical.rsi is not None and overview.technical.rsi > 75:
        risks.append("RSI overbought")
    if overview.technical.rsi is not None and overview.technical.rsi < 25:
        risks.append("RSI oversold")
    if overview.data_quality.missing_fields:
        risks.append(f"missing {', '.join(overview.data_quality.missing_fields)}")
    return "; ".join(risks) if risks else "standard market risk; define invalidation before entry"


def _final_summary(overview: MarketOverview, signal: str, risk: str, missing_data: str) -> str:
    return (
        f"{overview.symbol}: {signal}. Key risk: {risk}. "
        f"Missing data: {missing_data}. Treat this as research context, not financial advice."
    )
