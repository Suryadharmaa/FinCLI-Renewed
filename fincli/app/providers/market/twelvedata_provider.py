"""Twelve Data provider for multi-asset market data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.market.symbols import resolve_twelvedata_symbol
from fincli.app.utils.errors import ProviderError, RateLimitError


class TwelveDataProvider:
    name = "twelvedata"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://api.twelvedata.com",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def quote(self, symbol: str) -> Quote:
        resolved = resolve_twelvedata_symbol(symbol)
        data = await self._get("/quote", {"symbol": resolved.symbol})
        price = _safe_float(data.get("close") or data.get("price"))
        if price is None:
            raise ProviderError(f"Twelve Data tidak mengembalikan quote valid untuk {symbol}.")
        return Quote(
            symbol=str(data.get("symbol") or resolved.symbol).upper(),
            price=price,
            currency=str(data.get("currency") or "USD"),
            provider=self.name,
            timestamp=_parse_datetime(data.get("datetime")) or datetime.now(),
            status="realtime",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        resolved = resolve_twelvedata_symbol(symbol)
        data = await self._get(
            "/time_series",
            {
                "symbol": resolved.symbol,
                "interval": _interval_to_twelvedata(interval),
                "outputsize": _period_to_outputsize(period, interval),
                "timezone": "UTC",
            },
        )
        values = data.get("values") if isinstance(data, dict) else None
        if not isinstance(values, list) or not values:
            message = data.get("message") if isinstance(data, dict) else None
            raise ProviderError(f"Twelve Data OHLCV kosong untuk {symbol}.", str(message) if message else None)

        candles = [_parse_candle(item) for item in values if isinstance(item, dict)]
        candles.sort(key=lambda candle: candle.timestamp)
        if not candles:
            raise ProviderError(f"Twelve Data OHLCV kosong untuk {symbol}.")
        return candles

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        resolved = resolve_twelvedata_symbol(symbol)
        return FundamentalSnapshot(symbol=resolved.symbol.upper(), provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        status = "configured" if self.api_key else "unavailable"
        message = "Twelve Data provider configured." if self.api_key else "Requires TWELVE_DATA_API_KEY."
        return ProviderStatus(name=self.name, realtime=True, status=status, message=message)

    async def _get(self, path: str, params: dict[str, object]) -> Any:
        if not self.api_key:
            raise ProviderError("API key Twelve Data belum diatur.", "Gunakan /news_model key twelvedata <api_key>.")
        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.get(f"{self.base_url}{path}", params={**params, "apikey": self.api_key})
            if response.status_code == 429:
                raise RateLimitError("Twelve Data terkena rate limit.")
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict) and data.get("status") == "error":
                raise ProviderError(f"Twelve Data gagal: {data.get('message') or 'unknown error'}")
            return data
        except httpx.TimeoutException as exc:
            raise ProviderError("Twelve Data timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Twelve Data gagal: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Response Twelve Data bukan JSON valid.") from exc
        finally:
            if close_client:
                await client.aclose()


def _parse_candle(item: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=_parse_datetime(item.get("datetime")) or datetime.now(),
        open=float(item["open"]),
        high=float(item["high"]),
        low=float(item["low"]),
        close=float(item["close"]),
        volume=float(item.get("volume") or 0),
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _interval_to_twelvedata(interval: str) -> str:
    mapping = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1h",
        "4h": "4h",
        "1d": "1day",
        "d": "1day",
        "1w": "1week",
        "w": "1week",
        "1mo": "1month",
    }
    return mapping.get(interval.lower(), interval)


def _period_to_outputsize(period: str, interval: str) -> int:
    normalized = period.lower()
    interval_normalized = interval.lower()
    if normalized.endswith("mo"):
        days = 30 * int(normalized[:-2] or 6)
    elif normalized.endswith("y"):
        days = 365 * int(normalized[:-1] or 1)
    elif normalized.endswith("d"):
        days = int(normalized[:-1] or 180)
    else:
        days = 180
    if interval_normalized in {"1m", "5m", "15m", "30m", "1h", "4h"}:
        return min(5000, max(120, days * 24))
    return min(5000, max(30, days))
