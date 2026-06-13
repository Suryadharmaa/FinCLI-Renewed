"""Macro data service with offline-first fallback rows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class MacroIndicator:
    name: str
    region: str
    value: str
    period: str
    source: str
    note: str


class MacroDataService:
    """Return macro context from free fallback datasets.

    v0.2.2 keeps this deterministic/offline so /macro remains usable without API keys.
    Provider-backed DBnomics/FRED/World Bank adapters can hydrate this shape later.
    """

    def indicators(self, query: str = "") -> list[MacroIndicator]:
        normalized = query.strip().lower()
        rows = _fallback_rows()
        if not normalized:
            return rows
        filtered = [
            row
            for row in rows
            if normalized in row.region.lower()
            or normalized in row.name.lower()
            or normalized in row.note.lower()
        ]
        return filtered or rows[:5]


def _fallback_rows() -> list[MacroIndicator]:
    period = date.today().strftime("%Y")
    return [
        MacroIndicator("Policy Rate", "United States", "provider required", period, "Fallback", "Watch FRED/Fed data for rate path."),
        MacroIndicator("Inflation", "United States", "provider required", period, "Fallback", "CPI trend drives USD, yields, and risk assets."),
        MacroIndicator("GDP Growth", "World", "provider required", period, "Fallback", "Use World Bank/IMF for actual country values."),
        MacroIndicator("Policy Rate", "Indonesia", "provider required", period, "Fallback", "BI rate, USD strength, and capital flow affect IDR."),
        MacroIndicator("Inflation", "Indonesia", "provider required", period, "Fallback", "Inflation surprise can affect BI policy expectations."),
        MacroIndicator("PMI", "Euro Area", "provider required", period, "Fallback", "Growth momentum proxy for EUR and European equities."),
    ]
