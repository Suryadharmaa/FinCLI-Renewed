"""Source quality and freshness scoring for market data (Phase 0.5.0).

This produces a numeric freshness score and a source grade independent of the
raw provider status string kept on ``DataQualityReport.freshness``. It blends
quote freshness, OHLCV depth, news recency, and fundamentals coverage so that
``/research`` and ``/market`` can show how trustworthy the underlying sources
are right now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.providers.reliability import STATUS_DELAYED, STATUS_OK


@dataclass(frozen=True, slots=True)
class SourceQualityScore:
    freshness_score: int
    freshness_label: str
    source_grade: str
    realtime_label: str
    detail: str

    def compact(self) -> str:
        return (
            f"freshness={self.freshness_score}/100 ({self.freshness_label}) | "
            f"grade={self.source_grade} | {self.realtime_label}"
        )


def _news_age_hours(news: list[NewsItem]) -> float | None:
    timestamps = [item.published_at for item in news if item.published_at is not None]
    if not timestamps:
        return None
    now = datetime.now(timezone.utc)
    ages: list[float] = []
    for published in timestamps:
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        ages.append((now - published).total_seconds() / 3600.0)
    return min(ages)


def _grade(score: int) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    if score >= 30:
        return "D"
    return "E"


def score_source_quality(
    quote: Quote,
    candles: list[Candle],
    news: list[NewsItem],
    fundamentals: FundamentalSnapshot | None,
) -> SourceQualityScore:
    """Score how fresh and well-sourced the available market data is."""
    score = 0
    details: list[str] = []

    status = (quote.status or "unknown").lower()
    if quote.price is None:
        realtime_label = STATUS_DELAYED
        details.append("quote price missing")
    elif status in {"realtime", "live"}:
        score += 45
        realtime_label = STATUS_OK
        details.append("realtime quote")
    elif status in {"delayed", "cached", "fallback"}:
        score += 28
        realtime_label = STATUS_DELAYED
        details.append(f"{status} quote")
    else:
        score += 22
        realtime_label = STATUS_DELAYED
        details.append(f"{status} quote")

    if candles:
        score += 25 if len(candles) >= 120 else 15 if len(candles) >= 20 else 6
        details.append(f"{len(candles)} candles")
    else:
        details.append("no OHLCV")

    age_hours = _news_age_hours(news)
    if age_hours is None:
        if news:
            score += 8
            details.append(f"{len(news)} news (undated)")
        else:
            details.append("no news")
    elif age_hours <= 24:
        score += 22
        details.append("news <24h")
    elif age_hours <= 72:
        score += 14
        details.append("news <72h")
    elif age_hours <= 168:
        score += 8
        details.append("news <7d")
    else:
        score += 3
        details.append("news >7d old")

    if fundamentals is not None:
        score += 8
        details.append("fundamentals present")

    freshness_score = min(score, 100)
    if freshness_score >= 80:
        freshness_label = "fresh"
    elif freshness_score >= 55:
        freshness_label = "usable"
    elif freshness_score >= 30:
        freshness_label = "stale"
    else:
        freshness_label = "weak"

    return SourceQualityScore(
        freshness_score=freshness_score,
        freshness_label=freshness_label,
        source_grade=_grade(freshness_score),
        realtime_label=realtime_label,
        detail="; ".join(details),
    )
