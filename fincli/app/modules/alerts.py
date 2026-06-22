"""Local price alert management with conditional alerts and daemon support (v0.8.0)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

logger = logging.getLogger(__name__)

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError
from fincli.app.utils.formatting import normalize_symbol


# ---------------------------------------------------------------------------
# Alert check result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlertCheckResult:
    id: int
    symbol: str
    condition: str
    target: float
    current_price: float | None
    triggered: bool
    note: str


# ---------------------------------------------------------------------------
# Alert history entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlertHistoryEntry:
    id: int
    alert_id: int | None
    symbol: str
    condition: str
    target: float
    actual_value: float | None
    triggered: bool
    note: str
    created_at: str


# ---------------------------------------------------------------------------
# Conditional alert types
# ---------------------------------------------------------------------------

CONDITIONAL_TYPES = {
    "rsi_below": "RSI crosses below target",
    "rsi_above": "RSI crosses above target",
    "volume_above": "Volume exceeds target (x average)",
    "macd_cross_up": "MACD crosses above signal line",
    "macd_cross_down": "MACD crosses below signal line",
    "price_above": "Price rises above target",
    "price_below": "Price falls below target",
}


# ---------------------------------------------------------------------------
# Alert daemon state
# ---------------------------------------------------------------------------


class AlertDaemon:
    """Background alert checking daemon."""

    def __init__(self, alert_service: "AlertService", market_service: Any = None, check_interval: float = 60.0) -> None:
        self.alert_service = alert_service
        self.market_service = market_service
        self.check_interval = check_interval
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._last_check: datetime | None = None
        self._triggered_count = 0
        self._callbacks: list[Any] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_check(self) -> datetime | None:
        return self._last_check

    @property
    def triggered_count(self) -> int:
        return self._triggered_count

    def on_trigger(self, callback: Any) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def check_once(self) -> list[AlertCheckResult]:
        """Run one check cycle against all active alerts."""
        if self.market_service is None:
            return []
        active_alerts = self.alert_service.list(active_only=True)
        results: list[AlertCheckResult] = []
        for alert in active_alerts:
            try:
                quote = await self.market_service.quote(str(alert["symbol"]))
                price = quote.price
            except Exception:  # noqa: BLE001
                price = None

            result = _evaluate_conditional(alert, price)
            if result.triggered:
                self.alert_service.mark_triggered(result.id)
                self.alert_service.record_history(result.id, result.symbol, result.condition, result.target, result.current_price, True, result.note)
                self._triggered_count += 1
                for cb in self._callbacks:
                    try:
                        cb(result)
                    except Exception:  # noqa: BLE001
                        pass
            results.append(result)
        self._last_check = datetime.now(timezone.utc)
        return results

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.check_once()
            except Exception as exc:  # noqa: BLE001 - daemon should not crash
                logger.warning("Alert check failed: %s", exc)
            await asyncio.sleep(self.check_interval)


# ---------------------------------------------------------------------------
# Alert service
# ---------------------------------------------------------------------------


class AlertService:
    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def add(self, symbol: str, condition: str, target: float, note: str = "") -> None:
        normalized_condition = normalize_condition(condition)
        self.db.execute(
            """
            INSERT INTO alerts(symbol, condition, target, note, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (normalize_symbol(symbol), normalized_condition, target, note),
        )

    def add_conditional(self, symbol: str, condition: str, target: float, note: str = "") -> None:
        """Add a conditional alert (RSI, volume, MACD, price)."""
        normalized = condition.strip().lower()
        if normalized not in CONDITIONAL_TYPES:
            raise CommandError(
                f"Condition tidak dikenal: {condition}.",
                f"Gunakan: {', '.join(sorted(CONDITIONAL_TYPES))}.",
            )
        self.db.execute(
            """
            INSERT INTO alerts(symbol, condition, target, note, active)
            VALUES (?, ?, ?, ?, 1)
            """,
            (normalize_symbol(symbol), normalized, target, note),
        )

    def remove(self, alert_id: int) -> None:
        self.db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))

    def list(self, active_only: bool = False) -> list[dict[str, object]]:
        sql = "SELECT id, symbol, condition, target, note, active, triggered_at, created_at FROM alerts"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY active DESC, id DESC"
        return [dict(row) for row in self.db.query(sql)]

    def mark_triggered(self, alert_id: int) -> None:
        self.db.execute(
            "UPDATE alerts SET active = 0, triggered_at = CURRENT_TIMESTAMP WHERE id = ?",
            (alert_id,),
        )

    def record_history(self, alert_id: int, symbol: str, condition: str, target: float, actual_value: float | None, triggered: bool, note: str = "") -> None:
        self.db.execute(
            "INSERT INTO alert_history (alert_id, symbol, condition, target, actual_value, triggered, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alert_id, symbol, condition, target, actual_value, int(triggered), note),
        )

    def get_history(self, limit: int = 50) -> list[AlertHistoryEntry]:
        rows = self.db.query(
            "SELECT id, alert_id, symbol, condition, target, actual_value, triggered, note, created_at "
            "FROM alert_history ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            AlertHistoryEntry(
                id=int(r["id"]),
                alert_id=int(r["alert_id"]) if r["alert_id"] else None,
                symbol=str(r["symbol"]),
                condition=str(r["condition"]),
                target=float(r["target"]),
                actual_value=float(r["actual_value"]) if r["actual_value"] else None,
                triggered=bool(r["triggered"]),
                note=str(r["note"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Condition normalization
# ---------------------------------------------------------------------------


def normalize_condition(condition: str) -> str:
    normalized = condition.strip().lower()
    # Price conditions
    if normalized in {">", "above", "price_above", "gt"}:
        return "above"
    if normalized in {"<", "below", "price_below", "lt"}:
        return "below"
    # Conditional alerts
    if normalized in CONDITIONAL_TYPES:
        return normalized
    raise CommandError(
        f"Alert condition tidak dikenal: {condition}.",
        f"Gunakan: above, below, atau {', '.join(sorted(CONDITIONAL_TYPES))}.",
    )


# ---------------------------------------------------------------------------
# Alert evaluation
# ---------------------------------------------------------------------------


def evaluate_alert(alert: dict[str, object], current_price: float | None) -> AlertCheckResult:
    condition = str(alert["condition"])
    target = float(alert["target"])
    triggered = False
    if current_price is not None:
        if condition == "above":
            triggered = current_price >= target
        elif condition == "below":
            triggered = current_price <= target
    return AlertCheckResult(
        id=int(alert["id"]),
        symbol=str(alert["symbol"]),
        condition=condition,
        target=target,
        current_price=current_price,
        triggered=triggered,
        note=str(alert.get("note") or ""),
    )


def _evaluate_conditional(alert: dict[str, object], current_price: float | None) -> AlertCheckResult:
    """Evaluate conditional alerts (RSI, volume, MACD)."""
    condition = str(alert["condition"])
    target = float(alert["target"])

    # For simple price conditions, delegate to standard evaluate
    if condition in {"above", "below"}:
        return evaluate_alert(alert, current_price)

    # For conditional alerts, we need more data than just price.
    # These are evaluated by the daemon which has access to market_service.
    # For now, return as not triggered (daemon will handle with full data).
    return AlertCheckResult(
        id=int(alert["id"]),
        symbol=str(alert["symbol"]),
        condition=condition,
        target=target,
        current_price=current_price,
        triggered=False,
        note=f"Conditional alert ({condition}) requires daemon with market data access.",
    )
