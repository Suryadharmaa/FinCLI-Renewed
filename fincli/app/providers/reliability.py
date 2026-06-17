"""Provider reliability contracts and status classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fincli.app.utils.errors import RateLimitError


STATUS_OK = "ok"
STATUS_AUTH_FAILED = "auth_failed"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_ENTITLEMENT_MISSING = "entitlement_missing"
STATUS_PARTIAL_DATA = "partial_data"
STATUS_EMPTY_DATA = "empty_data"
STATUS_NETWORK_ERROR = "network_error"
STATUS_SCHEDULE_ONLY = "schedule_only"
STATUS_UNAVAILABLE = "unavailable"
STATUS_CIRCUIT_OPEN = "circuit_open"

GRANULAR_STATUSES = (
    STATUS_OK,
    STATUS_AUTH_FAILED,
    STATUS_RATE_LIMITED,
    STATUS_ENTITLEMENT_MISSING,
    STATUS_PARTIAL_DATA,
    STATUS_EMPTY_DATA,
    STATUS_NETWORK_ERROR,
    STATUS_SCHEDULE_ONLY,
    STATUS_UNAVAILABLE,
    STATUS_CIRCUIT_OPEN,
)


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Standard result envelope for provider calls."""

    provider: str
    operation: str
    status: str
    realtime_label: str = "unknown"
    source: str = ""
    data_quality: str = "unknown"
    missing_fields: tuple[str, ...] = ()
    message: str = ""


def classify_provider_error(exc: BaseException) -> str:
    """Classify provider failures into stable user-facing reliability statuses."""
    if isinstance(exc, RateLimitError):
        return STATUS_RATE_LIMITED

    text = f"{exc} {getattr(exc, 'help_text', '') or ''}".lower()
    if "429" in text or "rate limit" in text or "too many request" in text:
        return STATUS_RATE_LIMITED
    if "401" in text or "unauthorized" in text or "invalid key" in text or "api key" in text and "belum" in text:
        return STATUS_AUTH_FAILED
    if "403" in text or "entitlement" in text or "plan" in text or "premium" in text or "forbidden" in text:
        return STATUS_ENTITLEMENT_MISSING
    if "timeout" in text or "timed out" in text or "network" in text or "connection" in text or "dns" in text:
        return STATUS_NETWORK_ERROR
    if "empty" in text or "kosong" in text or "no data" in text:
        return STATUS_EMPTY_DATA
    if "missing" in text:
        return STATUS_PARTIAL_DATA
    return STATUS_UNAVAILABLE


def classify_payload(operation: str, payload: Any) -> tuple[str, tuple[str, ...]]:
    """Classify successful provider payload completeness."""
    if payload is None:
        return STATUS_EMPTY_DATA, (operation,)
    if isinstance(payload, list) and not payload:
        return STATUS_EMPTY_DATA, (operation,)
    if operation == "quote" and getattr(payload, "price", None) is None:
        return STATUS_PARTIAL_DATA, ("price",)
    if operation == "fundamentals":
        missing = tuple(
            field
            for field in ("market_cap", "pe_ratio", "eps", "revenue", "sector", "industry")
            if getattr(payload, field, None) in (None, "")
        )
        return (STATUS_PARTIAL_DATA if missing else STATUS_OK), missing
    return STATUS_OK, ()


def result_style(status: str) -> str:
    """Return a Rich style name for reliability statuses."""
    if status == STATUS_OK:
        return "green"
    if status in {
        STATUS_AUTH_FAILED,
        STATUS_RATE_LIMITED,
        STATUS_ENTITLEMENT_MISSING,
        STATUS_UNAVAILABLE,
        STATUS_NETWORK_ERROR,
        STATUS_CIRCUIT_OPEN,
    }:
        return "red"
    return "yellow"

