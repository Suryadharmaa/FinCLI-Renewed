"""Standard data quality report model for FinCLI outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    score: int
    quote: str
    ohlcv: str
    news: str
    fundamentals: str
    provider: str
    tier: str
    freshness: str
    reliability_status: str
    missing_fields: tuple[str, ...]
    label: str

    def compact(self) -> str:
        missing = ", ".join(self.missing_fields) if self.missing_fields else "none"
        return (
            f"{self.score}/100 | tier={self.tier} | reliability={self.reliability_status} | "
            f"freshness={self.freshness} | missing={missing}"
        )
