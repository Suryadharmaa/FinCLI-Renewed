from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle, FundamentalSnapshot, NewsItem, ProviderStatus, Quote
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_candles() -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, index % 24),
            open=100 + index,
            high=102 + index,
            low=99 + index,
            close=101 + index,
            volume=1_000 + index,
        )
        for index in range(80)
    ]


class FakeProvider:
    name = "fake"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol.upper(), price=180.0, currency="USD", provider=self.name, timestamp=datetime(2026, 1, 1), status="test")

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
        return make_candles()

    async def news(self, symbol: str, limit: int = 5) -> list[NewsItem]:
        return [NewsItem("Test headline", "unit-test", None, datetime(2026, 1, 1), "summary")]

    async def fundamentals(self, symbol: str) -> FundamentalSnapshot:
        return FundamentalSnapshot(symbol=symbol.upper(), provider=self.name, currency="USD", market_cap=1000, pe_ratio=20, eps=5, sector="Tech", industry="Software")

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, False, "test", "fake")


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=FakeProvider(),
    )


def test_scan_export_writes_csv(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    router.route("/watchlist add AAPL")
    target = tmp_path / "scan.csv"

    result = router.route(f"/scan export csv {target} trend=bullish 1d")

    assert result.status == "ready"
    assert target.exists()
    assert "AAPL" in target.read_text(encoding="utf-8")


def test_market_report_writes_json_and_markdown(tmp_path: Path) -> None:
    router = make_router(tmp_path)
    json_target = tmp_path / "report.json"
    md_target = tmp_path / "report.md"

    json_result = router.route(f"/report market AAPL json {json_target} 1d")
    md_result = router.route(f"/report market AAPL md {md_target} 1d")

    assert json_result.status == "ready"
    assert md_result.status == "ready"
    assert json.loads(json_target.read_text(encoding="utf-8"))["symbol"] == "AAPL"
    assert "# FinCLI Market Report: AAPL" in md_target.read_text(encoding="utf-8")
