"""Market data service with provider fallback chain."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from typing import Any, Awaitable

from fincli.app.providers.market.base import BaseMarketProvider, Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.storage.market_cache import MarketCache
from fincli.app.utils.errors import ProviderError


class MarketDataService:
    """Fetch market data through a prioritized provider chain."""

    def __init__(
        self,
        providers: list[BaseMarketProvider],
        cache: MarketCache | None = None,
        cache_ttl_seconds: int = 300,
    ) -> None:
        if not providers:
            raise ProviderError("MarketDataService membutuhkan minimal satu provider.")
        self.providers = providers
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.last_errors: list[str] = []

    @property
    def primary_provider(self) -> BaseMarketProvider:
        return self.providers[0]

    async def quote(self, symbol: str) -> Quote:
        cache_key = self._cache_key(symbol)
        cached = self._cache_get("quote", cache_key)
        if isinstance(cached, dict):
            return _quote_from_payload(cached)
        quote = await self._with_fallback("quote", symbol)
        self._cache_set("quote", cache_key, _quote_to_payload(quote))
        return quote

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        cache_key = self._cache_key(symbol, period, interval)
        cached = self._cache_get("history", cache_key)
        if isinstance(cached, list):
            return [_candle_from_payload(item) for item in cached if isinstance(item, dict)]
        candles = await self._with_fallback("history", symbol, period, interval)
        if candles:
            self._cache_set("history", cache_key, [_candle_to_payload(candle) for candle in candles])
        return candles

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        cache_key = self._cache_key(symbol, str(limit))
        cached = self._cache_get("news", cache_key)
        if isinstance(cached, list):
            return [_news_from_payload(item) for item in cached if isinstance(item, dict)]
        items = await self._with_fallback("news", symbol, limit)
        self._cache_set("news", cache_key, [_news_to_payload(item) for item in items])
        return items

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        cache_key = self._cache_key(symbol)
        cached = self._cache_get("fundamentals", cache_key)
        if isinstance(cached, dict):
            return _fundamentals_from_payload(cached)
        snapshot = await self._with_fallback("fundamentals", symbol)
        self._cache_set("fundamentals", cache_key, _fundamentals_to_payload(snapshot))
        return snapshot

    async def status(self) -> ProviderStatus:
        provider = self.primary_provider
        try:
            return await provider.status()
        except Exception as exc:  # noqa: BLE001
            return ProviderStatus(
                name=getattr(provider, "name", "unknown"),
                realtime=False,
                status="unavailable",
                message=str(exc),
            )

    async def _with_fallback(self, method_name: str, *args: object) -> Any:
        errors: list[str] = []
        for provider in self.providers:
            try:
                method = getattr(provider, method_name)
                return await method(*args)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{getattr(provider, 'name', 'unknown')}: {exc}")
        self.last_errors = errors
        raise ProviderError(
            f"Semua provider gagal untuk {method_name}.",
            "\n".join(errors),
        )

    def _cache_key(self, symbol: str, *parts: object) -> str:
        provider_chain = ",".join(provider.name for provider in self.providers)
        normalized = [symbol.upper(), *(str(part).lower() for part in parts), f"providers={provider_chain}"]
        return "|".join(normalized)

    def _cache_get(self, namespace: str, cache_key: str) -> dict[str, Any] | list[Any] | None:
        if self.cache is None:
            return None
        return self.cache.get(namespace, cache_key)

    def _cache_set(self, namespace: str, cache_key: str, payload: dict[str, Any] | list[Any]) -> None:
        if self.cache is None:
            return
        self.cache.set(namespace, cache_key, payload, self.cache_ttl_seconds)

    def run(self, awaitable: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, awaitable)
            return future.result()


def _quote_to_payload(quote: Quote) -> dict[str, Any]:
    payload = asdict(quote)
    payload["timestamp"] = quote.timestamp.isoformat()
    return payload


def _quote_from_payload(payload: dict[str, Any]) -> Quote:
    return Quote(
        symbol=str(payload["symbol"]),
        price=None if payload.get("price") is None else float(payload["price"]),
        currency=str(payload.get("currency", "USD")),
        provider=str(payload.get("provider", "cache")),
        timestamp=_parse_datetime(payload.get("timestamp")),
        status=str(payload.get("status", "cached")),
    )


def _candle_to_payload(candle: Candle) -> dict[str, Any]:
    payload = asdict(candle)
    payload["timestamp"] = candle.timestamp.isoformat()
    return payload


def _candle_from_payload(payload: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=_parse_datetime(payload.get("timestamp")),
        open=float(payload["open"]),
        high=float(payload["high"]),
        low=float(payload["low"]),
        close=float(payload["close"]),
        volume=float(payload.get("volume", 0)),
    )


def _news_to_payload(item: NewsItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["published_at"] = item.published_at.isoformat() if item.published_at else None
    return payload


def _news_from_payload(payload: dict[str, Any]) -> NewsItem:
    published_at = payload.get("published_at")
    return NewsItem(
        title=str(payload.get("title", "")),
        source=str(payload.get("source", "")),
        url=None if payload.get("url") is None else str(payload.get("url")),
        published_at=None if published_at is None else _parse_datetime(published_at),
        summary=str(payload.get("summary", "")),
    )


def _fundamentals_to_payload(snapshot: FundamentalSnapshot) -> dict[str, Any]:
    return asdict(snapshot)


def _fundamentals_from_payload(payload: dict[str, Any]) -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=str(payload["symbol"]),
        provider=str(payload.get("provider", "cache")),
        currency=str(payload.get("currency", "USD")),
        market_cap=_optional_float(payload.get("market_cap")),
        pe_ratio=_optional_float(payload.get("pe_ratio")),
        eps=_optional_float(payload.get("eps")),
        revenue=_optional_float(payload.get("revenue")),
        beta=_optional_float(payload.get("beta")),
        sector=None if payload.get("sector") is None else str(payload.get("sector")),
        industry=None if payload.get("industry") is None else str(payload.get("industry")),
    )


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
