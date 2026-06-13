from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class NewsMarketProvider:
    name = "news-market"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, 100.0, "USD", self.name, datetime(2026, 6, 7), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [Candle(datetime(2026, 1, 1), 1, 2, 1, 2, 100) for _ in range(30)]

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [
            NewsItem("AAPL launches new product", "UnitTest Wire", "https://example.com/aapl", datetime(2026, 6, 7), "Demand impact expected."),
            NewsItem("Analysts update estimates", "UnitTest Desk", "https://example.com/est", datetime(2026, 6, 6), "Margin estimates revised."),
        ][:limit]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol, self.name, "USD", pe_ratio=20)


def render_text(renderable: object) -> str:
    console = Console(record=True, width=140)
    console.print(renderable)
    return console.export_text()


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=NewsMarketProvider(),
    )


def test_agent_registry_contains_37_financial_framework_agents() -> None:
    from fincli.app.agents.registry import AgentRegistry

    registry = AgentRegistry()

    assert len(registry.all()) == 37
    assert registry.get("buffett") is not None
    assert {"trader", "investor", "economic", "geopolitics"}.issubset(set(registry.categories()))


def test_connector_catalog_has_100_plus_connectors_and_filtering() -> None:
    from fincli.app.connectors.catalog import ConnectorCatalog

    catalog = ConnectorCatalog()

    assert len(catalog.all()) >= 100
    assert catalog.find("FRED")[0].name == "FRED"
    assert catalog.by_category("macro")


def test_news_command_renders_news_desk_table(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/news AAPL")

    assert result.status == "ready"
    text = render_text(result.renderable)
    assert "News Desk" in text
    assert "AAPL launches new product" in text
    assert "UnitTest Wire" in text


def test_agent_connector_and_provider_metrics_commands_route(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    assert router.route("/agent list").status == "ready"
    assert router.route("/agent show buffett").status == "ready"
    assert router.route("/connector list macro").status == "ready"
    assert router.route("/connector search yahoo").status == "ready"
    assert router.route("/provider metrics").status == "ready"
