"""Base market provider contract for future provider implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    price: float | None
    currency: str
    provider: str
    timestamp: datetime
    status: str


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class NewsItem:
    title: str
    source: str
    url: str | None
    published_at: datetime | None
    summary: str = ""


@dataclass(frozen=True, slots=True)
class FundamentalSnapshot:
    symbol: str
    provider: str
    currency: str
    market_cap: float | None = None
    pe_ratio: float | None = None
    eps: float | None = None
    revenue: float | None = None
    beta: float | None = None
    sector: str | None = None
    industry: str | None = None
    # Provenance for providers that report filed figures (None elsewhere): the fiscal period
    # eps/revenue cover, its end date, the filing date, and revenue growth versus the prior fiscal year in percent.
    fiscal_period: str | None = None
    period_end: str | None = None
    filed_date: str | None = None
    revenue_growth: float | None = None


def fundamentals_provenance(snapshot: FundamentalSnapshot) -> str:
    """Where a snapshot's figures come from: provider and currency, plus the filing period for as-reported figures.

    A fallback snapshot can be in another currency and fiscal period than the quote beside it, so it is never shown unlabelled.
    """
    label = f"Source={snapshot.provider}; Currency={snapshot.currency}"
    if snapshot.fiscal_period:
        filed = f", filed {snapshot.filed_date}" if snapshot.filed_date else ""
        label += f"; EPS/Revenue as reported for {snapshot.fiscal_period} (period end {snapshot.period_end}{filed})"
    return label


def supports_operation(provider: object, operation: str) -> bool:
    """Whether the provider declares the operation; one without a readable declaration is tried for all."""
    capabilities = getattr(provider, "capabilities", None)
    if not callable(capabilities):
        return True
    try:
        return operation in capabilities().operations
    except Exception:  # noqa: BLE001 - a broken declaration must not hide the provider
        return True


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    realtime: bool
    status: str
    message: str


@dataclass(frozen=True, slots=True)
class ProviderEntitlement:
    provider: str
    status: str
    realtime_label: str
    asset_classes: tuple[str, ...]
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """Formal capability declaration for a market provider."""

    name: str
    realtime: bool
    operations: tuple[str, ...]  # ("quote", "history", "news", "fundamentals")
    asset_classes: tuple[str, ...]  # ("stock", "forex", "crypto", "commodity", "index")
    rate_limit_note: str = ""


@dataclass(frozen=True, slots=True)
class SymbolSearchResult:
    symbol: str
    name: str
    asset_class: str
    exchange: str = ""
    currency: str = ""
    provider_symbols: dict[str, str] | None = None
    notes: str = ""


class BaseMarketProvider(Protocol):
    name: str

    async def quote(self, symbol: str) -> Quote:
        """Fetch a single quote."""

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        """Fetch historical candles."""

    async def status(self) -> ProviderStatus:
        """Return provider health and realtime/delayed status."""

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        """Fetch latest news items."""

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        """Fetch a compact fundamental snapshot."""

    def capabilities(self) -> ProviderCapability:
        """Return formal capability declaration."""
