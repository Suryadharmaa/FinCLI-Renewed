from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.scanner import scan_symbols
from fincli.app.providers.market.base import Candle, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, index + 1),
            open=close - 0.5,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=1_000 + index,
        )
        for index, close in enumerate(closes)
    ]


class ScanMarketProvider:
    name = "scan"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 100.0, "USD", self.name, datetime(2026, 6, 4), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        if symbol.upper() == "AAPL":
            return make_candles([100, 102, 101, 104, 106, 108, 110, 111, 113, 115, 117, 119, 121, 123, 125, 127, 129, 131, 133, 135])
        return make_candles([140, 138, 137, 136, 134, 132, 130, 129, 127, 126, 124, 123, 121, 120, 118, 116, 115, 113, 111, 109])


def test_scan_symbols_filters_by_rsi_threshold() -> None:
    provider = ScanMarketProvider()

    results, errors = CommandRouter()._run_async(scan_symbols(["AAPL", "MSFT"], provider, "rsi<35"))

    symbols = [result.symbol for result in results]
    assert "MSFT" in symbols
    assert "AAPL" not in symbols


def test_scan_watchlist_command_filters_by_trend(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ScanMarketProvider(),
    )
    router.route("/watchlist add AAPL")
    router.route("/watchlist add MSFT")

    result = router.route("/scan watchlist trend=bullish")

    console = Console(record=True, width=140)
    console.print(result.renderable)
    output = console.export_text()
    assert result.status == "ready"
    assert "AAPL" in output
    assert "MSFT" not in output
    assert "RSI" in output
