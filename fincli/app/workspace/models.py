"""Versioned, JSON-safe results and instrument identity."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from typing import Any, cast


def json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    exchange: str = ""
    currency: str = ""
    asset_class: str = "unknown"
    provider_symbol: str = ""

    @classmethod
    def parse(cls, value: str) -> Instrument:
        symbol = value.strip().upper()
        if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.:^_!/-]{0,39}", symbol):
            raise ValueError("Invalid symbol. Use a ticker or EXCHANGE:TICKER.")
        exchange, ticker = symbol.split(":", 1) if ":" in symbol else ("", symbol)
        if not ticker:
            raise ValueError("Ticker is required.")
        return cls(symbol=symbol, exchange=exchange, provider_symbol=ticker)


def result(
    kind: str,
    data: Any,
    *,
    source: str = "local",
    warnings: list[str] | None = None,
    symbol: str = "",
    status: str = "ok",
) -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        json_safe(
            {
                "contract": "3.0",
                "ok": status != "error",
                "kind": kind,
                "status": status,
                "symbol": symbol,
                "data": data,
                "warnings": warnings or [],
                "provenance": {
                    "source": source,
                    "retrieved_at": now_iso(),
                    "display_status": "local" if source == "local" else "provider-reported",
                    "verification": "calculated" if source == "local" else "not independently verified",
                },
            }
        ),
    )
