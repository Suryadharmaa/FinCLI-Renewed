import asyncio
from datetime import datetime
from pathlib import Path

import httpx

from fincli.app.analysis.analyzer import build_technical_ai_summary
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle
from fincli.app.providers.market.finnhub_provider import FinnhubProvider
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.providers.market.symbols import resolve_finnhub_symbol, resolve_twelvedata_symbol, resolve_yfinance_symbol
from fincli.app.providers.market.twelvedata_provider import TwelveDataProvider
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def test_symbol_resolver_maps_common_forex_commodities_and_indices() -> None:
    assert resolve_yfinance_symbol("EURUSD").symbol == "EURUSD=X"
    assert resolve_yfinance_symbol("XAUUSD").symbol == "GC=F"
    assert resolve_yfinance_symbol("SPX").symbol == "^GSPC"
    assert resolve_twelvedata_symbol("EURUSD").symbol == "EUR/USD"
    assert resolve_twelvedata_symbol("XAUUSD").symbol == "XAU/USD"
    assert resolve_finnhub_symbol("EURUSD").symbol == "OANDA:EUR_USD"


def test_twelvedata_provider_parses_quote_and_history_payloads() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/quote":
            assert request.url.params["symbol"] == "XAU/USD"
            return httpx.Response(
                200,
                json={"symbol": "XAU/USD", "close": "2380.50", "currency": "USD", "datetime": "2026-06-05 12:00:00"},
            )
        if request.url.path == "/time_series":
            assert request.url.params["symbol"] == "XAU/USD"
            return httpx.Response(
                200,
                json={
                    "meta": {"symbol": "XAU/USD", "currency": "USD"},
                    "values": [
                        {"datetime": "2026-06-05 12:00:00", "open": "2370", "high": "2385", "low": "2368", "close": "2380", "volume": "0"},
                        {"datetime": "2026-06-04 12:00:00", "open": "2360", "high": "2375", "low": "2355", "close": "2370", "volume": "0"},
                    ],
                    "status": "ok",
                },
            )
        return httpx.Response(404)

    provider = TwelveDataProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.twelvedata.com"),
    )

    quote = asyncio.run(provider.quote("XAUUSD"))
    candles = asyncio.run(provider.history("XAUUSD"))

    assert quote.symbol == "XAU/USD"
    assert quote.price == 2380.5
    assert [candle.close for candle in candles] == [2370.0, 2380.0]


def test_finnhub_provider_uses_forex_candle_endpoint_for_forex_symbol() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/forex/candle"
        assert request.url.params["symbol"] == "OANDA:EUR_USD"
        return httpx.Response(
            200,
            json={"s": "ok", "t": [1_779_970_400], "o": [1.1], "h": [1.2], "l": [1.0], "c": [1.15], "v": [0]},
        )

    provider = FinnhubProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://finnhub.io"),
    )

    candles = asyncio.run(provider.history("EURUSD"))

    assert len(candles) == 1
    assert candles[0].close == 1.15


def test_market_provider_manager_creates_twelvedata(monkeypatch) -> None:
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "test-key")

    provider = MarketProviderManager().create("twelvedata")

    assert provider.name == "twelvedata"


def test_technical_output_includes_ai_assistance_summary(tmp_path: Path) -> None:
    class Provider:
        name = "fake"

        async def quote(self, symbol: str):
            raise NotImplementedError

        async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
            return [
                Candle(datetime(2026, 1, index + 1), 100 + index, 102 + index, 99 + index, 101 + index, 1000)
                for index in range(20)
            ]

    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=Provider(),
    )

    result = router.route("/technical EURUSD 1d")

    assert result.status == "ready"
    assert "AI Assistance Summary" in str(result.renderable)


def test_build_technical_ai_summary_is_structured() -> None:
    candles = [Candle(datetime(2026, 1, index + 1), 100 + index, 102 + index, 99 + index, 101 + index, 1000) for index in range(20)]

    summary = build_technical_ai_summary("EURUSD", "1d", candles)

    assert "Instrument: EURUSD" in summary
    assert "Trend Bias:" in summary
    assert "Signal:" in summary
    assert "Signal Reasoning:" in summary
    assert "Risk Notes:" in summary
