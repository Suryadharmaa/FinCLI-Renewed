"""Persistent provider metrics storage."""

from __future__ import annotations

from fincli.app.services.market_data import ProviderRuntimeMetrics
from fincli.app.storage.database import FinCLIDatabase


class ProviderMetricsStore:
    """Persist aggregate provider metrics across FinCLI sessions."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def record(self, provider: str, success: bool, latency_ms: float, fallback: bool = False) -> None:
        current = self.snapshot().get(provider, ProviderRuntimeMetrics(provider))
        current.record(success=success, latency_ms=latency_ms, fallback=fallback)
        self.db.execute(
            """
            INSERT INTO provider_metrics(provider, calls, successes, errors, fallbacks, total_latency_ms, last_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider) DO UPDATE SET
                calls=excluded.calls,
                successes=excluded.successes,
                errors=excluded.errors,
                fallbacks=excluded.fallbacks,
                total_latency_ms=excluded.total_latency_ms,
                last_status=excluded.last_status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                current.provider,
                current.calls,
                current.successes,
                current.errors,
                current.fallbacks,
                current.total_latency_ms,
                current.last_status,
            ),
        )

    def snapshot(self) -> dict[str, ProviderRuntimeMetrics]:
        rows = self.db.query(
            """
            SELECT provider, calls, successes, errors, fallbacks, total_latency_ms, last_status
            FROM provider_metrics
            ORDER BY provider
            """
        )
        metrics: dict[str, ProviderRuntimeMetrics] = {}
        for row in rows:
            metric = ProviderRuntimeMetrics(str(row["provider"]))
            metric.calls = int(row["calls"])
            metric.successes = int(row["successes"])
            metric.errors = int(row["errors"])
            metric.fallbacks = int(row["fallbacks"])
            metric.total_latency_ms = float(row["total_latency_ms"])
            metric.last_status = str(row["last_status"])
            metrics[metric.provider] = metric
        return metrics

