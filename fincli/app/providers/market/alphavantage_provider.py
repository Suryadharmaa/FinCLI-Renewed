"""Alpha Vantage market provider adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from fincli.app.providers.market.base import (
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.providers.market.symbols import resolve_provider_symbol
from fincli.app.utils.errors import ProviderError, RateLimitError


class AlphaVantageProvider:
    name = "alphavantage"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://www.alphavantage.co/query",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url
        self._client = client

    async def quote(self, symbol: str) -> Quote:
        try:
            resolved = resolve_provider_symbol(self.name, symbol)
            if resolved.asset_class == "forex":
                data = await self._get(
                    {
                        "function": "CURRENCY_EXCHANGE_RATE",
                        "from_currency": resolved.symbol[:3],
                        "to_currency": resolved.symbol[3:],
                    }
                )
                rate = data.get("Realtime Currency Exchange Rate", {})
                price = _safe_float(rate.get("5. Exchange Rate"))
                if price is None:
                    raise ProviderError(f"Alpha Vantage did not return a valid FX quote for {symbol}.")
                return Quote(
                    symbol=resolved.symbol,
                    price=price,
                    currency=resolved.symbol[3:],
                    provider=self.name,
                    timestamp=_parse_datetime(rate.get("6. Last Refreshed")) or datetime.now(),
                    status="plan-dependent",
                )

            data = await self._get({"function": "GLOBAL_QUOTE", "symbol": resolved.symbol})
            quote = data.get("Global Quote", {})
            price = _safe_float(quote.get("05. price"))
            if price is None:
                raise ProviderError(f"Alpha Vantage did not return a valid quote for {symbol}.")
            return Quote(
                symbol=str(quote.get("01. symbol") or resolved.symbol).upper(),
                price=price,
                currency="USD",
                provider=self.name,
                timestamp=_parse_datetime(quote.get("07. latest trading day")) or datetime.now(),
                status="plan-dependent",
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get quote from Alpha Vantage for {symbol}: {exc}") from exc

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        try:
            resolved = resolve_provider_symbol(self.name, symbol)
            if resolved.asset_class == "forex":
                data = await self._get(
                    {
                        "function": "FX_DAILY",
                        "from_symbol": resolved.symbol[:3],
                        "to_symbol": resolved.symbol[3:],
                        "outputsize": "compact",
                    }
                )
                series = data.get("Time Series FX (Daily)", {})
            else:
                data = await self._get(
                    {
                        "function": "TIME_SERIES_DAILY_ADJUSTED",
                        "symbol": resolved.symbol,
                        "outputsize": "compact",
                    }
                )
                series = data.get("Time Series (Daily)", {})

            if not isinstance(series, dict) or not series:
                raise ProviderError(f"Alpha Vantage OHLCV is empty for {symbol}.")
            candles = [_parse_daily_candle(day, payload) for day, payload in series.items() if isinstance(payload, dict)]
            candles.sort(key=lambda candle: candle.timestamp)
            return candles
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get history from Alpha Vantage for {symbol}: {exc}") from exc

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        try:
            resolved = resolve_provider_symbol(self.name, symbol)
            data = await self._get({"function": "NEWS_SENTIMENT", "tickers": resolved.symbol, "limit": limit})
            feed = data.get("feed", [])
            if not isinstance(feed, list):
                return []
            return [
                NewsItem(
                    title=str(item.get("title") or "Untitled"),
                    source=str(item.get("source") or self.name),
                    url=item.get("url"),
                    published_at=_parse_datetime(item.get("time_published")),
                    summary=str(item.get("summary") or ""),
                )
                for item in feed[:limit]
                if isinstance(item, dict)
            ]
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get news from Alpha Vantage for {symbol}: {exc}") from exc

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        try:
            resolved = resolve_provider_symbol(self.name, symbol)
            data = await self._get({"function": "OVERVIEW", "symbol": resolved.symbol})
            return FundamentalSnapshot(
                symbol=str(data.get("Symbol") or resolved.symbol).upper(),
                provider=self.name,
                currency=str(data.get("Currency") or "USD"),
                market_cap=_safe_float(data.get("MarketCapitalization")),
                pe_ratio=_safe_float(data.get("PERatio")),
                eps=_safe_float(data.get("EPS")),
                revenue=_safe_float(data.get("RevenueTTM")),
                beta=_safe_float(data.get("Beta")),
                sector=data.get("Sector"),
                industry=data.get("Industry"),
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get fundamentals from Alpha Vantage for {symbol}: {exc}") from exc

    async def status(self) -> ProviderStatus:
        status = "configured" if self.api_key else "unavailable"
        message = "Alpha Vantage provider configured." if self.api_key else "Requires ALPHA_VANTAGE_API_KEY."
        return ProviderStatus(name=self.name, realtime=False, status=status, message=message)

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=False,
            operations=("quote", "history", "fundamentals"),
            asset_classes=("stock", "forex", "crypto", "commodity"),
            rate_limit_note="Free tier: 25 calls/day.",
        )

    async def _get(self, params: dict[str, object]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("Alpha Vantage API key not set.", "Use /news_model key alphavantage <api_key>.")
        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.get(self.base_url, params={**params, "apikey": self.api_key})
            if response.status_code == 429:
                raise RateLimitError("Alpha Vantage rate limited.")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ProviderError("Alpha Vantage response is not a JSON object.")
            message = data.get("Note") or data.get("Information")
            if message:
                raise RateLimitError(f"Alpha Vantage rate limited: {message}")
            if "Error Message" in data:
                raise ProviderError(f"Alpha Vantage failed: {data['Error Message']}")
            return data
        except httpx.TimeoutException as exc:
            raise ProviderError("Alpha Vantage timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Alpha Vantage failed: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Alpha Vantage response is not valid JSON.") from exc
        finally:
            if close_client:
                await client.aclose()


def _parse_daily_candle(day: str, payload: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=_parse_datetime(day) or datetime.now(),
        open=float(payload.get("1. open")),
        high=float(payload.get("2. high")),
        low=float(payload.get("3. low")),
        close=float(payload.get("4. close")),
        volume=float(payload.get("6. volume") or payload.get("5. volume") or 0),
    )


def _safe_float(value: Any) -> float | None:
    try:
        if value in {None, "None", "-", ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    for fmt in ("%Y%m%dT%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
