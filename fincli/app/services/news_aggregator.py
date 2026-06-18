"""News aggregation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fincli.app.connectors.news_connectors import NewsConnectorManager
from fincli.app.providers.market.base import NewsItem
from fincli.app.providers.reliability import STATUS_OK, STATUS_PARTIAL_DATA, STATUS_UNAVAILABLE, classify_provider_error
from fincli.app.services.market_data import MarketDataService


@dataclass(frozen=True, slots=True)
class NewsDesk:
    symbol: str
    provider_chain: tuple[str, ...]
    items: list[NewsItem]
    note: str
    errors: tuple[str, ...] = ()
    lookback_days: int | None = None
    reliability_status: str = STATUS_UNAVAILABLE


class NewsAggregator:
    def __init__(
        self,
        market_service: MarketDataService,
        news_connectors: NewsConnectorManager | None = None,
        priority: list[str] | None = None,
    ) -> None:
        self.market_service = market_service
        self.news_connectors = news_connectors or NewsConnectorManager()
        self.priority = priority or ["yfinance", "google_news_rss", "yahoo_finance_rss"]

    async def latest(self, symbol: str, limit: int = 12, lookback_days: int | None = None) -> NewsDesk:
        normalized = symbol.upper()
        items: list[NewsItem] = []
        errors: list[str] = []
        seen: set[str] = set()
        provider_chain = tuple(_dedupe(self.priority))

        for provider in provider_chain:
            try:
                fetched = await self._fetch_provider(provider, normalized, max(limit - len(items), 1))
            except Exception as exc:  # noqa: BLE001 - fallback chain should continue
                errors.append(f"{provider}: {classify_provider_error(exc)} ({exc})")
                continue
            for item in fetched:
                if lookback_days is not None and not _within_lookback(item, lookback_days):
                    continue
                key = (item.url or item.title).strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    items.append(item)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break

        _min_dt = datetime.min.replace(tzinfo=timezone.utc)
        items.sort(key=lambda x: x.published_at if x.published_at and x.published_at.tzinfo else _min_dt, reverse=True)

        note = "Provider-backed news. Realtime/delayed status depends on provider entitlement."
        reliability_status = STATUS_OK
        if not items:
            note = "No news returned by active providers. Try /research <symbol> --deep or configure /news_model priority."
            reliability_status = STATUS_UNAVAILABLE if errors else STATUS_PARTIAL_DATA
        elif errors:
            note = f"{note} Fallback used after {len(errors)} provider error(s)."
            reliability_status = STATUS_PARTIAL_DATA
        return NewsDesk(normalized, provider_chain, items, note, tuple(errors), lookback_days, reliability_status)

    async def _fetch_provider(self, provider: str, symbol: str, limit: int) -> list[NewsItem]:
        if provider == "yfinance" or any(item.name == provider for item in self.market_service.providers):
            return await self.market_service.news(symbol, limit=limit)
        return await self.news_connectors.fetch(provider, symbol, limit=limit)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _within_lookback(item: NewsItem, lookback_days: int) -> bool:
    if item.published_at is None:
        return False
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    return published >= cutoff
