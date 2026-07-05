"""Research workspace orchestration (Research Engine v3)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from fincli.app.providers.ai.base import AIRequest, BaseAIProvider
from fincli.app.research.models import (
    MissingDataItem,
    ResearchBrief,
    ResearchCitation,
    ResearchFact,
    ResearchInference,
    ResearchScenario,
    ResearchSource,
    ResearchTrustSummary,
)
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
        if mode in {"deep", "report"} and self.ai_provider is not None:
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
    citations = _build_citations(sources, overview)
    citation_ids = tuple(citation.id for citation in citations[:3])
    trust_summary = ResearchTrustSummary(
        label=trust_gate.level,
        confidence_cap=float(trust_gate.confidence_cap),
        max_signal_strength=trust_gate.max_signal_strength,
        verification_steps=trust_gate.required_verification,
    )
    facts = _build_facts(overview, citations)
    inferences = _build_inferences(signal, risk, trust_gate.confidence_cap, citation_ids)
    missing_data_items = _build_missing_data_items(overview)
    scenario_matrix = _build_scenarios(overview, trust_gate.confidence_cap, citation_ids)
    report_notes = (
        f"Snapshot: {snapshot}",
        f"Signal: {signal}",
        f"Risk: {risk}",
        f"Context: {context_blend}",
        f"Missing data: {missing_data}",
        f"Source quality: {source_quality}",
        f"Sources cited: {len(sources)}",
        f"Trust cap: {trust_gate.confidence_cap}%",
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
        citations=citations,
        facts=facts,
        inferences=inferences,
        missing_data_items=missing_data_items,
        scenario_matrix=scenario_matrix,
        trust_summary=trust_summary,
    )


def _build_citations(sources: tuple[ResearchSource, ...], overview: MarketOverview) -> tuple[ResearchCitation, ...]:
    citations: list[ResearchCitation] = []
    for index, source in enumerate(sources):
        score = max(0.0, min(100.0, float(overview.data_quality.score))) if source.kind == "market" else 70.0
        freshness = overview.data_quality.freshness if source.kind == "market" else "source-reported"
        reliability = overview.data_quality.reliability_status if source.kind == "market" else "unverified"
        citations.append(
            ResearchCitation(
                id=_citation_id(index),
                title=source.title,
                source=source.detail or source.kind,
                url=source.url or None,
                score=score,
                freshness=freshness,
                reliability=reliability,
                evidence_kind=source.kind,
            )
        )
    return tuple(citations)


def _build_facts(overview: MarketOverview, citations: tuple[ResearchCitation, ...]) -> tuple[ResearchFact, ...]:
    market_id = (citations[0].id,) if citations else ()
    facts = [
        ResearchFact(
            f"{overview.symbol} quote is {overview.quote.price} {overview.quote.currency} via {overview.quote.provider} ({overview.quote.status}).",
            market_id,
        ),
        ResearchFact(
            f"Technical trend bias is {overview.technical.trend_bias}; market structure is {overview.structure.trend}.",
            market_id,
        ),
        ResearchFact(
            f"Data quality score is {overview.data_quality.score}/100 with reliability {overview.data_quality.reliability_status}.",
            market_id,
        ),
    ]
    if overview.fundamentals is not None:
        facts.append(
            ResearchFact(
                f"Fundamentals provider reports sector {overview.fundamentals.sector or 'N/A'} and P/E {overview.fundamentals.pe_ratio}.",
                tuple(citation.id for citation in citations if citation.evidence_kind in {"fundamentals", "market"})[:2],
            )
        )
    if overview.news:
        news_ids = tuple(citation.id for citation in citations if citation.evidence_kind in {"news", "web"})
        facts.append(ResearchFact(f"Latest cited news: {overview.news[0].title} ({overview.news[0].source}).", news_ids[:2]))
    return tuple(facts)


def _build_inferences(signal: str, risk: str, confidence_cap: int, citation_ids: tuple[str, ...]) -> tuple[ResearchInference, ...]:
    confidence = _confidence_from_trust(float(confidence_cap), 55.0)
    return (
        ResearchInference(f"Signal interpretation: {signal}", citation_ids, confidence),
        ResearchInference(f"Primary risk interpretation: {risk}", citation_ids, _confidence_from_trust(float(confidence_cap), 50.0)),
    )


def _build_missing_data_items(overview: MarketOverview) -> tuple[MissingDataItem, ...]:
    items: list[MissingDataItem] = []
    for field in overview.data_quality.missing_fields:
        severity = "high" if field in {"quote", "ohlcv", "history"} else "medium" if field in {"news", "fundamentals"} else "low"
        items.append(MissingDataItem(field=field, severity=severity, impact=f"Missing {field} lowers research confidence."))
    if not items:
        return ()
    return tuple(items)


def _build_scenarios(overview: MarketOverview, confidence_cap: int, citation_ids: tuple[str, ...]) -> tuple[ResearchScenario, ...]:
    support = overview.technical.support
    resistance = overview.technical.resistance
    cap = float(confidence_cap)
    return (
        ResearchScenario(
            name="Bull",
            thesis="Upside scenario if price confirms above resistance with improving momentum.",
            trigger=f"Break and hold above resistance {resistance}.",
            invalidation=f"Failure back below support {support} or trust gate deterioration.",
            confidence=_confidence_from_trust(cap, 55.0),
            citation_ids=citation_ids,
        ),
        ResearchScenario(
            name="Base",
            thesis="Wait-for-confirmation scenario while signal and risk remain mixed.",
            trigger="Clean retest near key level with provider data still usable.",
            invalidation="New missing critical data or failed retest.",
            confidence=_confidence_from_trust(cap, 60.0),
            citation_ids=citation_ids,
        ),
        ResearchScenario(
            name="Bear",
            thesis="Downside scenario if support fails or structure turns bearish.",
            trigger=f"Break below support {support} with weak momentum.",
            invalidation=f"Recovery above resistance {resistance} with stronger data quality.",
            confidence=_confidence_from_trust(cap, 50.0),
            citation_ids=citation_ids,
        ),
    )


def _citation_id(index: int) -> str:
    return f"S{index + 1}"


def _confidence_from_trust(cap: float, requested: float) -> float:
    return min(cap, requested)


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
