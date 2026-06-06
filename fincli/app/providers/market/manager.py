"""Market/news provider catalog."""

from __future__ import annotations

from dataclasses import dataclass
import os

from fincli.app.providers.market.base import BaseMarketProvider
from fincli.app.providers.market.custom_provider import CustomMarketProvider
from fincli.app.providers.market.finnhub_provider import FinnhubProvider
from fincli.app.providers.market.twelvedata_provider import TwelveDataProvider
from fincli.app.providers.market.yfinance_provider import YFinanceProvider
from fincli.app.storage.secrets import secret_source


@dataclass(frozen=True, slots=True)
class MarketProviderInfo:
    name: str
    realtime: bool
    status: str
    notes: str


MARKET_PROVIDERS: dict[str, MarketProviderInfo] = {
    "yfinance": MarketProviderInfo(
        name="yfinance",
        realtime=False,
        status="fallback",
        notes="Fallback delayed data. No API key required.",
    ),
    "custom": MarketProviderInfo(
        name="custom",
        realtime=True,
        status="configured",
        notes="Custom REST API provider. Requires MARKET_DATA_API_KEY and MARKET_DATA_BASE_URL.",
    ),
    "finnhub": MarketProviderInfo(
        name="finnhub",
        realtime=True,
        status="configured",
        notes="Finnhub REST provider. Requires FINNHUB_API_KEY.",
    ),
    "twelvedata": MarketProviderInfo(
        name="twelvedata",
        realtime=True,
        status="configured",
        notes="Multi-asset provider for stocks, forex, ETFs, indices, commodities, and crypto. Requires TWELVE_DATA_API_KEY.",
    ),
}


class MarketProviderManager:
    """Market provider catalog and factory."""

    def list_providers(self) -> list[MarketProviderInfo]:
        return list(MARKET_PROVIDERS.values())

    def get(self, name: str) -> MarketProviderInfo | None:
        return MARKET_PROVIDERS.get(name.lower())

    def create(self, name: str) -> BaseMarketProvider:
        provider_name = name.lower()
        if provider_name == "yfinance":
            return YFinanceProvider()
        if provider_name == "custom":
            return CustomMarketProvider(
                api_key=os.getenv("MARKET_DATA_API_KEY"),
                base_url=os.getenv("MARKET_DATA_BASE_URL", ""),
            )
        if provider_name == "finnhub":
            return FinnhubProvider(api_key=os.getenv("FINNHUB_API_KEY"))
        if provider_name == "twelvedata":
            return TwelveDataProvider(api_key=os.getenv("TWELVE_DATA_API_KEY"))
        raise ValueError(f"Market provider tidak dikenal: {name}")

    def create_many(self, names: list[str]) -> list[BaseMarketProvider]:
        providers: list[BaseMarketProvider] = []
        seen: set[str] = set()
        for name in names:
            normalized = name.lower().strip()
            if not normalized or normalized in seen:
                continue
            providers.append(self.create(normalized))
            seen.add(normalized)
        if not providers:
            providers.append(self.create("yfinance"))
        return providers

    def key_status(self) -> list[dict[str, str]]:
        return [
            {"provider": "yfinance", "key": "-", "status": "not required", "source": "-"},
            {
                "provider": "custom",
                "key": "MARKET_DATA_API_KEY",
                "status": _mask_status(os.getenv("MARKET_DATA_API_KEY")),
                "source": secret_source("MARKET_DATA_API_KEY"),
            },
            {
                "provider": "custom",
                "key": "MARKET_DATA_BASE_URL",
                "status": _mask_status(os.getenv("MARKET_DATA_BASE_URL")),
                "source": secret_source("MARKET_DATA_BASE_URL"),
            },
            {
                "provider": "finnhub",
                "key": "FINNHUB_API_KEY",
                "status": _mask_status(os.getenv("FINNHUB_API_KEY")),
                "source": secret_source("FINNHUB_API_KEY"),
            },
            {
                "provider": "twelvedata",
                "key": "TWELVE_DATA_API_KEY",
                "status": _mask_status(os.getenv("TWELVE_DATA_API_KEY")),
                "source": secret_source("TWELVE_DATA_API_KEY"),
            },
        ]


def _mask_status(value: str | None) -> str:
    if not value:
        return "not set"
    if len(value) <= 8:
        return "set"
    return f"{value[:4]}...{value[-4:]}"
