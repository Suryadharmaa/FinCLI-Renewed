"""Tests for v1.0.3 Provider System v2 features."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fincli.app.providers.market.base import (
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.providers.reliability import (
    STATUS_OK,
    STATUS_PARTIAL_DATA,
    ProviderResponse,
    ProviderResult,
    score_quality,
)
from fincli.app.providers.market.symbols import SymbolResolver


# --- ProviderCapability tests ---


class TestProviderCapability:
    def test_frozen_dataclass(self):
        cap = ProviderCapability(
            name="test",
            realtime=True,
            operations=("quote", "history"),
            asset_classes=("stock",),
            rate_limit_note="60/min",
        )
        assert cap.name == "test"
        assert cap.realtime is True
        assert "quote" in cap.operations
        assert "stock" in cap.asset_classes
        assert cap.rate_limit_note == "60/min"

    def test_default_rate_limit_note(self):
        cap = ProviderCapability(name="x", realtime=False, operations=(), asset_classes=())
        assert cap.rate_limit_note == ""


# --- ProviderResponse tests ---


class TestProviderResponse:
    def test_basic_response(self):
        quote = Quote(
            symbol="AAPL",
            price=150.0,
            currency="USD",
            provider="finnhub",
            timestamp=datetime.now(timezone.utc),
            status="realtime",
        )
        resp = ProviderResponse(
            data=quote,
            provider="finnhub",
            operation="quote",
            status=STATUS_OK,
            quality_score=90,
            latency_ms=120.5,
            realtime_label="realtime",
        )
        assert resp.data is quote
        assert resp.quality_score == 90
        assert resp.latency_ms == 120.5
        assert resp.provider == "finnhub"

    def test_none_data(self):
        resp = ProviderResponse(
            data=None,
            provider="yfinance",
            operation="quote",
            status="empty_data",
            quality_score=0,
            latency_ms=50.0,
        )
        assert resp.data is None
        assert resp.quality_score == 0


# --- score_quality tests ---


class TestScoreQuality:
    def test_perfect_quote(self):
        quote = Quote(
            symbol="AAPL",
            price=150.0,
            currency="USD",
            provider="finnhub",
            timestamp=datetime.now(timezone.utc),
            status="realtime",
        )
        score = score_quality("quote", quote, ())
        assert score >= 90

    def test_quote_missing_price(self):
        quote = Quote(
            symbol="AAPL",
            price=None,
            currency="USD",
            provider="finnhub",
            timestamp=datetime.now(timezone.utc),
            status="realtime",
        )
        score = score_quality("quote", quote, ("price",))
        assert score <= 40

    def test_empty_list(self):
        score = score_quality("history", [], ())
        assert score == 10

    def test_none_payload(self):
        score = score_quality("quote", None, ())
        assert score == 0

    def test_fundamentals_missing_fields(self):
        snap = FundamentalSnapshot(symbol="AAPL", provider="yfinance", currency="USD")
        score = score_quality("fundamentals", snap, ("market_cap", "pe_ratio", "eps"))
        assert score < 60

    def test_perfect_history(self):
        candles = [
            Candle(
                timestamp=datetime.now(timezone.utc),
                open=100.0,
                high=105.0,
                low=99.0,
                close=103.0,
                volume=1000000.0,
            )
            for _ in range(20)
        ]
        score = score_quality("history", candles, ())
        assert score >= 90


# --- SymbolResolver caching tests ---


class TestSymbolResolverCaching:
    def test_search_caches_results(self):
        resolver = SymbolResolver()
        r1 = resolver.search("AAPL")
        r2 = resolver.search("AAPL")
        assert r1 == r2
        # Verify it's actually cached (same object)
        assert r1 is r2

    def test_different_queries_different_cache(self):
        resolver = SymbolResolver()
        r1 = resolver.search("AAPL")
        r2 = resolver.search("MSFT")
        assert r1 != r2

    def test_resolve_caches(self):
        resolver = SymbolResolver()
        r1 = resolver.resolve("AAPL", provider="yfinance")
        r2 = resolver.resolve("AAPL", provider="yfinance")
        assert r1 is r2


# --- Circuit breaker reset test ---


class TestCircuitBreakerReset:
    def test_reset_existing_provider(self):
        from fincli.app.services.market_data import MarketDataService

        provider = MagicMock()
        provider.name = "test_provider"
        provider.quote = MagicMock()
        service = MarketDataService([provider])
        metric = service.provider_metrics["test_provider"]
        metric.circuit_open = True
        metric.consecutive_failures = 5
        metric.circuit_opened_at = 100.0

        result = service.reset_circuit("test_provider")
        assert result is True
        assert metric.circuit_open is False
        assert metric.consecutive_failures == 0
        assert metric.last_status == "reset"

    def test_reset_nonexistent_provider(self):
        from fincli.app.services.market_data import MarketDataService

        provider = MagicMock()
        provider.name = "test_provider"
        service = MarketDataService([provider])
        result = service.reset_circuit("nonexistent")
        assert result is False


# --- Per-operation metrics test ---


class TestPerOperationMetrics:
    def test_record_per_operation(self, tmp_path):
        from fincli.app.storage.provider_metrics import ProviderMetricsStore
        from fincli.app.storage.database import FinCLIDatabase

        db = FinCLIDatabase(tmp_path / "test.db")
        store = ProviderMetricsStore(db)
        store.record("finnhub", operation="quote", success=True, latency_ms=100.0)
        store.record("finnhub", operation="quote", success=True, latency_ms=150.0)
        store.record("finnhub", operation="history", success=False, latency_ms=200.0)

        quote_metric = store.operation_snapshot("finnhub", "quote")
        assert quote_metric is not None
        assert quote_metric.calls == 2
        assert quote_metric.successes == 2
        assert quote_metric.errors == 0

        history_metric = store.operation_snapshot("finnhub", "history")
        assert history_metric is not None
        assert history_metric.calls == 1
        assert history_metric.successes == 0
        assert history_metric.errors == 1

    def test_all_operation_snapshots(self, tmp_path):
        from fincli.app.storage.provider_metrics import ProviderMetricsStore
        from fincli.app.storage.database import FinCLIDatabase

        db = FinCLIDatabase(tmp_path / "test.db")
        store = ProviderMetricsStore(db)
        store.record("finnhub", operation="quote", success=True, latency_ms=100.0)
        store.record("yfinance", operation="news", success=True, latency_ms=200.0)

        all_ops = store.all_operation_snapshots()
        assert len(all_ops) == 2
        providers = {op.provider for op in all_ops}
        assert providers == {"finnhub", "yfinance"}


# --- Version test ---


class TestVersion:
    def test_version_is_1_0_5(self):
        from fincli import __version__
        assert __version__ == "1.0.5"
