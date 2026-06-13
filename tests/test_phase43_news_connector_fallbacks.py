from __future__ import annotations

from datetime import datetime
from pathlib import Path

import httpx
from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class EmptyNewsMarketProvider:
    name = "empty-news-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, 100.0, "USD", self.name, datetime(2026, 6, 13), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime(2026, 1, 1), 1, 2, 1, 2, 100)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol, self.name, "USD")


def render_text(renderable: object) -> str:
    console = Console(record=True, width=140)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=EmptyNewsMarketProvider(),
    )


def test_news_connector_catalog_contains_100_plus_news_connectors() -> None:
    from fincli.app.connectors.news_connectors import NewsConnectorCatalog

    catalog = NewsConnectorCatalog()
    connectors = catalog.all()
    freeish = [item for item in connectors if item.access in {"free", "free-tier", "public-rss", "public-web"}]

    assert len(connectors) >= 100
    assert len(freeish) >= 60
    assert catalog.get("google_news_rss") is not None
    assert catalog.get("marketaux") is not None
    assert catalog.get("custom_news") is not None


def test_news_connector_manager_fetches_public_rss_fallback() -> None:
    from fincli.app.connectors.news_connectors import NewsConnectorManager

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "news.google.com" in str(request.url)
        return httpx.Response(
            200,
            text="""<?xml version="1.0" encoding="UTF-8"?>
            <rss><channel>
              <item>
                <title>AAPL rallies after earnings</title>
                <link>https://example.com/aapl</link>
                <pubDate>Sat, 13 Jun 2026 09:00:00 GMT</pubDate>
                <description>Apple shares rise as revenue beats estimates.</description>
              </item>
            </channel></rss>""",
        )

    manager = NewsConnectorManager(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    import asyncio

    items = asyncio.run(manager.fetch("google_news_rss", "AAPL", limit=3))

    assert items[0].title == "AAPL rallies after earnings"
    assert items[0].source == "Google News RSS"


def test_news_command_uses_configured_public_rss_fallback(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.config.set_news_provider_priority(["google_news_rss"])

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="""<rss><channel><item>
            <title>NVDA data center demand expands</title>
            <link>https://example.com/nvda</link>
            <description>Demand for AI chips remains strong.</description>
            </item></channel></rss>""",
        )

    from fincli.app.connectors.news_connectors import NewsConnectorManager

    router.news_connectors = NewsConnectorManager(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    result = router.route("/news NVDA")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "NVDA data center demand expands" in text
    assert "google_news_rss" in text


def test_news_model_commands_manage_primary_fallback_and_api_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("fincli.app.storage.secrets.SECRETS_FILE", tmp_path / "secrets.env")
    router = make_router(tmp_path)

    assert router.route("/news_model list").status == "ready"
    priority = router.route("/news_model priority google_news_rss,yfinance,marketaux")
    key = router.route("/news_model key marketaux test-key")
    custom = router.route("/news_model use custom_news")

    assert priority.status == "ready"
    assert key.status == "ready"
    assert custom.status == "ready"
    assert router.config.settings.news_provider == "custom_news"
    assert router.config.settings.news_provider_priority[0] == "custom_news"
