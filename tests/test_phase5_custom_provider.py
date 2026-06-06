import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.custom_provider import CustomMarketProvider
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError


def test_custom_provider_rejects_missing_api_key() -> None:
    provider = CustomMarketProvider(api_key="", base_url="https://market.test")

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.quote("AAPL"))

    assert "API key" in str(error.value)


def test_custom_provider_parses_quote_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/quote/AAPL"
        assert request.headers["X-API-Key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "symbol": "AAPL",
                "price": 123.45,
                "currency": "USD",
                "timestamp": "2026-06-04T12:00:00",
                "status": "realtime",
            },
        )

    provider = CustomMarketProvider(
        api_key="test-key",
        base_url="https://market.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://market.test"),
    )

    quote = asyncio.run(provider.quote("AAPL"))

    assert quote.symbol == "AAPL"
    assert quote.price == 123.45
    assert quote.status == "realtime"
    assert quote.timestamp == datetime(2026, 6, 4, 12, 0, 0)


def test_market_provider_manager_creates_custom_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
    monkeypatch.setenv("MARKET_DATA_BASE_URL", "https://market.test")

    provider = MarketProviderManager().create("custom")

    assert provider.name == "custom"


def test_news_model_command_updates_runtime_market_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKET_DATA_API_KEY", "test-key")
    monkeypatch.setenv("MARKET_DATA_BASE_URL", "https://market.test")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/news_model custom")

    assert result.status == "ready"
    assert router.market_provider.name == "custom"
