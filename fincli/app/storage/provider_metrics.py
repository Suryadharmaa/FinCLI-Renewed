"""Persistent provider metrics storage."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.services.market_data import ProviderRuntimeMetrics
from fincli.app.storage.database import FinCLIDatabase


@dataclass(frozen=True, slots=True)
class OperationMetric:
    provider: str
    operation: str
    calls: int
    successes: int
    errors: int
    total_latency_ms: float

    @property
    def success_rate(self) -> float:
        return (self.successes / self.calls * 100) if self.calls else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.calls) if self.calls else 0.0


class ProviderMetricsStore:
    """Persist aggregate provider metrics across FinCLI sessions."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def record(self, provider: str, operation: str = "", success: bool = True, latency_ms: float = 0.0, fallback: bool = False) -> None:
        success_inc = 1 if success else 0
        error_inc = 0 if success else 1
        fallback_inc = 1 if fallback else 0
        latency = max(latency_ms, 0.0)
        last_status = "success" if success else "error"

        self.db.execute(
            """
            INSERT INTO provider_metrics(provider, calls, successes, errors, fallbacks, total_latency_ms, last_status, updated_at)
            VALUES (?, 1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider) DO UPDATE SET
                calls = calls + 1,
                successes = successes + ?,
                errors = errors + ?,
                fallbacks = fallbacks + ?,
                total_latency_ms = total_latency_ms + ?,
                last_status = ?,
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider, success_inc, error_inc, fallback_inc, latency, last_status,
             success_inc, error_inc, fallback_inc, latency, last_status),
        )
        if operation:
            self._record_operation(provider, operation, success, latency_ms)

    def _record_operation(self, provider: str, operation: str, success: bool, latency_ms: float) -> None:
        success_inc = 1 if success else 0
        error_inc = 0 if success else 1
        latency = max(latency_ms, 0.0)
        self.db.execute(
            """
            INSERT INTO provider_operation_metrics(provider, operation, calls, successes, errors, total_latency_ms, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(provider, operation) DO UPDATE SET
                calls = calls + 1,
                successes = successes + ?,
                errors = errors + ?,
                total_latency_ms = total_latency_ms + ?,
                updated_at = CURRENT_TIMESTAMP
            """,
            (provider, operation, success_inc, error_inc, latency,
             success_inc, error_inc, latency),
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

    def operation_snapshot(self, provider: str, operation: str) -> OperationMetric | None:
        rows = self.db.query(
            """
            SELECT provider, operation, calls, successes, errors, total_latency_ms
            FROM provider_operation_metrics
            WHERE provider = ? AND operation = ?
            """,
            (provider, operation),
        )
        if not rows:
            return None
        row = rows[0]
        return OperationMetric(
            provider=str(row["provider"]),
            operation=str(row["operation"]),
            calls=int(row["calls"]),
            successes=int(row["successes"]),
            errors=int(row["errors"]),
            total_latency_ms=float(row["total_latency_ms"]),
        )

    def all_operation_snapshots(self) -> list[OperationMetric]:
        rows = self.db.query(
            """
            SELECT provider, operation, calls, successes, errors, total_latency_ms
            FROM provider_operation_metrics
            ORDER BY provider, operation
            """
        )
        return [
            OperationMetric(
                provider=str(row["provider"]),
                operation=str(row["operation"]),
                calls=int(row["calls"]),
                successes=int(row["successes"]),
                errors=int(row["errors"]),
                total_latency_ms=float(row["total_latency_ms"]),
            )
            for row in rows
        ]
