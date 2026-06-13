"""Models for FinCLI research workspace."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.services.market_overview import MarketOverview


@dataclass(frozen=True, slots=True)
class ResearchBrief:
    symbol: str
    mode: str
    overview: MarketOverview
    decision_points: list[str]
    risks: list[str]
    final_summary: str
    ai_summary: str = ""
