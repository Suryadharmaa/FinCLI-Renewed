"""Local price alert management."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError
from fincli.app.utils.formatting import normalize_symbol


@dataclass(frozen=True, slots=True)
class AlertCheckResult:
    id: int
    symbol: str
    condition: str
    target: float
    current_price: float | None
    triggered: bool
    note: str


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


def normalize_condition(condition: str) -> str:
    normalized = condition.strip().lower()
    if normalized in {">", "above", "price_above", "gt"}:
        return "above"
    if normalized in {"<", "below", "price_below", "lt"}:
        return "below"
    raise CommandError("Alert condition must be above/> or below/<.")


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
