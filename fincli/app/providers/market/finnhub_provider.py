"""Finnhub market provider.

Finnhub supports real-time REST/WebSocket APIs for stocks, forex, and crypto,
plus company fundamentals/news depending on endpoint and plan. This provider
implements the endpoints FinCLI needs for stock-style symbols first:
- /quote
- /stock/candle
- /company-news
- /stock/profile2
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable

import httpx

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderCapability, ProviderStatus, Quote
from fincli.app.providers.market.symbols import resolve_finnhub_symbol
from fincli.app.utils.errors import ProviderError, RateLimitError


class FinnhubProvider:
    name = "finnhub"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://finnhub.io/api/v1",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def quote(self, symbol: str) -> Quote:
        try:
            resolved = resolve_finnhub_symbol(symbol)
            if resolved.asset_class in {"forex", "crypto"}:
                candles = await self.history(symbol, period="5d", interval="1d")
                if not candles:
                    raise ProviderError(f"Finnhub did not return a valid price for {symbol}.")
                latest = candles[-1]
                return Quote(
                    symbol=resolved.symbol,
                    price=latest.close,
                    currency="USD",
                    provider=self.name,
                    timestamp=latest.timestamp,
                    status="delayed",
                )
            data = await self._get("/quote", {"symbol": symbol.upper()})
            if not isinstance(data, dict):
                raise ProviderError(f"Finnhub quote response is not valid for {symbol}.")
            price = _safe_float(data.get("c"))
            if price is None or price == 0:
                raise ProviderError(f"Finnhub did not return a valid price for {symbol}.")
            return Quote(
                symbol=symbol.upper(),
                price=price,
                currency="USD",
                provider=self.name,
                timestamp=datetime.fromtimestamp(int(data.get("t") or datetime.now().timestamp())),
                status="realtime",
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get quote from Finnhub for {symbol}: {exc}") from exc

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        try:
            resolved = resolve_finnhub_symbol(symbol)
            now = datetime.now()
            start = now - _period_to_delta(period)
            path = {
                "forex": "/forex/candle",
                "crypto": "/crypto/candle",
            }.get(resolved.asset_class, "/stock/candle")
            data = await self._get(
                path,
                {
                    "symbol": resolved.symbol,
                    "resolution": _interval_to_resolution(interval),
                    "from": int(start.timestamp()),
                    "to": int(now.timestamp()),
                },
            )
            if not isinstance(data, dict) or data.get("s") != "ok":
                raise ProviderError(f"Finnhub candle data is empty for {symbol} ({resolved.symbol}).")
            timestamps = data.get("t") or []
            candles = [
                Candle(
                    timestamp=datetime.fromtimestamp(int(ts)),
                    open=float(data["o"][index]),
                    high=float(data["h"][index]),
                    low=float(data["l"][index]),
                    close=float(data["c"][index]),
                    volume=float(data["v"][index]),
                )
                for index, ts in enumerate(timestamps)
            ]
            if not candles:
                raise ProviderError(f"Finnhub candle data is empty for {symbol} ({resolved.symbol}).")
            return candles
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get history from Finnhub for {symbol}: {exc}") from exc

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        try:
            today = datetime.now().date()
            start = today - timedelta(days=14)
            data = await self._get(
                "/company-news",
                {"symbol": symbol.upper(), "from": start.isoformat(), "to": today.isoformat()},
            )
            if not isinstance(data, list):
                raise ProviderError("Finnhub news response is not valid.")
            items: list[NewsItem] = []
            for item in data[:limit]:
                if not isinstance(item, dict):
                    continue
                timestamp = item.get("datetime")
                published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc) if isinstance(timestamp, (int, float)) else None
                items.append(
                    NewsItem(
                        title=str(item.get("headline") or item.get("title") or "Untitled"),
                        source=str(item.get("source") or self.name),
                        url=item.get("url"),
                        published_at=published_at,
                        summary=str(item.get("summary") or ""),
                    )
                )
            return items
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get news from Finnhub for {symbol}: {exc}") from exc

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        try:
            data = await self._get("/stock/profile2", {"symbol": symbol.upper()})
            if not isinstance(data, dict):
                raise ProviderError(f"Finnhub fundamentals response is not valid for {symbol}.")
            return FundamentalSnapshot(
                symbol=str(data.get("ticker") or symbol).upper(),
                provider=self.name,
                currency=str(data.get("currency") or "USD"),
                market_cap=_safe_float(data.get("marketCapitalization")),
                sector=data.get("finnhubIndustry"),
                industry=data.get("finnhubIndustry"),
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get fundamentals from Finnhub for {symbol}: {exc}") from exc

    async def insider_transactions(self, symbol: str, limit: int = 20) -> list[dict[str, object]]:
        data = await self._get("/stock/insider-transactions", {"symbol": symbol.upper()})
        rows = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Finnhub insider transactions response is not valid.")
        return [_parse_insider_transaction(item, symbol) for item in rows[:limit] if isinstance(item, dict)]

    async def ipo_calendar(self, start: date, end: date) -> list[dict[str, object]]:
        data = await self._get("/calendar/ipo", {"from": start.isoformat(), "to": end.isoformat()})
        rows = data.get("ipoCalendar") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ProviderError("Finnhub IPO calendar response is not valid.")
        return [_parse_ipo_item(item) for item in rows if isinstance(item, dict)]

    async def status(self) -> ProviderStatus:
        status = "configured" if self.api_key else "unavailable"
        message = "Finnhub provider configured." if self.api_key else "Requires FINNHUB_API_KEY."
        return ProviderStatus(name=self.name, realtime=True, status=status, message=message)

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=True,
            operations=("quote", "history", "news", "fundamentals"),
            asset_classes=("stock", "forex", "crypto", "commodity", "index"),
            rate_limit_note="Free tier: 60 calls/min.",
        )

    def run(self, awaitable: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, awaitable)
            return future.result(timeout=60)

    async def _get(self, path: str, params: dict[str, object]) -> Any:
        if not self.api_key:
            raise ProviderError("Finnhub API key not set.", "Use /news_model key finnhub <api_key>.")
        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        query = {**params, "token": self.api_key}
        try:
            response = await client.get(f"{self.base_url}{path}", params=query)
            if response.status_code == 429:
                raise RateLimitError("Finnhub rate limited.")
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Finnhub timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Finnhub failed: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Finnhub response is not valid JSON.") from exc
        finally:
            if close_client:
                await client.aclose()


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_insider_transaction(item: dict[str, Any], symbol: str) -> dict[str, object]:
    return {
        "symbol": str(item.get("symbol") or symbol).upper(),
        "name": str(item.get("name") or "-"),
        "date": str(item.get("transactionDate") or item.get("filingDate") or "-"),
        "transaction_code": str(item.get("transactionCode") or "-"),
        "change": _safe_float(item.get("change")),
        "shares": _safe_float(item.get("share")),
        "transaction_price": _safe_float(item.get("transactionPrice")),
    }


def _parse_ipo_item(item: dict[str, Any]) -> dict[str, object]:
    return {
        "date": str(item.get("date") or "-"),
        "exchange": str(item.get("exchange") or "-"),
        "symbol": str(item.get("symbol") or "-"),
        "name": str(item.get("name") or "-"),
        "price": str(item.get("price") or "-"),
        "shares": _safe_float(item.get("numberOfShares")),
        "status": str(item.get("status") or "-"),
    }


def _period_to_delta(period: str) -> timedelta:
    normalized = period.lower()
    if normalized.endswith("mo"):
        return timedelta(days=30 * int(normalized[:-2] or 6))
    if normalized.endswith("y"):
        return timedelta(days=365 * int(normalized[:-1] or 1))
    if normalized.endswith("d"):
        return timedelta(days=int(normalized[:-1] or 30))
    return timedelta(days=180)


def _interval_to_resolution(interval: str) -> str:
    mapping = {"1d": "D", "d": "D", "1w": "W", "w": "W", "1m": "M"}
    return mapping.get(interval.lower(), interval)
