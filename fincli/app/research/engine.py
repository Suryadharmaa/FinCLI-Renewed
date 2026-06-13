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
                decision_points=brief.decision_points,
                risks=brief.risks,
                final_summary=brief.final_summary,
                ai_summary=response.content,
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

    risks = [
        f"Data quality {overview.data_quality.score}/100; provider label {overview.data_quality.provider}.",
        "Use confirmation and invalidation; do not treat this brief as financial advice.",
    ]
    if structure.change_of_character:
        risks.append("Change of character detected; directional confidence should be reduced.")
    if technical.rsi is not None and (technical.rsi > 75 or technical.rsi < 25):
        risks.append("RSI is at an extreme; avoid chasing without confirmation.")

    final_summary = (
        f"{overview.symbol} is a {technical.trend_bias} / {structure.trend} setup with "
        f"{overview.data_quality.score}/100 data quality. Focus on support/resistance reaction and news/fundamental confirmation."
    )
    return ResearchBrief(
        symbol=overview.symbol,
        mode=mode,
        overview=overview,
        decision_points=decision_points[:6],
        risks=risks[:4],
        final_summary=final_summary,
    )
