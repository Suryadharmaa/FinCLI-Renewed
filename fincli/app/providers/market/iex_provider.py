"""IEX Cloud market provider.

IEX Cloud provides market data for US stocks. Free tier available
with limited API calls.

Endpoints:
- /stock/{symbol}/quote — real-time quote
- /stock/{symbol}/chart/{range} — historical prices
- /stock/{symbol}/company — company info
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

from fincli.app.providers.market.base import Candle, FundamentalSnapshot, ProviderStatus, Quote
from fincli.app.utils.errors import ProviderError, RateLimitError


class IEXProvider:
    name = "iex"

    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://cloud.iexapis.com/stable",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def quote(self, symbol: str) -> Quote:
        try:
            data = await self._get(f"/stock/{symbol.upper()}/quote")
            if not isinstance(data, dict):
                raise ProviderError(f"IEX did not return a valid quote for {symbol}.")
            price = data.get("latestPrice")
            if price is None or price == 0:
                raise ProviderError(f"IEX did not return a valid price for {symbol}.")
            return Quote(
                symbol=symbol.upper(),
                price=float(price),
                currency=data.get("currency", "USD").upper(),
                provider=self.name,
                timestamp=datetime.fromtimestamp(data.get("latestUpdate", 0) / 1000, tz=UTC),
                status="realtime" if data.get("isUSMarketOpen") else "delayed",
            )
        except ProviderError:
            raise
        except RateLimitError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get quote from IEX for {symbol}: {exc}") from exc

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        try:
            iex_range = _period_to_iex_range(period)
            data = await self._get(f"/stock/{symbol.upper()}/chart/{iex_range}")
            if not isinstance(data, list) or not data:
                raise ProviderError(f"IEX candle data is empty for {symbol}.")

            candles = []
            for item in data:
                close = item.get("close")
                if close is None:
                    continue
                candles.append(Candle(
                    timestamp=datetime.strptime(item["date"], "%Y-%m-%d").replace(tzinfo=UTC),
                    open=float(item.get("open", close)),
                    high=float(item.get("high", close)),
                    low=float(item.get("low", close)),
                    close=float(close),
                    volume=float(item.get("volume", 0)),
                ))
            return candles
        except ProviderError:
            raise
        except RateLimitError:
            raise
        except Exception as exc:
            raise ProviderError(f"Failed to get history from IEX for {symbol}: {exc}") from exc

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        try:
            data = await self._get(f"/stock/{symbol.upper()}/company")
            if not isinstance(data, dict):
                return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD")
            return FundamentalSnapshot(
                symbol=symbol.upper(),
                provider=self.name,
                currency="USD",
                sector=data.get("sector"),
                industry=data.get("industry"),
            )
        except Exception:
            return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            realtime=True,
            status="ok" if self.api_key else "no_key",
            message="IEX Cloud: US stocks, real-time during market hours." if self.api_key else "No API key set.",
        )

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        all_params = dict(params or {})
        all_params["token"] = self.api_key
        url = f"{self.base_url}{path}"

        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.get(url, params=all_params)
            if response.status_code == 429:
                raise RateLimitError("IEX rate limit reached.")
            if response.status_code >= 400:
                raise ProviderError(f"IEX HTTP {response.status_code}: {url}")
            return response.json()
        finally:
            if self._client is None:
                await client.aclose()


def _period_to_iex_range(period: str) -> str:
    """Convert period string to IEX chart range."""
    period = period.lower().strip()
    mapping = {
        "1d": "1d",
        "5d": "5d",
        "1mo": "1m",
        "3mo": "3m",
        "6mo": "6m",
        "1y": "1y",
        "2y": "2y",
        "5y": "5y",
    }
    return mapping.get(period, "6m")
