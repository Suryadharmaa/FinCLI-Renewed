from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.custom_provider import CustomMarketProvider
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.providers.market.symbols import (
    provider_symbol_matrix,
    resolve_provider_symbol,
    search_symbol_catalog,
)
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))


def test_provider_symbol_matrix_maps_multi_asset_aliases() -> None:
    matrix = provider_symbol_matrix("XAUUSD")

    assert matrix["yfinance"].symbol == "GC=F"
    assert matrix["twelvedata"].symbol == "XAU/USD"
    assert matrix["finnhub"].symbol == "OANDA:XAU_USD"
    assert matrix["custom"].symbol == "XAUUSD"
    assert matrix["yfinance"].asset_class == "commodity"


def test_symbol_search_returns_provider_specific_symbols() -> None:
    results = search_symbol_catalog("apple")

    assert results
    assert results[0].symbol == "AAPL"
    assert results[0].provider_symbols
    assert results[0].provider_symbols["yfinance"] == "AAPL"


def test_resolve_provider_symbol_for_idx_stock() -> None:
    resolved = resolve_provider_symbol("yfinance", "BBRI")

    assert resolved.symbol == "BBRI.JK"
    assert resolved.asset_class == "stock"


def test_provider_entitlements_include_realtime_labels() -> None:
    items = MarketProviderManager().entitlements()
    labels = {item.provider: item.realtime_label for item in items}

    assert labels["yfinance"] == "delayed/fallback"
    assert labels["twelvedata"] == "plan-dependent"
    assert labels["custom"] == "custom"


def test_symbol_and_entitlement_commands_route(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    assert router.route("/symbol XAUUSD").status == "ready"
    assert router.route("/symbol normalize EURUSD").status == "ready"
    assert router.route("/provider entitlement").status == "ready"


@pytest.mark.anyio
async def test_custom_provider_rejects_quote_without_numeric_price() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbol": "AAPL", "currency": "USD"})

    provider = CustomMarketProvider(
        api_key="test-key",
        base_url="https://custom.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ProviderError, match="quote.price"):
        await provider.quote("AAPL")
