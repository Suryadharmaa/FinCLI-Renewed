"""Research workspace orchestration (Research Engine v3)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from fincli.app.providers.ai.base import AIRequest, BaseAIProvider
from fincli.app.research.models import ResearchBrief, ResearchSource
from fincli.app.research.prompt_builder import build_research_prompt
from fincli.app.services.data_trust import build_data_trust_gate
from fincli.app.services.market_overview import MarketOverview, build_market_overview

if TYPE_CHECKING:
    from fincli.app.services.macro_data import MacroDataService, MacroIndicator
    from fincli.app.services.market_data import MarketDataService

# Modes that pull current public web context when provider news is missing.
_WEB_FALLBACK_MODES = {"deep", "report"}


class ResearchEngine:
    """Build compact research briefs around the existing market overview service.

    Research Engine v3 blends sector/macro/news context, attaches cited sources,
    and can fall back to public web research when provider news is unavailable.
    """

    def __init__(
        self,
        market_service: MarketDataService,
        ai_provider: BaseAIProvider | None = None,
        model: str = "",
        macro_service: MacroDataService | None = None,
        web_research: object | None = None,
    ) -> None:
        self.market_service = market_service
        self.ai_provider = ai_provider
        self.model = model
        self.macro_service = macro_service
        self.web_research = web_research

    async def build(self, symbol: str, timeframe: str = "1d", mode: str = "snapshot") -> ResearchBrief:
        overview = await build_market_overview(symbol.upper(), self.market_service, timeframe)
        macro_rows = self._macro_rows()
        web_sources = await self._web_sources(overview, mode)
        brief = _brief_from_overview(
            overview,
            mode,
            self.market_service.provider_metrics_snapshot(),
            macro_rows,
            web_sources,
        )
        if mode == "deep" and self.ai_provider is not None:
            prompt = build_research_prompt(brief)
            response = await self.ai_provider.complete(AIRequest(prompt=prompt, model=self.model))
            return replace(brief, ai_summary=response.content)
        return brief

    def _macro_rows(self) -> list[MacroIndicator]:
        if self.macro_service is None:
            return []
        try:
            return list(self.macro_service.indicators())[:3]
        except Exception:  # noqa: BLE001 - macro context is best-effort
            return []

    async def _web_sources(self, overview: MarketOverview, mode: str) -> list[ResearchSource]:
        if overview.news or self.web_research is None or mode not in _WEB_FALLBACK_MODES:
            return []
        try:
            results = await self.web_research.search(f"{overview.symbol} stock news", limit=3)
        except Exception:  # noqa: BLE001 - web research is a best-effort fallback
            return []
        sources: list[ResearchSource] = []
        for result in results[:3]:
            sources.append(
                ResearchSource(
                    kind="web",
                    title=getattr(result, "title", "") or "Web result",
                    detail=getattr(result, "snippet", "") or "",
                    url=getattr(result, "url", "") or "",
                )
            )
        return sources


def _brief_from_overview(
    overview: MarketOverview,
    mode: str,
    provider_metrics: dict[str, object] | None = None,
    macro_rows: list[MacroIndicator] | None = None,
    web_sources: list[ResearchSource] | None = None,
) -> ResearchBrief:
    technical = overview.technical
    structure = overview.structure
    fundamentals = overview.fundamentals
    macro_rows = macro_rows or []
    web_sources = web_sources or []
    trust_gate = build_data_trust_gate(overview.data_quality, provider_metrics)
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
        f"provider={overview.data_quality.provider} | {overview.source_quality.compact()}"
    )
    signal = _research_signal(overview, trust_gate.level)
    risk = _research_risk(overview)
    snapshot = (
        f"{overview.symbol}: {technical.trend_bias} trend, {structure.trend} structure, "
        f"price {overview.quote.price} {overview.quote.currency}, data {overview.data_quality.score}/100."
    )

    macro_context = tuple(
        f"{row.name} ({row.region}): {row.value} [{row.source}]" for row in macro_rows
    )
    context_blend = _context_blend(overview, macro_context)
    sources = _build_sources(overview, macro_rows, web_sources)

    risks = [
        f"Source quality: {source_quality}.",
        f"Trust gate: {trust_gate.compact()}.",
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
        f"Context: {context_blend}",
        f"Missing data: {missing_data}",
        f"Source quality: {source_quality}",
        f"Sources cited: {len(sources)}",
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
        trust_gate=trust_gate.compact(),
        decision_points=decision_points[:6],
        risks=risks[:4],
        final_summary=final_summary,
        report_notes=report_notes,
        sources=sources,
        context_blend=context_blend,
        macro_context=macro_context,
    )


def _context_blend(overview: MarketOverview, macro_context: tuple[str, ...]) -> str:
    parts: list[str] = []
    sector = getattr(overview.fundamentals, "sector", None) if overview.fundamentals else None
    industry = getattr(overview.fundamentals, "industry", None) if overview.fundamentals else None
    if sector or industry:
        parts.append(f"Sector: {sector or 'N/A'}{f' / {industry}' if industry else ''}")
    else:
        parts.append("Sector: not provided")
    if macro_context:
        parts.append("Macro: " + "; ".join(macro_context))
    if overview.news:
        parts.append(f"News pulse: {overview.news[0].title} ({overview.news[0].source})")
    else:
        parts.append("News pulse: none from active providers")
    return " | ".join(parts)


def _build_sources(
    overview: MarketOverview,
    macro_rows: list[MacroIndicator],
    web_sources: list[ResearchSource],
) -> tuple[ResearchSource, ...]:
    sources: list[ResearchSource] = [
        ResearchSource(
            kind="market",
            title=f"{overview.quote.provider} quote/OHLCV",
            detail=f"{overview.quote.status}; {overview.source_quality.compact()}",
        )
    ]
    for item in overview.news[:3]:
        sources.append(
            ResearchSource(
                kind="news",
                title=item.title,
                detail=item.source,
                url=item.url or "",
            )
        )
    sources.extend(web_sources)
    for row in macro_rows:
        sources.append(
            ResearchSource(
                kind="macro",
                title=f"{row.name} ({row.region})",
                detail=f"{row.value} via {row.source}",
            )
        )
    if overview.fundamentals is not None:
        sources.append(
            ResearchSource(
                kind="fundamentals",
                title=f"{overview.fundamentals.provider} fundamentals",
                detail=f"sector={overview.fundamentals.sector or 'N/A'}",
            )
        )
    return tuple(sources)


def _research_signal(overview: MarketOverview, trust_level: str = "usable") -> str:
    trend = overview.technical.trend_bias.lower()
    structure = overview.structure.trend.lower()
    rsi = overview.technical.rsi
    if trust_level in {"blocked", "limited"}:
        return "CAUTION - data trust gate prevents directional signal; verify provider data first."
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
