from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.providers.market.symbols import SymbolResolver
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import ProviderError

if TYPE_CHECKING:
    from pathlib import Path


def test_symbol_resolver_maps_global_aliases() -> None:
    resolver = SymbolResolver()

    assert resolver.provider_symbol("yfinance", "BBRI") == "BBRI.JK"
    assert resolver.provider_symbol("yfinance", "XAUUSD") == "GC=F"
    assert resolver.provider_symbol("twelvedata", "XAUUSD") == "XAU/USD"
    assert resolver.provider_symbol("finnhub", "XAUUSD") == "OANDA:XAU_USD"
    assert resolver.provider_symbol("yfinance", "US500") == "^GSPC"
    assert resolver.provider_symbol("twelvedata", "BTCUSDT") == "BTC/USD"


def test_symbol_command_supports_search_and_resolve(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    assert router.route("/symbol search BBRI").status == "ready"
    assert router.route("/symbol resolve BBRI").status == "ready"
    assert router.route("/symbol normalize XAUUSD").status == "ready"


def test_market_service_normalizes_symbol_per_provider_before_fallback() -> None:
    failing = CapturingProvider("yfinance", fail=True)
    working = CapturingProvider("twelvedata", fail=False)
    service = MarketDataService([failing, working], symbol_resolver=SymbolResolver())

    quote = service.run(service.quote("XAUUSD"))

    assert quote.symbol == "XAU/USD"
    assert failing.seen_symbols == ["GC=F"]
    assert working.seen_symbols == ["XAU/USD"]


class CapturingProvider:
    def __init__(self, name: str, fail: bool) -> None:
        self.name = name
        self.realtime = False
        self.fail = fail
        self.seen_symbols: list[str] = []

    async def quote(self, symbol: str) -> Quote:
        self.seen_symbols.append(symbol)
        if self.fail:
            raise ProviderError("simulated provider failure")
        return Quote(symbol=symbol, price=100.0, currency="USD", provider=self.name, timestamp=datetime.now(UTC), status="ok")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return []

    async def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, realtime=False, status="ok", message="test")

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return []

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol, provider=self.name, currency="USD")
