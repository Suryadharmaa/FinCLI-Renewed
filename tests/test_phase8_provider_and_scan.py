from datetime import datetime
from pathlib import Path

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.scanner import scan_symbols
from fincli.app.providers.market.base import Candle, ProviderStatus, Quote
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


class ProviderCommandMarket:
    name = "fake-provider"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 123.45, "USD", self.name, datetime(2026, 6, 4), "delayed")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, realtime=False, status="ok", message="fake provider healthy")


class CombinedScanProvider:
    name = "combined-scan"

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        if symbol.upper() == "AAPL":
            return make_candles([100, 102, 101, 104, 106, 108, 110, 111, 113, 115, 117, 119, 121, 123, 125, 127, 129, 131, 133, 135])
        if symbol.upper() == "MSFT":
            return make_candles([140, 138, 137, 136, 134, 132, 130, 129, 127, 126, 124, 123, 121, 120, 118, 116, 115, 113, 111, 109])
        return make_candles([100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101])


def render_text(renderable) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


def test_provider_list_command_shows_available_providers(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/provider list")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "yfinance" in output
    assert "custom" in output
    assert "finnhub" in output


def test_provider_test_command_fetches_quote(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ProviderCommandMarket(),
    )

    result = router.route("/provider test AAPL")

    output = str(result.renderable)
    assert result.status == "ready"
    assert "AAPL" in output
    assert "123.4500" in output


def test_provider_status_uses_provider_health(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=ProviderCommandMarket(),
    )

    result = router.route("/provider status")

    output = render_text(result.renderable)
    assert "fake provider healthy" in output


def test_scan_symbols_supports_combined_filters() -> None:
    router = CommandRouter()

    results = router._run_async(scan_symbols(["AAPL", "MSFT"], CombinedScanProvider(), "rsi>60 trend=bullish"))

    assert [result.symbol for result in results] == ["AAPL"]


def test_scan_symbols_requires_all_combined_filters_to_match() -> None:
    router = CommandRouter()

    results = router._run_async(scan_symbols(["AAPL", "MSFT"], CombinedScanProvider(), "rsi<60 trend=bullish"))

    assert results == []


def test_scan_watchlist_command_supports_combined_filters(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=CombinedScanProvider(),
    )
    router.route("/watchlist add AAPL")
    router.route("/watchlist add MSFT")

    result = router.route("/scan watchlist rsi>60 trend=bullish")

    output = render_text(result.renderable)
    assert result.status == "ready"
    assert "AAPL" in output
    assert "MSFT" not in output
