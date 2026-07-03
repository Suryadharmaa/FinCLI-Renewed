"""Market/news provider catalog."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fincli.app.providers.market.alphavantage_provider import AlphaVantageProvider
from fincli.app.providers.market.base import BaseMarketProvider, ProviderEntitlement
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
    "alphavantage": MarketProviderInfo(
        name="alphavantage",
        realtime=False,
        status="configured",
        notes="Alpha Vantage adapter for stocks, FX, news sentiment, and company overview. Requires ALPHA_VANTAGE_API_KEY.",
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
        if provider_name == "alphavantage":
            return AlphaVantageProvider(api_key=os.getenv("ALPHA_VANTAGE_API_KEY"))
        raise ValueError(f"Unknown market provider: {name}")

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
            {
                "provider": "alphavantage",
                "key": "ALPHA_VANTAGE_API_KEY",
                "status": _mask_status(os.getenv("ALPHA_VANTAGE_API_KEY")),
                "source": secret_source("ALPHA_VANTAGE_API_KEY"),
            },
        ]

    def entitlements(self) -> list[ProviderEntitlement]:
        return [
            ProviderEntitlement(
                provider="yfinance",
                status="available",
                realtime_label="delayed/fallback",
                asset_classes=("stocks", "ETFs", "indices", "forex", "crypto", "commodities", "funds"),
                capabilities=("quote", "history", "news", "fundamentals", "yahoo tables"),
                limitations=(
                    "No API key required.",
                    "Data may be delayed and Yahoo coverage varies by exchange.",
                    "Not suitable for guaranteed realtime execution workflows.",
                ),
            ),
            ProviderEntitlement(
                provider="twelvedata",
                status="configured" if os.getenv("TWELVE_DATA_API_KEY") else "missing key",
                realtime_label="plan-dependent",
                asset_classes=("stocks", "ETFs", "indices", "forex", "crypto", "commodities"),
                capabilities=("quote", "history"),
                limitations=(
                    "Requires TWELVE_DATA_API_KEY.",
                    "Realtime access depends on plan and exchange entitlement.",
                    "News/fundamentals are not implemented in this adapter yet.",
                ),
            ),
            ProviderEntitlement(
                provider="finnhub",
                status="configured" if os.getenv("FINNHUB_API_KEY") else "missing key",
                realtime_label="plan-dependent",
                asset_classes=("stocks", "forex", "crypto"),
                capabilities=("quote", "history", "news", "fundamentals", "economic calendar"),
                limitations=(
                    "Requires FINNHUB_API_KEY.",
                    "Forex/crypto support is strongest for candles.",
                    "News/fundamentals coverage is strongest for equities.",
                ),
            ),
            ProviderEntitlement(
                provider="custom",
                status=(
                    "configured"
                    if os.getenv("MARKET_DATA_API_KEY") and os.getenv("MARKET_DATA_BASE_URL")
                    else "missing key/base url"
                ),
                realtime_label="custom",
                asset_classes=("provider-defined",),
                capabilities=("quote", "history", "news", "fundamentals"),
                limitations=(
                    "Requires MARKET_DATA_API_KEY and MARKET_DATA_BASE_URL.",
                    "Realtime/delayed status must be supplied by the custom API payload.",
                    "Payloads are validated by FinCLI before being accepted.",
                ),
            ),
            ProviderEntitlement(
                provider="alphavantage",
                status="configured" if os.getenv("ALPHA_VANTAGE_API_KEY") else "missing key",
                realtime_label="delayed/plan-dependent",
                asset_classes=("stocks", "forex", "selected crypto/commodities via provider functions"),
                capabilities=("quote", "history", "news", "fundamentals"),
                limitations=(
                    "Requires ALPHA_VANTAGE_API_KEY.",
                    "Free plans are heavily rate-limited.",
                    "Realtime availability and exchange coverage depend on Alpha Vantage plan.",
                ),
            ),
        ]


def _mask_status(value: str | None) -> str:
    if not value:
        return "not set"
    if len(value) <= 8:
        return "set"
    return f"{value[:4]}...{value[-4:]}"
