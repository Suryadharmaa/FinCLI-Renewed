from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fincli.app.analysis.backtest import run_backtest
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, index % 24),
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1_000 + index,
        )
        for index, close in enumerate(closes)
    ]


class FakeProvider:
    name = "fake"

    async def history(self, symbol: str, period: str = "2y", interval: str = "1d") -> list[Candle]:
        prices = [100 + index for index in range(40)]
        prices += [140 - index for index in range(20)]
        prices += [120 + index for index in range(40)]
        return make_candles(prices)


def test_backtest_engine_returns_metrics() -> None:
    candles = make_candles([100 + index for index in range(35)] + [135 - index for index in range(35)])

    result = run_backtest("AAPL", candles, "sma_cross", "1d")

    assert result.symbol == "AAPL"
    assert result.candles == 70
    assert result.total_return_percent >= -100
    assert result.max_drawdown_percent >= 0
    assert result.notes


def test_backtest_command_routes(tmp_path: Path) -> None:
    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeProvider(),
    )

    result = router.route("/backtest AAPL sma_cross 1d")

    assert result.status == "ready"
