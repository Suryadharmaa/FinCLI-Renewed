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

from datetime import datetime, timedelta
from typing import Any

import httpx

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
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
        resolved = resolve_finnhub_symbol(symbol)
        if resolved.asset_class in {"forex", "crypto"}:
            candles = await self.history(symbol, period="5d", interval="1d")
            if not candles:
                raise ProviderError(f"Finnhub tidak mengembalikan harga valid untuk {symbol}.")
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
        price = _safe_float(data.get("c"))
        if price is None or price == 0:
            raise ProviderError(f"Finnhub tidak mengembalikan harga valid untuk {symbol}.")
        return Quote(
            symbol=symbol.upper(),
            price=price,
            currency="USD",
            provider=self.name,
            timestamp=datetime.fromtimestamp(int(data.get("t") or datetime.now().timestamp())),
            status="realtime",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
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
        if data.get("s") != "ok":
            raise ProviderError(f"Finnhub candle data kosong untuk {symbol} ({resolved.symbol}).")
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
            raise ProviderError(f"Finnhub candle data kosong untuk {symbol} ({resolved.symbol}).")
        return candles

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        today = datetime.now().date()
        start = today - timedelta(days=14)
        data = await self._get(
            "/company-news",
            {"symbol": symbol.upper(), "from": start.isoformat(), "to": today.isoformat()},
        )
        if not isinstance(data, list):
            raise ProviderError("Response Finnhub news tidak valid.")
        items: list[NewsItem] = []
        for item in data[:limit]:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("datetime")
            published_at = datetime.fromtimestamp(timestamp) if isinstance(timestamp, int) else None
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

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        data = await self._get("/stock/profile2", {"symbol": symbol.upper()})
        return FundamentalSnapshot(
            symbol=str(data.get("ticker") or symbol).upper(),
            provider=self.name,
            currency=str(data.get("currency") or "USD"),
            market_cap=_safe_float(data.get("marketCapitalization")),
            sector=data.get("finnhubIndustry"),
            industry=data.get("finnhubIndustry"),
        )

    async def status(self) -> ProviderStatus:
        status = "configured" if self.api_key else "unavailable"
        message = "Finnhub provider configured." if self.api_key else "Requires FINNHUB_API_KEY."
        return ProviderStatus(name=self.name, realtime=True, status=status, message=message)

    async def _get(self, path: str, params: dict[str, object]) -> Any:
        if not self.api_key:
            raise ProviderError("API key Finnhub belum diatur.", "Gunakan /news_model key finnhub <api_key>.")
        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        query = {**params, "token": self.api_key}
        try:
            response = await client.get(f"{self.base_url}{path}", params=query)
            if response.status_code == 429:
                raise RateLimitError("Finnhub terkena rate limit.")
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError("Finnhub timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Finnhub gagal: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Response Finnhub bukan JSON valid.") from exc
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
