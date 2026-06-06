from __future__ import annotations

import asyncio

import httpx

from fincli.app.providers.market.alphavantage_provider import AlphaVantageProvider
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.tui.market_provider_selector import market_provider_choices, recommended_provider_priority


def test_alphavantage_provider_parses_quote_history_news_and_fundamentals() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        function = request.url.params["function"]
        if function == "GLOBAL_QUOTE":
            return httpx.Response(200, json={"Global Quote": {"01. symbol": "AAPL", "05. price": "190.50", "07. latest trading day": "2026-06-05"}})
        if function == "TIME_SERIES_DAILY_ADJUSTED":
            return httpx.Response(
                200,
                json={
                    "Time Series (Daily)": {
                        "2026-06-05": {"1. open": "188", "2. high": "191", "3. low": "187", "4. close": "190", "6. volume": "1000"},
                        "2026-06-04": {"1. open": "186", "2. high": "189", "3. low": "185", "4. close": "188", "6. volume": "900"},
                    }
                },
            )
        if function == "NEWS_SENTIMENT":
            return httpx.Response(200, json={"feed": [{"title": "AAPL news", "source": "AV", "url": "https://example.com", "time_published": "20260605T120000", "summary": "summary"}]})
        if function == "OVERVIEW":
            return httpx.Response(200, json={"Symbol": "AAPL", "Currency": "USD", "MarketCapitalization": "1000", "PERatio": "20", "EPS": "5", "Sector": "Tech", "Industry": "Software"})
        return httpx.Response(404)

    provider = AlphaVantageProvider(
        api_key="test-key",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://www.alphavantage.co"),
    )

    quote = asyncio.run(provider.quote("AAPL"))
    candles = asyncio.run(provider.history("AAPL"))
    news = asyncio.run(provider.news("AAPL"))
    fundamentals = asyncio.run(provider.fundamentals("AAPL"))

    assert quote.price == 190.5
    assert [candle.close for candle in candles] == [188.0, 190.0]
    assert news[0].title == "AAPL news"
    assert fundamentals.pe_ratio == 20


def test_market_provider_manager_and_selector_include_alphavantage(monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "test-key")

    provider = MarketProviderManager().create("alphavantage")
    choices = {choice.provider for choice in market_provider_choices()}
    priority = recommended_provider_priority("alphavantage")

    assert provider.name == "alphavantage"
    assert "alphavantage" in choices
    assert priority[0] == "alphavantage"
    assert "yfinance" in priority
