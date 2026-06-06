import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.finnhub_provider import FinnhubProvider
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError


def test_finnhub_provider_rejects_missing_api_key() -> None:
    provider = FinnhubProvider(api_key="")

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.quote("AAPL"))

    assert "API key" in str(error.value)


def test_finnhub_provider_parses_quote_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/quote"
        assert request.url.params["symbol"] == "AAPL"
        assert request.url.params["token"] == "test-key"
        return httpx.Response(200, json={"c": 123.45, "t": 1_779_970_400})

    provider = FinnhubProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://finnhub.io"),
    )

    quote = asyncio.run(provider.quote("AAPL"))

    assert quote.symbol == "AAPL"
    assert quote.price == 123.45
    assert quote.provider == "finnhub"
    assert quote.status == "realtime"


def test_finnhub_provider_parses_stock_candles() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/stock/candle"
        return httpx.Response(
            200,
            json={
                "s": "ok",
                "t": [1_779_970_400, 1_780_056_800],
                "o": [100, 101],
                "h": [102, 103],
                "l": [99, 100],
                "c": [101, 102],
                "v": [1000, 1100],
            },
        )

    provider = FinnhubProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://finnhub.io"),
    )

    candles = asyncio.run(provider.history("AAPL"))

    assert len(candles) == 2
    assert candles[0].close == 101.0


def test_market_provider_manager_creates_finnhub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    provider = MarketProviderManager().create("finnhub")

    assert provider.name == "finnhub"


def test_news_model_command_updates_runtime_to_finnhub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/news_model finnhub")

    assert result.status == "ready"
    assert router.market_provider.name == "finnhub"
