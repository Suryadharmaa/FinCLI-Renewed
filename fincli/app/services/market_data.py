"""Market data service with provider fallback chain."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from time import perf_counter
from typing import Any, Awaitable

from fincli.app.providers.market.base import BaseMarketProvider, Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.reliability import ProviderResult, classify_payload, classify_provider_error
from fincli.app.storage.market_cache import MarketCache
from fincli.app.utils.errors import ProviderError


class MarketDataService:
    """Fetch market data through a prioritized provider chain."""

    def __init__(
        self,
        providers: list[BaseMarketProvider],
        cache: MarketCache | None = None,
        cache_ttl_seconds: int = 300,
        metrics_store: Any | None = None,
    ) -> None:
        if not providers:
            raise ProviderError("MarketDataService membutuhkan minimal satu provider.")
        self.providers = providers
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.metrics_store = metrics_store
        self.last_errors: list[str] = []
        self.provider_results: list[ProviderResult] = []
        self.provider_metrics: dict[str, ProviderRuntimeMetrics] = {
            getattr(provider, "name", "unknown"): ProviderRuntimeMetrics(getattr(provider, "name", "unknown"))
            for provider in providers
        }

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
            provider_name = getattr(provider, "name", "unknown")
            started = perf_counter()
            try:
                method = getattr(provider, method_name)
                payload = await method(*args)
                latency_ms = (perf_counter() - started) * 1000
                status, missing = classify_payload(method_name, payload)
                self._record_provider_metric(provider_name, success=status != "partial_data", latency_ms=latency_ms)
                self._record_provider_result(
                    provider=provider_name,
                    operation=method_name,
                    status=status,
                    missing_fields=missing,
                    message="ok" if not missing else f"partial payload: {', '.join(missing)}",
                )
                return payload
            except Exception as exc:  # noqa: BLE001
                latency_ms = (perf_counter() - started) * 1000
                errors.append(f"{provider_name}: {exc}")
                self._record_provider_metric(provider_name, success=False, latency_ms=latency_ms, fallback=True)
                self._record_provider_result(
                    provider=provider_name,
                    operation=method_name,
                    status=classify_provider_error(exc),
                    message=str(exc),
                )
        self.last_errors = errors
        raise ProviderError(
            f"Semua provider gagal untuk {method_name}.",
            "\n".join(errors),
        )

    def _record_provider_result(
        self,
        provider: str,
        operation: str,
        status: str,
        missing_fields: tuple[str, ...] = (),
        message: str = "",
    ) -> None:
        self.provider_results.append(
            ProviderResult(
                provider=provider,
                operation=operation,
                status=status,
                realtime_label="unknown",
                source=provider,
                data_quality=status,
                missing_fields=missing_fields,
                message=message,
            )
        )
        if len(self.provider_results) > 50:
            self.provider_results = self.provider_results[-50:]

    def _record_provider_metric(self, provider: str, success: bool, latency_ms: float, fallback: bool = False) -> None:
        metric = self.provider_metrics.setdefault(provider, ProviderRuntimeMetrics(provider))
        metric.record(success=success, latency_ms=latency_ms, fallback=fallback)
        if self.metrics_store is not None:
            self.metrics_store.record(provider, success=success, latency_ms=latency_ms, fallback=fallback)

    def provider_metrics_snapshot(self) -> dict[str, "ProviderRuntimeMetrics"]:
        return {provider: metric.copy() for provider, metric in self.provider_metrics.items()}

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


class ProviderRuntimeMetrics:
    """Runtime metrics for one market provider."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.calls = 0
        self.successes = 0
        self.errors = 0
        self.fallbacks = 0
        self.total_latency_ms = 0.0
        self.last_status = "not_called"

    @property
    def success_rate(self) -> float:
        return (self.successes / self.calls * 100) if self.calls else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.calls) if self.calls else 0.0

    def record(self, success: bool, latency_ms: float, fallback: bool = False) -> None:
        self.calls += 1
        self.total_latency_ms += max(latency_ms, 0.0)
        if success:
            self.successes += 1
            self.last_status = "success"
        else:
            self.errors += 1
            self.last_status = "error"
        if fallback:
            self.fallbacks += 1

    def copy(self) -> "ProviderRuntimeMetrics":
        duplicate = ProviderRuntimeMetrics(self.provider)
        duplicate.calls = self.calls
        duplicate.successes = self.successes
        duplicate.errors = self.errors
        duplicate.fallbacks = self.fallbacks
        duplicate.total_latency_ms = self.total_latency_ms
        duplicate.last_status = self.last_status
        return duplicate
