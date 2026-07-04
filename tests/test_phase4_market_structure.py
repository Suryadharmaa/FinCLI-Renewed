from datetime import datetime
from pathlib import Path

from fincli.app.analysis.market_structure import analyze_market_structure
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def candle(index: int, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2026, 1, index),
        open=close - 0.5,
        high=high,
        low=low,
        close=close,
        volume=1_000,
    )


def test_market_structure_detects_higher_highs_and_bos() -> None:
    candles = [
        candle(1, 100, 95, 98),
        candle(2, 104, 97, 103),
        candle(3, 102, 96, 99),
        candle(4, 108, 100, 107),
        candle(5, 111, 104, 110),
    ]

    result = analyze_market_structure(candles)

    assert result.trend == "bullish"
    assert result.latest_pattern == "HH/HL"
    assert result.break_of_structure is True
    assert result.change_of_character is False
    assert result.liquidity_area is not None


def test_market_structure_detects_bearish_change_of_character() -> None:
    candles = [
        candle(1, 110, 105, 108),
        candle(2, 114, 108, 113),
        candle(3, 116, 111, 115),
        candle(4, 112, 104, 105),
        candle(5, 109, 101, 102),
    ]

    result = analyze_market_structure(candles)

    assert result.trend == "bearish"
    assert result.latest_pattern == "LH/LL"
    assert result.change_of_character is True


class StructureMarketProvider:
    name = "structure"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol.upper(), 110.0, "USD", self.name, datetime(2026, 1, 5), "delayed")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return [
            candle(1, 100, 95, 98),
            candle(2, 104, 97, 103),
            candle(3, 102, 96, 99),
            candle(4, 108, 100, 107),
            candle(5, 111, 104, 110),
        ]


def test_structure_command_outputs_market_structure(tmp_path: Path) -> None:
    from rich.console import Console

    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=StructureMarketProvider(),
    )

    result = router.route("/technical AAPL 1d")

    assert result.status == "ready"
    console = Console(record=True, width=160)
    console.print(result.renderable)
    output = console.export_text()
    assert "AAPL" in output
    assert "RSI" in output
