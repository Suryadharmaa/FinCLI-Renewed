"""Polygon.io market provider.

Polygon.io provides real-time and historical market data for stocks, forex,
and crypto. Free tier: 5 API calls/min, delayed data.

Endpoints:
- /v2/aggs/ticker/{symbol}/prev — previous close
- /v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from}/{to} — aggregates
- /v3/reference/tickers/{symbol} — ticker details
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, ProviderStatus, Quote
from fincli.app.utils.errors import ProviderError, RateLimitError


class PolygonProvider:
    name = "polygon"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.polygon.io",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def quote(self, symbol: str) -> Quote:
        try:
            resolved = _resolve_symbol(symbol)
            data = await self._get(f"/v2/aggs/ticker/{resolved}/prev")
            if not isinstance(data, dict) or not data.get("results"):
                raise ProviderError(f"Polygon did not return a valid price for {symbol}.")
            result = data["results"][0]
            price = result.get("c")  # close price
            if price is None or price == 0:
                raise ProviderError(f"Polygon did not return a valid price for {symbol}.")
            return Quote(
                symbol=symbol.upper(),
                price=float(price),
                currency="USD",
                provider=self.name,
                timestamp=datetime.fromtimestamp(result.get("t", 0) / 1000, tz=timezone.utc),
                status="delayed",
            )
        except ProviderError:
            raise
        except RateLimitError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get quote from Polygon for {symbol}: {exc}") from exc

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        try:
            resolved = _resolve_symbol(symbol)
            multiplier, timespan = _parse_interval(interval)
            end = datetime.now()
            start = end - _period_to_delta(period)

            data = await self._get(
                f"/v2/aggs/ticker/{resolved}/range/{multiplier}/{timespan}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}",
                {"adjusted": "true", "sort": "asc", "limit": "5000"},
            )
            if not isinstance(data, dict) or not data.get("results"):
                raise ProviderError(f"Polygon candle data is empty for {symbol}.")

            candles = [
                Candle(
                    timestamp=datetime.fromtimestamp(item["t"] / 1000, tz=timezone.utc),
                    open=float(item["o"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    close=float(item["c"]),
                    volume=float(item.get("v", 0)),
                )
                for item in data["results"]
            ]
            return candles
        except ProviderError:
            raise
        except RateLimitError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get history from Polygon for {symbol}: {exc}") from exc

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        try:
            resolved = _resolve_symbol(symbol)
            data = await self._get(f"/v3/reference/tickers/{resolved}")
            if not isinstance(data, dict) or not data.get("results"):
                return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD")

            result = data["results"]
            return FundamentalSnapshot(
                symbol=symbol.upper(),
                provider=self.name,
                currency=result.get("currency_name", "USD").upper(),
                market_cap=_safe_float(result.get("market_cap")),
                sector=result.get("sic_description"),
                industry=result.get("type"),
            )
        except Exception:
            return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            realtime=False,
            status="ok" if self.api_key else "no_key",
            message="Polygon.io free tier: 5 API calls/min, delayed data." if self.api_key else "No API key set.",
        )

    async def _get(self, path: str, params: dict | None = None) -> dict:
        all_params = dict(params or {})
        all_params["apiKey"] = self.api_key
        url = f"{self.base_url}{path}"

        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.get(url, params=all_params)
            if response.status_code == 429:
                raise RateLimitError("Polygon rate limit reached. Free tier: 5 calls/min.")
            if response.status_code >= 400:
                raise ProviderError(f"Polygon HTTP {response.status_code}: {url}")
            return response.json()
        finally:
            if self._client is None:
                await client.aclose()


def _resolve_symbol(symbol: str) -> str:
    """Normalize symbol for Polygon API."""
    s = symbol.upper().strip()
    # Polygon uses X:BTCUSD format for crypto
    if s.endswith("-USD"):
        return f"X:{s.replace('-USD', 'USD')}"
    # Polygon uses C:EURUSD format for forex
    if s.endswith("=X"):
        return f"C:{s.replace('=X', '')}"
    return s


def _parse_interval(interval: str) -> tuple[int, str]:
    """Convert interval string to Polygon multiplier/timespan."""
    interval = interval.lower().strip()
    mapping = {
        "1m": (1, "minute"),
        "5m": (5, "minute"),
        "15m": (15, "minute"),
        "30m": (30, "minute"),
        "1h": (1, "hour"),
        "1d": (1, "day"),
        "1wk": (1, "week"),
        "1mo": (1, "month"),
    }
    return mapping.get(interval, (1, "day"))


def _period_to_delta(period: str) -> timedelta:
    """Convert period string to timedelta."""
    period = period.lower().strip()
    mapping = {
        "1d": timedelta(days=1),
        "5d": timedelta(days=5),
        "1mo": timedelta(days=30),
        "3mo": timedelta(days=90),
        "6mo": timedelta(days=180),
        "1y": timedelta(days=365),
        "2y": timedelta(days=730),
        "5y": timedelta(days=1825),
    }
    return mapping.get(period, timedelta(days=180))


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
