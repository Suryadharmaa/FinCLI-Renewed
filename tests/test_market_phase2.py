import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from fincli.app.analysis import indicators
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class FakeMarketProvider:
    name = "fake"

    async def quote(self, symbol: str) -> Quote:
        return Quote(
            symbol=symbol.upper(),
            price=123.45,
            currency="USD",
            provider=self.name,
            timestamp=datetime(2026, 6, 4, 12, 0, 0),
            status="delayed",
        )

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[object]:
        candle = pytest.importorskip("fincli.app.providers.market.base").Candle
        prices = [100, 102, 101, 105, 108, 110, 109, 112, 115, 117, 116, 119, 121, 123, 125]
        return [
            candle(
                timestamp=datetime(2026, 1, index + 1),
                open=price - 1,
                high=price + 2,
                low=price - 2,
                close=price,
                volume=1_000 + index,
            )
            for index, price in enumerate(prices)
        ]


def make_router(tmp_path: Path) -> CommandRouter:
    config = ConfigManager(tmp_path / "config.json")
    db = FinCLIDatabase(tmp_path / "fincli.db")
    return CommandRouter(config=config, db=db, market_provider=FakeMarketProvider())


def test_price_command_uses_market_provider(tmp_path: Path) -> None:
    from rich.console import Console

    router = make_router(tmp_path)

    result = router.route("/market aapl 1d")

    assert result.status == "ready"
    console = Console(record=True, width=160)
    console.print(result.renderable)
    text = console.export_text()
    assert "AAPL" in text


def test_technical_command_uses_historical_candles(tmp_path: Path) -> None:
    router = make_router(tmp_path)

    result = router.route("/technical AAPL 1d")

    assert result.status == "ready"
    text = str(result.renderable)
    assert "AAPL" in text
    assert "RSI" in text
    assert "Trend Bias" in text


def test_indicator_summary_detects_uptrend() -> None:
    candles = pytest.importorskip("fincli.app.providers.market.base").Candle
    data = [
        candles(
            timestamp=datetime(2026, 1, index + 1),
            open=float(100 + index),
            high=float(102 + index),
            low=float(99 + index),
            close=float(101 + index),
            volume=1_000,
        )
        for index in range(20)
    ]

    summary = indicators.summarize_technical_indicators(data)

    assert summary.trend_bias == "bullish"
    assert summary.latest_close == 120.0
    assert summary.rsi is not None


def test_router_can_run_provider_inside_existing_event_loop(tmp_path: Path) -> None:
    from rich.console import Console

    router = make_router(tmp_path)

    async def call_router() -> str:
        result = router.route("/market AAPL 1d")
        console = Console(record=True, width=160)
        console.print(result.renderable)
        return console.export_text()

    output = asyncio.run(call_router())

    assert "AAPL" in output
