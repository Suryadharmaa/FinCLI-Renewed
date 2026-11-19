"""Equibles fundamentals provider (fundamentals only).

Serves as-reported annual revenue and diluted EPS from SEC filings (10-K, 20-F, 40-F),
plus sector and industry. It declares only the "fundamentals" operation, and
MarketDataService never routes quotes, history or news to a provider that does not
declare them.

Endpoints (Bearer key, https://equibles.com/docs/api):
- /v1/stocks/{ticker} - profile (sector, industry, listing currency)
- /v1/stocks/{ticker}/financial-facts/{concept} - a concept's reported annual history
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any
from urllib.parse import quote as url_quote

import httpx

from fincli.app.providers.market.base import (
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.utils.errors import ProviderError, RateLimitError

if TYPE_CHECKING:
    from collections.abc import Callable

API_BASE_URL = "https://api.equibles.com/v1"
API_KEYS_URL = "https://equibles.com/dashboard/apikeys"
# Annual filings change at most a few times a year; one snapshot costs three requests of a
# free key's 100 a day, so a process reuses it for six hours.
DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
# A fiscal year that ended over two years ago means a missed annual report, so it is not shown as current.
MAX_ANNUAL_AGE_DAYS = 2 * 365
_FISCAL_YEAR = re.compile(r"^FY(\d{4})$")


class EquiblesProvider:
    name = "equibles"
    realtime = False

    def __init__(
        self,
        api_key: str | None,
        base_url: str = API_BASE_URL,
        client: httpx.AsyncClient | None = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = monotonic,
        today: Callable[[], date] | None = None,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._today = today or (lambda: datetime.now(UTC).date())
        self._cache: dict[str, tuple[float, FundamentalSnapshot]] = {}

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        ticker = symbol.strip().upper()
        if not ticker:
            raise ProviderError("Equibles needs a ticker symbol.")
        cached = self._cache.get(ticker)
        if cached is not None and self._clock() - cached[0] < self._cache_ttl_seconds:
            return cached[1]

        path = f"/stocks/{url_quote(ticker, safe='')}"
        try:
            profile = await self._get(path)
        except _NotFoundError:
            # A symbol Equibles does not list (FX, crypto, a non-SEC listing) is an empty answer, not a
            # provider failure: it must not count toward the circuit breaker or be asked again within the window.
            snapshot = FundamentalSnapshot(symbol=ticker, provider=self.name, currency="USD")
            self._cache[ticker] = (self._clock(), snapshot)
            return snapshot
        revenue, eps = await asyncio.gather(
            self._get_facts(f"{path}/financial-facts/revenue"),
            self._get_facts(f"{path}/financial-facts/eps-diluted"),
        )
        snapshot = build_snapshot(ticker, profile, revenue, eps, today=self._today())
        self._cache[ticker] = (self._clock(), snapshot)
        return snapshot

    async def quote(self, symbol: str) -> Quote:
        raise ProviderError(_unsupported("quotes"))

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        raise ProviderError(_unsupported("price history"))

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        raise ProviderError(_unsupported("news"))

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=False,
            operations=("fundamentals",),
            asset_classes=("stock",),
            rate_limit_note="Free keys allow 100 requests a day; a snapshot uses 3 and is reused for 6 hours.",
        )

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            realtime=False,
            status="ok" if self.api_key else "no_key",
            message="Fundamentals only, as reported in SEC filings."
            if self.api_key
            else f"EQUIBLES_API_KEY not set. Create a key at {API_KEYS_URL}.",
        )

    async def _get_facts(self, path: str) -> dict[str, Any] | None:
        """A concept's facts, or None when the company reports none for it."""
        try:
            return await self._get(path)
        except _NotFoundError:
            return None

    async def _get(self, path: str) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError(
                "Equibles API key not set.",
                f"Add EQUIBLES_API_KEY (a free key from {API_KEYS_URL} allows 100 requests a day).",
            )
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            try:
                response = await client.get(
                    f"{self.base_url}{path}", headers={"Authorization": f"Bearer {self.api_key}"}
                )
            except httpx.TimeoutException as exc:
                raise ProviderError("Equibles request timed out.") from exc
            except httpx.TransportError as exc:
                raise ProviderError(f"Equibles network error ({type(exc).__name__}).") from exc
            _raise_for_status(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError("Equibles returned a response that is not JSON.") from exc
            if not isinstance(payload, dict):
                raise ProviderError("Equibles returned an unexpected response shape.")
            return payload
        finally:
            if self._client is None:
                await client.aclose()


class _NotFoundError(ProviderError):
    """HTTP 404: an unknown ticker, or a concept the company does not report."""


def build_snapshot(
    ticker: str,
    profile: dict[str, Any],
    revenue_facts: dict[str, Any] | None,
    eps_facts: dict[str, Any] | None,
    today: date | None = None,
) -> FundamentalSnapshot:
    """A snapshot of the newest full fiscal year either series reports.

    A series whose latest year is older than that year, or EPS in another currency than revenue, is left empty
    rather than shown as current. So are both when that year ended more than MAX_ANNUAL_AGE_DAYS before `today`
    (a filer that stopped reporting, or a concept whose tag changed).
    """
    revenue_rows = _comparable_annual(revenue_facts)
    eps_rows = _comparable_annual(eps_facts)
    latest = [rows[-1] for rows in (revenue_rows, eps_rows) if rows]
    # max() keeps the first of equal period ends, so revenue anchors a tie.
    anchor = max(latest, key=lambda row: row["periodEnd"]) if latest else None
    if anchor is not None and _days_since(anchor["periodEnd"], today or datetime.now(UTC).date()) > MAX_ANNUAL_AGE_DAYS:
        anchor = None

    revenue_row = revenue_rows[-1] if anchor and revenue_rows and revenue_rows[-1]["fiscalPeriod"] == anchor["fiscalPeriod"] else None
    eps_row = next((row for row in eps_rows if anchor and row["fiscalPeriod"] == anchor["fiscalPeriod"]), None)
    currency = _currency(revenue_facts) if revenue_row else _currency(eps_facts) if eps_row else None
    if revenue_row and eps_row and _currency(eps_facts) != currency:
        eps_row = None

    return FundamentalSnapshot(
        symbol=ticker,
        provider="equibles",
        currency=currency or str(profile.get("currency") or "USD"),
        eps=_number(eps_row),
        revenue=_number(revenue_row),
        sector=profile.get("sector") or None,
        industry=profile.get("industry") or None,
        fiscal_period=anchor.get("fiscalPeriod") if anchor else None,
        period_end=anchor.get("periodEnd") if anchor else None,
        filed_date=anchor.get("filedDate") if anchor else None,
        revenue_growth=revenue_growth(revenue_rows) if revenue_row else None,
    )


def _days_since(iso_date: str, today: date) -> int:
    try:
        return (today - date.fromisoformat(iso_date[:10])).days
    except ValueError:
        return MAX_ANNUAL_AGE_DAYS + 1


def revenue_growth(rows: list[dict[str, Any]]) -> float | None:
    """Percent change from the prior fiscal year to the latest, matched by fiscal-year label, never by position.

    None when the prior year is missing, either value is absent, or the prior value is not positive.
    """
    if not rows:
        return None
    latest = rows[-1]
    year = _fiscal_year(latest)
    if year is None:
        return None
    prior = next((row for row in rows if _fiscal_year(row) == year - 1), None)
    current_value, prior_value = _number(latest), _number(prior)
    if current_value is None or prior_value is None or prior_value <= 0:
        return None
    return (current_value / prior_value - 1) * 100


def _comparable_annual(facts: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Full-year rows with a fiscal-year label and a value, oldest period first; short transition years are dropped."""
    rows = (facts or {}).get("annual")
    if not isinstance(rows, list):
        return []
    usable = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("isComparableAnnual") is True
        and _fiscal_year(row) is not None
        and _number(row) is not None
        and isinstance(row.get("periodEnd"), str)
    ]
    return sorted(usable, key=lambda row: row["periodEnd"])


def _currency(facts: dict[str, Any] | None) -> str | None:
    """`USD` from `USD` or `USD/shares`."""
    unit = (facts or {}).get("unit")
    if not isinstance(unit, str) or not unit:
        return None
    return unit.split("/", 1)[0].upper()


def _fiscal_year(row: dict[str, Any] | None) -> int | None:
    match = _FISCAL_YEAR.match(str((row or {}).get("fiscalPeriod") or ""))
    return int(match.group(1)) if match else None


def _number(row: dict[str, Any] | None) -> float | None:
    value = (row or {}).get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _raise_for_status(response: httpx.Response) -> None:
    code = response.status_code
    if code < 400:
        return
    detail = _api_message(response)
    if code == 401:
        raise ProviderError(f"Equibles HTTP 401: unauthorized, the API key was refused. {detail}".strip())
    if code == 403:
        raise ProviderError(f"Equibles HTTP 403: forbidden, the key's plan does not include this data. {detail}".strip())
    if code == 404:
        raise _NotFoundError(f"Equibles HTTP 404: not found. {detail}".strip())
    if code == 429:
        reset = response.headers.get("X-RateLimit-Reset")
        when = f" Resets at {reset}." if reset else ""
        raise RateLimitError(f"Equibles HTTP 429: daily request limit reached.{when} {detail}".strip())
    if code >= 500:
        raise ProviderError(f"Equibles HTTP {code}: service unavailable.")
    raise ProviderError(f"Equibles HTTP {code}: {detail or 'request refused'}")


def _api_message(response: httpx.Response) -> str:
    """The API's own error message ({"error": {"message": ...}}), shortened; never echoes request headers."""
    try:
        body = response.json()
    except ValueError:
        return ""
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return str(message)[:200] if message else ""


def _unsupported(what: str) -> str:
    return f"Equibles provides fundamentals only, not {what}; FinCLI routes {what} to your other providers."
