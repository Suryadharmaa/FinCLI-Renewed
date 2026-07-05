"""Models for FinCLI research workspace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fincli.app.services.market_overview import MarketOverview


@dataclass(frozen=True, slots=True)
class ResearchSource:
    """A cited source used to ground the research brief."""

    kind: str
    title: str
    detail: str = ""
    url: str = ""

    def citation(self) -> str:
        base = f"[{self.kind}] {self.title}"
        if self.detail:
            base = f"{base} - {self.detail}"
        if self.url:
            base = f"{base} ({self.url})"
        return base


@dataclass(frozen=True, slots=True)
class ResearchCitation:
    id: str
    title: str
    source: str
    url: str | None
    score: float
    freshness: str
    reliability: str
    evidence_kind: str


@dataclass(frozen=True, slots=True)
class ResearchFact:
    text: str
    citation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchInference:
    text: str
    citation_ids: tuple[str, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class MissingDataItem:
    field: str
    severity: str
    impact: str


@dataclass(frozen=True, slots=True)
class ResearchScenario:
    name: str
    thesis: str
    trigger: str
    invalidation: str
    confidence: float
    citation_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchTrustSummary:
    label: str
    confidence_cap: float
    max_signal_strength: str
    verification_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResearchBrief:
    symbol: str
    mode: str
    overview: MarketOverview
    snapshot: str
    signal: str
    risk: str
    missing_data: str
    source_quality: str
    trust_gate: str
    decision_points: list[str]
    risks: list[str]
    final_summary: str
    ai_summary: str = ""
    report_notes: tuple[str, ...] = ()
    sources: tuple[ResearchSource, ...] = ()
    context_blend: str = ""
    macro_context: tuple[str, ...] = ()
    citations: tuple[ResearchCitation, ...] = ()
    facts: tuple[ResearchFact, ...] = ()
    inferences: tuple[ResearchInference, ...] = ()
    missing_data_items: tuple[MissingDataItem, ...] = ()
    scenario_matrix: tuple[ResearchScenario, ...] = ()
    trust_summary: ResearchTrustSummary | None = None
