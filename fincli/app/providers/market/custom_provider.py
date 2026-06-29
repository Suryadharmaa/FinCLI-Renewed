"""Custom HTTP market API provider.

Expected endpoint contract:
- GET /quote/{symbol}
- GET /history/{symbol}?period=6mo&interval=1d
- GET /news/{symbol}?limit=5
- GET /fundamentals/{symbol}

The provider accepts common JSON key variants so users can adapt simple APIs
without changing FinCLI core.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from fincli.app.providers.market.base import (
    BaseMarketProvider,
    Candle,
    FundamentalSnapshot,
    NewsItem,
    ProviderCapability,
    ProviderStatus,
    Quote,
)
from fincli.app.utils.errors import ProviderError, RateLimitError


class CustomMarketProvider(BaseMarketProvider):
    name = "custom"

    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def quote(self, symbol: str) -> Quote:
        data = await self._get(f"/quote/{symbol.upper()}")
        data = _require_mapping(data, "quote")
        price = _required_float(data.get("price") or data.get("last") or data.get("last_price"), "quote.price")
        return Quote(
            symbol=str(data.get("symbol") or symbol).upper(),
            price=price,
            currency=str(data.get("currency") or "USD"),
            provider=self.name,
            timestamp=_parse_datetime(data.get("timestamp")) or datetime.now(),
            status=str(data.get("status") or "custom"),
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        data = await self._get(f"/history/{symbol.upper()}", params={"period": period, "interval": interval})
        raw_items = data.get("candles") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            raise ProviderError("Custom provider history response is not valid.")
        candles: list[Candle] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            candles.append(
                Candle(
                    timestamp=_parse_datetime(item.get("timestamp") or item.get("date")) or datetime.now(),
                    open=_required_float(item.get("open") or item.get("o"), "history.open"),
                    high=_required_float(item.get("high") or item.get("h"), "history.high"),
                    low=_required_float(item.get("low") or item.get("l"), "history.low"),
                    close=_required_float(item.get("close") or item.get("c"), "history.close"),
                    volume=float(item.get("volume") or item.get("v") or 0),
                )
            )
        if not candles:
            raise ProviderError(f"OHLCV data is empty for {symbol}.")
        return candles

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        data = await self._get(f"/news/{symbol.upper()}", params={"limit": limit})
        raw_items = data.get("news") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            raise ProviderError("Custom provider news response is not valid.")
        items: list[NewsItem] = []
        for item in raw_items[:limit]:
            if not isinstance(item, dict):
                continue
            items.append(
                NewsItem(
                    title=str(item.get("title") or "Untitled"),
                    source=str(item.get("source") or self.name),
                    url=item.get("url"),
                    published_at=_parse_datetime(item.get("published_at") or item.get("timestamp")),
                    summary=str(item.get("summary") or ""),
                )
            )
        return items

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        data = await self._get(f"/fundamentals/{symbol.upper()}")
        data = _require_mapping(data, "fundamentals")
        return FundamentalSnapshot(
            symbol=str(data.get("symbol") or symbol).upper(),
            provider=self.name,
            currency=str(data.get("currency") or "USD"),
            market_cap=_safe_float(data.get("market_cap") or data.get("marketCap")),
            pe_ratio=_safe_float(data.get("pe_ratio") or data.get("trailingPE")),
            eps=_safe_float(data.get("eps") or data.get("trailingEps")),
            revenue=_safe_float(data.get("revenue") or data.get("totalRevenue")),
            beta=_safe_float(data.get("beta")),
            sector=data.get("sector"),
            industry=data.get("industry"),
        )

    async def status(self) -> ProviderStatus:
        status = "configured" if self.api_key else "unavailable"
        message = "Custom provider configured." if self.api_key else "Requires MARKET_DATA_API_KEY."
        return ProviderStatus(name=self.name, realtime=True, status=status, message=message)

    def capabilities(self) -> ProviderCapability:
        return ProviderCapability(
            name=self.name,
            realtime=True,
            operations=("quote", "history", "news", "fundamentals"),
            asset_classes=("stock", "forex", "crypto", "commodity", "index"),
            rate_limit_note="User-defined endpoint; rate limits depend on backend.",
        )

    async def _get(self, path: str, params: dict[str, object] | None = None) -> Any:
        if not self.api_key:
            raise ProviderError(
                "Custom market provider API key not set.",
                "Use /news_model key custom <api_key> <base_url>.",
            )
        if not self.base_url:
            raise ProviderError(
                "Custom market provider base URL not set.",
                "Use /news_model key custom <api_key> <base_url>.",
            )

        close_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        headers = {"X-API-Key": self.api_key, "Authorization": f"Bearer {self.api_key}"}
        try:
            response = await client.get(f"{self.base_url}{path}", params=params, headers=headers)
            if response.status_code == 429:
                raise RateLimitError("Custom market provider rate limited.")
            response.raise_for_status()
            data = response.json()
            return data
        except httpx.TimeoutException as exc:
            raise ProviderError("Custom market provider timeout.") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Custom market provider gagal: HTTP {exc.response.status_code}.") from exc
        except ValueError as exc:
            raise ProviderError("Response custom market provider bukan JSON valid.") from exc
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


def _required_float(value: Any, field_name: str) -> float:
    number = _safe_float(value)
    if number is None:
        raise ProviderError(f"Response custom provider tidak valid: {field_name} wajib berupa angka.")
    return number


def _require_mapping(value: Any, section: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderError(f"Response {section} custom provider tidak valid: root JSON harus object.")
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
