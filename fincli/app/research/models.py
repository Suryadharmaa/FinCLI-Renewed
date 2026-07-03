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
