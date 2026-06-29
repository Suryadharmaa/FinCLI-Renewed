"""Market data service with provider fallback chain."""

from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import threading
from dataclasses import asdict
from datetime import datetime
from time import monotonic, perf_counter
from typing import Any, Awaitable

from fincli.app.providers.market.base import BaseMarketProvider, Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.market.symbols import SymbolResolver
from fincli.app.providers.reliability import (
    STATUS_CIRCUIT_OPEN,
    STATUS_NETWORK_ERROR,
    STATUS_OK,
    ProviderResponse,
    ProviderResult,
    classify_payload,
    classify_provider_error,
    score_quality,
)
from fincli.app.storage.market_cache import MarketCache
from fincli.app.utils.errors import ProviderError


class MarketDataService:
    """Fetch market data through a prioritized provider chain."""

    def __init__(
        self,
        providers: list[BaseMarketProvider],
        cache: MarketCache | None = None,
        cache_ttl_seconds: int = 300,
        provider_timeout_seconds: float = 12.0,
        metrics_store: Any | None = None,
        symbol_resolver: SymbolResolver | None = None,
        circuit_breaker_failure_threshold: int = 3,
        circuit_breaker_cooldown_seconds: float = 60.0,
    ) -> None:
        if not providers:
            raise ProviderError("MarketDataService requires at least one provider.")
        self.providers = providers
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds
        self.provider_timeout_seconds = max(0.05, float(provider_timeout_seconds))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_lock = threading.Lock()
        self.metrics_store = metrics_store
        self.symbol_resolver = symbol_resolver or SymbolResolver()
        self.circuit_breaker_failure_threshold = max(1, int(circuit_breaker_failure_threshold))
        self.circuit_breaker_cooldown_seconds = max(0.0, float(circuit_breaker_cooldown_seconds))
        self.last_errors: list[str] = []
        self.provider_results: deque[ProviderResult] = deque(maxlen=50)
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
        response = await self._with_fallback("quote", symbol)
        quote = response.data
        if quote is not None:
            self._cache_set("quote", cache_key, _quote_to_payload(quote))
        return quote  # type: ignore[return-value]

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        cache_key = self._cache_key(symbol, period, interval)
        cached = self._cache_get("history", cache_key)
        if isinstance(cached, list):
            return [_candle_from_payload(item) for item in cached if isinstance(item, dict)]
        response = await self._with_fallback("history", symbol, period, interval)
        candles = response.data or []
        if candles:
            self._cache_set("history", cache_key, [_candle_to_payload(candle) for candle in candles])
        return candles  # type: ignore[return-value]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        cache_key = self._cache_key(symbol, str(limit))
        cached = self._cache_get("news", cache_key)
        if isinstance(cached, list):
            return [_news_from_payload(item) for item in cached if isinstance(item, dict)]
        response = await self._with_fallback("news", symbol, limit)
        items = response.data or []
        self._cache_set("news", cache_key, [_news_to_payload(item) for item in items])
        return items  # type: ignore[return-value]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        cache_key = self._cache_key(symbol)
        cached = self._cache_get("fundamentals", cache_key)
        if isinstance(cached, dict):
            return _fundamentals_from_payload(cached)
        response = await self._with_fallback("fundamentals", symbol)
        snapshot = response.data
        if snapshot is not None:
            self._cache_set("fundamentals", cache_key, _fundamentals_to_payload(snapshot))
        return snapshot  # type: ignore[return-value]

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

    async def _with_fallback(self, method_name: str, *args: object) -> ProviderResponse[Any]:
        errors: list[str] = []
        degraded_response: ProviderResponse[Any] | None = None
        for provider in self.providers:
            provider_name = getattr(provider, "name", "unknown")
            if self._is_circuit_open(provider_name):
                message = (
                    f"{provider_name}: circuit open; skipped {method_name} for "
                    f"{self.circuit_breaker_cooldown_seconds:.0f}s cooldown"
                )
                errors.append(message)
                self._record_provider_result(
                    provider=provider_name,
                    operation=method_name,
                    status=STATUS_CIRCUIT_OPEN,
                    realtime_label=_provider_realtime_label(provider),
                    message=message,
                )
                continue
            started = perf_counter()
            try:
                method = getattr(provider, method_name)
                provider_args = self._normalize_provider_args(provider_name, method_name, args)
                payload = await asyncio.wait_for(method(*provider_args), timeout=self.provider_timeout_seconds)
                latency_ms = (perf_counter() - started) * 1000
                status, missing = classify_payload(method_name, payload)
                quality = score_quality(method_name, payload, missing)
                is_complete = status == STATUS_OK
                self._record_provider_metric(
                    provider_name,
                    operation=method_name,
                    success=is_complete,
                    latency_ms=latency_ms,
                    fallback=not is_complete,
                )
                self._record_circuit_success(provider_name)
                result = self._record_provider_result(
                    provider=provider_name,
                    operation=method_name,
                    status=status,
                    realtime_label=_provider_realtime_label(provider),
                    missing_fields=missing,
                    message="ok" if not missing else f"partial payload: {', '.join(missing)}",
                )
                response = ProviderResponse(
                    data=payload,
                    provider=provider_name,
                    operation=method_name,
                    status=status,
                    quality_score=quality,
                    latency_ms=latency_ms,
                    realtime_label=_provider_realtime_label(provider),
                    missing_fields=missing,
                    message="ok" if not missing else f"partial payload: {', '.join(missing)}",
                    raw_result=result,
                )
                if is_complete:
                    return response
                if degraded_response is None or response.quality_score > degraded_response.quality_score:
                    degraded_response = response
                errors.append(f"{provider_name}: {response.message}")
                continue
            except TimeoutError as exc:
                latency_ms = (perf_counter() - started) * 1000
                message = f"{provider_name}: {method_name} timeout after {self.provider_timeout_seconds:.1f}s"
                errors.append(message)
                self._record_provider_metric(provider_name, operation=method_name, success=False, latency_ms=latency_ms, fallback=True)
                self._record_circuit_failure(provider_name)
                self._record_provider_result(
                    provider=provider_name,
                    operation=method_name,
                    status=STATUS_NETWORK_ERROR,
                    realtime_label=_provider_realtime_label(provider),
                    message=message,
                )
            except Exception as exc:  # noqa: BLE001
                latency_ms = (perf_counter() - started) * 1000
                errors.append(f"{provider_name}: {exc}")
                self._record_provider_metric(provider_name, operation=method_name, success=False, latency_ms=latency_ms, fallback=True)
                self._record_circuit_failure(provider_name)
                self._record_provider_result(
                    provider=provider_name,
                    operation=method_name,
                    status=classify_provider_error(exc),
                    realtime_label=_provider_realtime_label(provider),
                    message=str(exc),
                )
        self.last_errors = errors
        if degraded_response is not None:
            return degraded_response
        raise ProviderError(
            f"All providers failed for {method_name}.",
            "\n".join(errors),
        )

    def _normalize_provider_args(self, provider: str, method_name: str, args: tuple[object, ...]) -> tuple[object, ...]:
        if method_name not in {"quote", "history", "news", "fundamentals"}:
            return args
        if not args or not isinstance(args[0], str):
            return args
        try:
            symbol = self.symbol_resolver.provider_symbol(provider, args[0])
        except Exception:  # noqa: BLE001
            return args
        return (symbol, *args[1:])

    def _is_circuit_open(self, provider: str) -> bool:
        metric = self.provider_metrics.setdefault(provider, ProviderRuntimeMetrics(provider))
        if not metric.circuit_open:
            return False
        if self.circuit_breaker_cooldown_seconds <= 0:
            return False
        if metric.circuit_opened_at is None:
            return False
        if monotonic() - metric.circuit_opened_at >= self.circuit_breaker_cooldown_seconds:
            metric.circuit_open = False
            metric.circuit_opened_at = None
            metric.last_status = "half_open"
            return False
        return True

    def _record_circuit_failure(self, provider: str) -> None:
        metric = self.provider_metrics.setdefault(provider, ProviderRuntimeMetrics(provider))
        metric.consecutive_failures += 1
        if metric.consecutive_failures >= self.circuit_breaker_failure_threshold:
            metric.circuit_open = True
            metric.circuit_opened_at = monotonic()
            metric.last_status = STATUS_CIRCUIT_OPEN

    def _record_circuit_success(self, provider: str) -> None:
        metric = self.provider_metrics.setdefault(provider, ProviderRuntimeMetrics(provider))
        metric.consecutive_failures = 0
        metric.circuit_open = False
        metric.circuit_opened_at = None

    def reset_circuit(self, provider_name: str) -> bool:
        """Manually reset circuit breaker for a provider. Returns True if provider found."""
        metric = self.provider_metrics.get(provider_name)
        if metric is None:
            return False
        metric.consecutive_failures = 0
        metric.circuit_open = False
        metric.circuit_opened_at = None
        metric.last_status = "reset"
        return True

    def _record_provider_result(
        self,
        provider: str,
        operation: str,
        status: str,
        realtime_label: str = "unknown",
        missing_fields: tuple[str, ...] = (),
        message: str = "",
    ) -> ProviderResult:
        result = ProviderResult(
            provider=provider,
            operation=operation,
            status=status,
            realtime_label=realtime_label,
            source=provider,
            data_quality=status,
            missing_fields=missing_fields,
            message=message,
        )
        self.provider_results.append(result)
        return result

    def _record_provider_metric(self, provider: str, operation: str = "", success: bool = True, latency_ms: float = 0.0, fallback: bool = False) -> None:
        metric = self.provider_metrics.setdefault(provider, ProviderRuntimeMetrics(provider))
        metric.record(success=success, latency_ms=latency_ms, fallback=fallback)
        if self.metrics_store is not None:
            self.metrics_store.record(provider, operation=operation, success=success, latency_ms=latency_ms, fallback=fallback)

    def provider_metrics_snapshot(self) -> dict[str, "ProviderRuntimeMetrics"]:
        return {provider: metric.copy() for provider, metric in self.provider_metrics.items()}

    def check_provider_health(self, latency_threshold_ms: float = 1500.0, error_rate_threshold: float = 20.0) -> list[dict[str, Any]]:
        """Check health of all providers and return warnings.

        Returns:
            List of health status dicts, one per provider with warnings.
        """
        results: list[dict[str, Any]] = []
        for provider_name, metric in self.provider_metrics.items():
            health = metric.health_status(latency_threshold_ms, error_rate_threshold)
            if health["warnings"]:
                results.append(health)
        return results

    @property
    def last_result(self) -> ProviderResult | None:
        return self.provider_results[-1] if self.provider_results else None

    def recent_results(self, limit: int = 10) -> list[ProviderResult]:
        return list(self.provider_results)[-limit:]

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
            with self._loop_lock:
                if self._loop is None or self._loop.is_closed():
                    self._loop = asyncio.new_event_loop()
            return self._loop.run_until_complete(awaitable)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, awaitable)
            return future.result(timeout=self.provider_timeout_seconds)


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


def _provider_realtime_label(provider: BaseMarketProvider) -> str:
    realtime = getattr(provider, "realtime", None)
    if realtime is True:
        return "realtime_or_plan_dependent"
    if realtime is False:
        return "delayed_or_fallback"
    return "unknown"


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
        self.consecutive_failures = 0
        self.circuit_open = False
        self.circuit_opened_at: float | None = None

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
        duplicate.consecutive_failures = self.consecutive_failures
        duplicate.circuit_open = self.circuit_open
        duplicate.circuit_opened_at = self.circuit_opened_at
        return duplicate

    def health_status(self, latency_threshold_ms: float = 1500.0, error_rate_threshold: float = 20.0) -> dict[str, Any]:
        """Check provider health and return status dict.

        Args:
            latency_threshold_ms: Average latency threshold in ms (default 1.5s)
            error_rate_threshold: Error rate threshold in % (default 20%)

        Returns:
            Dict with 'status', 'warnings', 'metrics' keys.
        """
        warnings: list[str] = []
        status = "ok"

        if self.calls == 0:
            return {"status": "not_called", "warnings": [], "metrics": self._summary_dict()}

        # Check error rate
        error_rate = (self.errors / self.calls * 100) if self.calls else 0
        if error_rate > error_rate_threshold:
            warnings.append(f"{self.provider}: error rate {error_rate:.1f}% (threshold: {error_rate_threshold:.0f}%)")
            status = "degraded"

        # Check latency
        avg_latency = self.avg_latency_ms
        if avg_latency > latency_threshold_ms:
            warnings.append(f"{self.provider}: avg latency {avg_latency:.0f}ms (threshold: {latency_threshold_ms:.0f}ms) — consider /provider reset {self.provider}")
            status = "degraded"

        # Check circuit breaker
        if self.circuit_open:
            warnings.append(f"{self.provider}: circuit breaker OPEN — provider is temporarily disabled")
            status = "critical"

        # Check consecutive failures
        if self.consecutive_failures >= 3:
            warnings.append(f"{self.provider}: {self.consecutive_failures} consecutive failures")
            status = "degraded"

        return {"status": status, "warnings": warnings, "metrics": self._summary_dict()}

    def _summary_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "calls": self.calls,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms,
            "errors": self.errors,
            "fallbacks": self.fallbacks,
            "circuit_open": self.circuit_open,
            "consecutive_failures": self.consecutive_failures,
        }
