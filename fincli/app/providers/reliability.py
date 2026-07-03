"""Provider reliability contracts and status classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, TypeVar

from fincli.app.utils.errors import RateLimitError

T = TypeVar("T")


STATUS_OK = "ok"
STATUS_AUTH_FAILED = "auth_failed"
STATUS_RATE_LIMITED = "rate_limited"
STATUS_ENTITLEMENT_MISSING = "entitlement_missing"
STATUS_PARTIAL_DATA = "partial_data"
STATUS_DELAYED = "delayed"
STATUS_FALLBACK = "fallback"
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
    STATUS_DELAYED,
    STATUS_FALLBACK,
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


@dataclass(slots=True)
class ProviderResponse(Generic[T]):
    """Standardized response envelope wrapping provider data with quality metadata."""

    data: T | None
    provider: str
    operation: str
    status: str
    quality_score: int  # 0-100
    latency_ms: float
    realtime_label: str = "unknown"
    missing_fields: tuple[str, ...] = ()
    message: str = ""
    raw_result: ProviderResult | None = field(default=None, repr=False)
    # Soft error detection (v1.2.0)
    staleness_score: float = 0.0  # 0=fresh, 1=stale
    anomaly_flags: tuple[str, ...] = ()  # e.g. ("price_spike", "stale_data")
    data_freshness: datetime | None = None  # timestamp of data source


def score_quality(operation: str, payload: Any, missing_fields: tuple[str, ...]) -> int:
    """Compute a 0-100 quality score from operation, payload completeness, and missing fields."""
    if payload is None:
        return 0
    if isinstance(payload, list) and not payload:
        return 10

    base = 100
    # Deduct for missing fields
    deduction_per_field = {
        "quote": 30,
        "history": 25,
        "news": 15,
        "fundamentals": 20,
    }.get(operation, 15)

    for _ in missing_fields:
        base -= deduction_per_field

    # Operation-specific checks
    if operation == "quote":
        if getattr(payload, "price", None) is None:
            base -= 40
        if getattr(payload, "currency", "") == "":
            base -= 10
    elif operation == "history":
        if isinstance(payload, list) and len(payload) < 5:
            base -= 20
    elif operation == "fundamentals":
        if getattr(payload, "market_cap", None) is None:
            base -= 15
        if getattr(payload, "sector", None) is None:
            base -= 10

    return max(0, min(100, base))


def classify_provider_error(exc: BaseException) -> str:
    """Classify provider failures into stable user-facing reliability statuses."""
    if isinstance(exc, RateLimitError):
        return STATUS_RATE_LIMITED

    text = f"{exc} {getattr(exc, 'help_text', '') or ''}".lower()
    if "429" in text or "rate limit" in text or "too many request" in text:
        return STATUS_RATE_LIMITED
    if "401" in text or "unauthorized" in text or "invalid key" in text or ("api key" in text and ("not set" in text or "missing" in text or "required" in text)):
        return STATUS_AUTH_FAILED
    if "403" in text or "entitlement" in text or "plan" in text or "premium" in text or "forbidden" in text:
        return STATUS_ENTITLEMENT_MISSING
    if "502" in text or "503" in text or "504" in text or "bad gateway" in text or "service unavailable" in text:
        return STATUS_NETWORK_ERROR
    if "timeout" in text or "timed out" in text or "network" in text or "connection" in text or "dns" in text:
        return STATUS_NETWORK_ERROR
    if "empty" in text or "no data" in text or "not found" in text:
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


# ---------------------------------------------------------------------------
# Soft Error Detection (v1.2.0)
# ---------------------------------------------------------------------------

PRICE_ANOMALY_THRESHOLD = 0.50  # 50% change = anomaly
STALE_DATA_THRESHOLD_SECONDS = 300  # 5 minutes


def detect_staleness(data_freshness: datetime | None, max_age_seconds: int = STALE_DATA_THRESHOLD_SECONDS) -> float:
    """Detect data staleness. Returns 0.0 (fresh) to 1.0 (stale)."""
    if data_freshness is None:
        return 0.5  # Unknown freshness

    now = datetime.now(data_freshness.tzinfo) if data_freshness.tzinfo else datetime.now()
    age_seconds = (now - data_freshness).total_seconds()

    if age_seconds <= 0:
        return 0.0  # Future timestamp (clock skew)
    if age_seconds <= max_age_seconds:
        return 0.0  # Fresh
    if age_seconds <= max_age_seconds * 2:
        return 0.5  # Slightly stale
    return 1.0  # Very stale


def detect_price_anomaly(current_price: float | None, previous_price: float | None) -> tuple[bool, str]:
    """Detect price anomalies (sudden spikes/drops).

    Returns (is_anomaly, flag_description).
    """
    if current_price is None or previous_price is None:
        return False, ""
    if previous_price == 0:
        return False, ""

    change_pct = abs(current_price - previous_price) / abs(previous_price)
    if change_pct > PRICE_ANOMALY_THRESHOLD:
        return True, f"price_spike_{change_pct:.0%}"
    return False, ""


def detect_quote_anomaly(quote: Any) -> tuple[str, ...]:
    """Detect anomalies in quote data.

    Returns tuple of anomaly flags.
    """
    flags = []

    price = getattr(quote, "price", None)
    if price is not None:
        if price <= 0:
            flags.append("negative_price")
        if price > 1_000_000:
            flags.append("extreme_price")

    currency = getattr(quote, "currency", "")
    if not currency:
        flags.append("missing_currency")

    return tuple(flags)


def detect_history_anomaly(candles: list[Any]) -> tuple[str, ...]:
    """Detect anomalies in historical candle data.

    Returns tuple of anomaly flags.
    """
    if not candles or len(candles) < 2:
        return ()

    flags = []

    for i in range(1, len(candles)):
        prev_close = getattr(candles[i - 1], "close", None)
        curr_open = getattr(candles[i], "open", None)
        curr_high = getattr(candles[i], "high", None)
        curr_low = getattr(candles[i], "low", None)

        if prev_close and curr_open and prev_close > 0:
            gap_pct = abs(curr_open - prev_close) / prev_close
            if gap_pct > 0.20:  # 20% gap
                flags.append(f"gap_at_index_{i}")

        if curr_high and curr_low and curr_low > 0:
            if curr_high < curr_low:
                flags.append(f"inverted_hl_at_index_{i}")

    return tuple(flags)


def detect_fundamental_anomaly(snapshot: Any) -> tuple[str, ...]:
    """Detect anomalies in fundamental data.

    Returns tuple of anomaly flags.
    """
    flags = []

    pe = getattr(snapshot, "pe_ratio", None)
    if pe is not None and (pe < -100 or pe > 1000):
        flags.append("extreme_pe")

    market_cap = getattr(snapshot, "market_cap", None)
    if market_cap is not None and market_cap < 0:
        flags.append("negative_market_cap")

    return tuple(flags)


def build_enhanced_response(
    response: ProviderResponse,
    data_freshness: datetime | None = None,
    previous_price: float | None = None,
) -> ProviderResponse:
    """Enhance a ProviderResponse with soft error detection.

    Adds staleness_score and anomaly_flags.
    """

    # Detect staleness
    staleness = detect_staleness(data_freshness)

    # Detect anomalies based on operation
    anomaly_flags: list[str] = []

    if response.operation == "quote" and response.data is not None:
        anomaly_flags.extend(detect_quote_anomaly(response.data))
        if previous_price:
            is_anomaly, flag = detect_price_anomaly(
                getattr(response.data, "price", None),
                previous_price,
            )
            if is_anomaly:
                anomaly_flags.append(flag)
    elif response.operation == "history" and response.data is not None:
        if isinstance(response.data, list):
            anomaly_flags.extend(detect_history_anomaly(response.data))
    elif response.operation == "fundamentals" and response.data is not None:
        anomaly_flags.extend(detect_fundamental_anomaly(response.data))

    # Create enhanced response
    return ProviderResponse(
        data=response.data,
        provider=response.provider,
        operation=response.operation,
        status=response.status,
        quality_score=response.quality_score,
        latency_ms=response.latency_ms,
        realtime_label=response.realtime_label,
        missing_fields=response.missing_fields,
        message=response.message,
        raw_result=response.raw_result,
        staleness_score=staleness,
        anomaly_flags=tuple(anomaly_flags),
        data_freshness=data_freshness,
    )
