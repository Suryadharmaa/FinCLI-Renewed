from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fincli.app.analysis.multi_timeframe import analyze_multi_timeframe
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


def make_candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, index % 24),
            open=close - 0.5,
            high=close + 1.5,
            low=close - 1.5,
            close=close,
            volume=10_000 + index,
        )
        for index, close in enumerate(closes)
    ]


class FakeProvider:
    name = "fake"

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        if interval == "1d":
            return make_candles(list(range(100, 130)))
        if interval == "1h":
            return make_candles(list(range(120, 150)))
        return make_candles(list(range(140, 170)))


def test_multi_timeframe_detects_bullish_alignment() -> None:
    analysis = FinCLIRunner.run(analyze_multi_timeframe("AAPL", FakeProvider(), ("1d", "1h", "15m")))

    assert analysis.bias == "bullish"
    assert analysis.alignment in {"aligned bullish", "mostly bullish"}
    assert len(analysis.frames) == 3


def test_mtf_command_routes(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeProvider(),
    )

    result = router.route("/mtf AAPL 1d,1h,15m")

    assert result.status == "ready"


class FinCLIRunner:
    @staticmethod
    def run(awaitable):
        import asyncio

        return asyncio.run(awaitable)
