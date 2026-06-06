"""Base market provider contract for future provider implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


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


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    name: str
    realtime: bool
    status: str
    message: str


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
