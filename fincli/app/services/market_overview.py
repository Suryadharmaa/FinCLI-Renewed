"""Market overview orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.analysis.market_structure import MarketStructureSummary, analyze_market_structure
from fincli.app.providers.reliability import STATUS_OK, STATUS_PARTIAL_DATA, STATUS_UNAVAILABLE
from fincli.app.services.data_quality import DataQualityReport
from fincli.app.services.source_quality import SourceQualityScore, score_source_quality
from fincli.app.utils.errors import FinCLIError

if TYPE_CHECKING:
    from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
    from fincli.app.services.market_data import MarketDataService

DataQuality = DataQualityReport


@dataclass(frozen=True, slots=True)
class MarketOverview:
    symbol: str
    timeframe: str
    quote: Quote
    candles: list[Candle]
    technical: TechnicalSummary
    structure: MarketStructureSummary
    news: list[NewsItem]
    fundamentals: FundamentalSnapshot | None
    data_quality: DataQuality
    source_quality: SourceQualityScore


async def build_market_overview(symbol: str, market_service: MarketDataService, timeframe: str = "1d") -> MarketOverview:
    """Build a compact market overview from available provider data."""
    normalized = symbol.upper()
    quote = await market_service.quote(normalized)
    candles = await market_service.history(normalized, period="6mo", interval=timeframe)
    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)

    try:
        news = await market_service.news(normalized, limit=3)
    except FinCLIError:
        news = []

    try:
        fundamentals = await market_service.fundamentals(normalized)
    except FinCLIError:
        fundamentals = None

    quality = _score_data_quality(quote, candles, news, fundamentals)
    source_quality = score_source_quality(quote, candles, news, fundamentals)
    return MarketOverview(
        symbol=normalized,
        timeframe=timeframe,
        quote=quote,
        candles=candles,
        technical=technical,
        structure=structure,
        news=news,
        fundamentals=fundamentals,
        data_quality=quality,
        source_quality=source_quality,
    )


def _score_data_quality(
    quote: Quote,
    candles: list[Candle],
    news: list[NewsItem],
    fundamentals: FundamentalSnapshot | None,
) -> DataQuality:
    score = 0
    missing: list[str] = []
    quote_status = "ok" if quote.price is not None else "missing"
    if quote.price is not None:
        score += 25
    else:
        missing.append("quote")

    candle_count = len(candles)
    if candle_count >= 120:
        ohlcv_status = f"strong ({candle_count} candles)"
        score += 35
    elif candle_count >= 20:
        ohlcv_status = f"usable ({candle_count} candles)"
        score += 25
    elif candle_count:
        ohlcv_status = f"weak ({candle_count} candles)"
        score += 10
    else:
        ohlcv_status = "missing"
        missing.append("ohlcv")

    news_status = f"{len(news)} item(s)" if news else "missing"
    if news:
        score += 15
    else:
        missing.append("news")

    fundamentals_status = "ok" if fundamentals is not None else "missing"
    if fundamentals is not None:
        score += 20
    else:
        missing.append("fundamentals")

    if quote.status == "realtime":
        score += 5

    normalized_score = min(score, 100)
    tier = _quality_tier(normalized_score)
    freshness = quote.status or "unknown"
    reliability_status = _reliability_status(missing, normalized_score)
    return DataQuality(
        score=normalized_score,
        quote=quote_status,
        ohlcv=ohlcv_status,
        news=news_status,
        fundamentals=fundamentals_status,
        provider=f"{quote.provider} ({quote.status})",
        tier=tier,
        freshness=freshness,
        reliability_status=reliability_status,
        missing_fields=tuple(missing),
        label=f"{tier} | {reliability_status} | freshness={freshness}",
    )


def _quality_tier(score: int) -> str:
    if score >= 85:
        return "strong"
    if score >= 65:
        return "usable"
    if score >= 40:
        return "partial"
    return "weak"


def _reliability_status(missing: list[str], score: int) -> str:
    if "quote" in missing or "ohlcv" in missing or score < 25:
        return STATUS_UNAVAILABLE
    if missing:
        return STATUS_PARTIAL_DATA
    return STATUS_OK
