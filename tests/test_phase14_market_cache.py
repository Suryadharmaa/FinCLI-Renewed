from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, Quote
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.market_cache import MarketCache


class CountingProvider:
    name = "counting"

    def __init__(self) -> None:
        self.quote_calls = 0
        self.history_calls = 0

    async def quote(self, symbol: str) -> Quote:
        self.quote_calls += 1
        return Quote(symbol.upper(), 101.5, "USD", self.name, datetime(2026, 6, 5, 10, 0, 0), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        self.history_calls += 1
        return [
            Candle(datetime(2026, 6, 1), 100.0, 102.0, 99.0, 101.0, 1000.0),
            Candle(datetime(2026, 6, 2), 101.0, 103.0, 100.0, 102.0, 1200.0),
        ]


def render_text(renderable) -> str:
    console = Console(record=True, width=140)
    console.print(renderable)
    return console.export_text()


def test_market_data_service_uses_persistent_quote_cache(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)
    provider = CountingProvider()
    service = MarketDataService([provider], cache=cache, cache_ttl_seconds=300)

    first = service.run(service.quote("AAPL"))
    second = service.run(service.quote("AAPL"))

    assert first.price == 101.5
    assert second.price == 101.5
    assert provider.quote_calls == 1


def test_market_data_service_uses_persistent_history_cache_across_instances(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    cache = MarketCache(db)
    provider = CountingProvider()
    first_service = MarketDataService([provider], cache=cache, cache_ttl_seconds=300)
    second_service = MarketDataService([provider], cache=MarketCache(db), cache_ttl_seconds=300)

    first = first_service.run(first_service.history("AAPL", period="1mo", interval="1d"))
    second = second_service.run(second_service.history("AAPL", period="1mo", interval="1d"))

    assert [candle.close for candle in first] == [101.0, 102.0]
    assert [candle.close for candle in second] == [101.0, 102.0]
    assert provider.history_calls == 1


def test_cache_stats_and_clear_commands_include_persistent_cache(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    provider = CountingProvider()
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=db, market_provider=provider)

    router.route("/market AAPL")

    stats = router.route("/cache stats")
    assert stats.status == "ready"
    assert "Persistent entries:" in render_text(stats.renderable)

    cleared = router.route("/cache clear")
    assert cleared.status == "ready"
    assert "persistent cache dibersihkan" in render_text(cleared.renderable).lower()

    stats_after = router.route("/cache stats")
    assert "Persistent entries: 0" in render_text(stats_after.renderable)
