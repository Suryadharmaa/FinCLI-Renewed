"""Tests for v1.2.0 robustness features: session state, AI cache, soft errors."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fincli.app.providers.reliability import (
    ProviderResponse,
    build_enhanced_response,
    detect_price_anomaly,
    detect_quote_anomaly,
    detect_staleness,
)
from fincli.app.storage.ai_cache import AICache
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.session_state import SessionState, SessionStateManager

if TYPE_CHECKING:
    from pathlib import Path

# --- Session State Tests ---


class TestSessionStateManager:
    def _make_manager(self, tmp_path: Path) -> SessionStateManager:
        db = FinCLIDatabase(tmp_path / "fincli.db")
        return SessionStateManager(db)

    def test_init_session(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test-session-123")
        assert manager.current_state is not None
        assert manager.current_state.session_id == "test-session-123"

    def test_update_buffer(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test")
        manager.update_buffer("/research AAPL")
        assert manager.current_state.command_buffer == "/research AAPL"
        assert manager.current_state.is_dirty is True

    def test_add_output(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test")
        manager.add_output("AAPL: $150", "/market AAPL")
        assert len(manager.current_state.output_entries) == 1
        assert manager.current_state.output_entries[0]["command"] == "/market AAPL"

    def test_max_output_entries(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test")
        for i in range(150):
            manager.add_output(f"Entry {i}")
        assert len(manager.current_state.output_entries) == 100  # MAX_OUTPUT_ENTRIES

    def test_should_save(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test")
        assert not manager.should_save()  # Not dirty
        manager.update_buffer("test")
        assert not manager.should_save()  # Dirty but too soon
        # Simulate time passing
        manager._last_save_time = time.time() - 120
        assert manager.should_save()  # Dirty and enough time passed

    def test_save_and_recover(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test-session")
        manager.update_buffer("/research AAPL")
        manager.add_output("Result", "/research AAPL")
        manager.save(force=True)

        # Simulate crash - create new manager
        manager2 = self._make_manager(tmp_path)
        unclean = manager2.get_last_unclean_state()
        assert unclean is not None
        assert unclean.session_id == "test-session"
        assert unclean.command_buffer == "/research AAPL"

    def test_mark_clean_shutdown(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        manager.init_session("test")
        manager.save(force=True)
        manager.mark_clean_shutdown()

        # New manager should not find unclean state
        manager2 = self._make_manager(tmp_path)
        unclean = manager2.get_last_unclean_state()
        assert unclean is None

    def test_recovery_summary(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        state = SessionState(
            session_id="test-123",
            command_buffer="/research AAPL",
            output_entries=[{"text": "result"}],
            timestamp=time.time(),
        )
        summary = manager.get_recovery_summary(state)
        assert "test-123" in summary
        assert "/research AAPL" in summary
        assert "1 saved" in summary

    def test_restore_state(self, tmp_path: Path):
        manager = self._make_manager(tmp_path)
        state = SessionState(
            session_id="test",
            command_buffer="/test",
            status_bar="ready",
        )
        restored = manager.restore_state(state)
        assert restored["session_id"] == "test"
        assert restored["command_buffer"] == "/test"


# --- AI Cache Tests ---


class TestAICache:
    def _make_cache(self, tmp_path: Path) -> AICache:
        db = FinCLIDatabase(tmp_path / "fincli.db")
        return AICache(db, ttl_seconds=60)

    def test_set_and_get(self, tmp_path: Path):
        cache = self._make_cache(tmp_path)
        cache.set("What is AAPL?", "gpt-4", "AAPL is Apple Inc.")
        result = cache.get("What is AAPL?", "gpt-4")
        assert result == "AAPL is Apple Inc."

    def test_get_miss(self, tmp_path: Path):
        cache = self._make_cache(tmp_path)
        result = cache.get("Unknown prompt", "gpt-4")
        assert result is None

    def test_different_model_miss(self, tmp_path: Path):
        cache = self._make_cache(tmp_path)
        cache.set("test", "gpt-4", "response")
        result = cache.get("test", "gpt-3.5")
        assert result is None

    def test_different_context_miss(self, tmp_path: Path):
        cache = self._make_cache(tmp_path)
        cache.set("test", "gpt-4", "response", "context1")
        result = cache.get("test", "gpt-4", "context2")
        assert result is None

    def test_ttl_expiration(self, tmp_path: Path):
        db = FinCLIDatabase(tmp_path / "fincli.db")
        cache = AICache(db, ttl_seconds=1)  # 1 second TTL
        cache.set("test", "gpt-4", "response")
        time.sleep(1.5)
        result = cache.get("test", "gpt-4")
        assert result is None

    def test_invalidate_all(self, tmp_path: Path):
        cache = self._make_cache(tmp_path)
        cache.set("test1", "gpt-4", "response1")
        cache.set("test2", "gpt-4", "response2")
        count = cache.invalidate()
        assert count == 2
        assert cache.get("test1", "gpt-4") is None

    def test_stats(self, tmp_path: Path):
        cache = self._make_cache(tmp_path)
        cache.set("test", "gpt-4", "response")
        cache.get("test", "gpt-4")  # Hit
        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["total_hits"] >= 1

    def test_compute_hash_deterministic(self):
        hash1 = AICache.compute_hash("test", "gpt-4")
        hash2 = AICache.compute_hash("test", "gpt-4")
        assert hash1 == hash2

    def test_compute_hash_different(self):
        hash1 = AICache.compute_hash("test1", "gpt-4")
        hash2 = AICache.compute_hash("test2", "gpt-4")
        assert hash1 != hash2


# --- Soft Error Detection Tests ---


class TestSoftErrorDetection:
    def test_detect_staleness_fresh(self):
        freshness = datetime.now(UTC)
        assert detect_staleness(freshness) == 0.0

    def test_detect_staleness_slightly_stale(self):
        freshness = datetime.now(UTC) - timedelta(seconds=400)
        assert detect_staleness(freshness, max_age_seconds=300) == 0.5

    def test_detect_staleness_very_stale(self):
        freshness = datetime.now(UTC) - timedelta(seconds=1000)
        assert detect_staleness(freshness, max_age_seconds=300) == 1.0

    def test_detect_staleness_unknown(self):
        assert detect_staleness(None) == 0.5

    def test_detect_price_anomaly_spike(self):
        is_anomaly, flag = detect_price_anomaly(200.0, 100.0)
        assert is_anomaly is True
        assert "price_spike" in flag

    def test_detect_price_anomaly_normal(self):
        is_anomaly, flag = detect_price_anomaly(105.0, 100.0)
        assert is_anomaly is False

    def test_detect_price_anomaly_none(self):
        is_anomaly, flag = detect_price_anomaly(None, 100.0)
        assert is_anomaly is False

    def test_detect_quote_anomaly_negative_price(self):
        from dataclasses import dataclass

        @dataclass
        class MockQuote:
            price: float = -10.0
            currency: str = "USD"

        flags = detect_quote_anomaly(MockQuote())
        assert "negative_price" in flags

    def test_detect_quote_anomaly_missing_currency(self):
        from dataclasses import dataclass

        @dataclass
        class MockQuote:
            price: float = 100.0
            currency: str = ""

        flags = detect_quote_anomaly(MockQuote())
        assert "missing_currency" in flags

    def test_build_enhanced_response(self):
        response = ProviderResponse(
            data=None,
            provider="test",
            operation="quote",
            status="ok",
            quality_score=80,
            latency_ms=100.0,
        )
        enhanced = build_enhanced_response(
            response,
            data_freshness=datetime.now(UTC),
        )
        assert enhanced.staleness_score == 0.0
        assert enhanced.anomaly_flags == ()
