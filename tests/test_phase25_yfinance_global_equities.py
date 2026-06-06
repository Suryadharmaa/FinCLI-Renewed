from __future__ import annotations

import asyncio
from datetime import datetime
import sys
import types
from pathlib import Path

import pandas as pd

from fincli.app.cli.router import CommandRouter
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.market.symbols import resolve_yfinance_symbol
from fincli.app.providers.market.yfinance_provider import YFinanceProvider
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


class FakeAIProvider:
    name = "fake-ai"

    async def complete(self, request: AIRequest) -> AIResponse:
        return AIResponse(provider=self.name, model=request.model, content="Market Summary: BBRI context received")


class FakeTicker:
    seen_symbols: list[str] = []

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.seen_symbols.append(symbol)
        self.fast_info = {"last_price": 4120.0, "currency": "IDR"}
        self.info = {
            "symbol": symbol,
            "longName": "Bank Rakyat Indonesia Persero Tbk",
            "currency": "IDR",
            "financialCurrency": "IDR",
            "marketCap": 610_000_000_000_000,
            "trailingPE": 11.5,
            "trailingEps": 358.0,
            "totalRevenue": 180_000_000_000_000,
            "sector": "Financial Services",
            "industry": "Banks",
            "country": "Indonesia",
            "website": "https://bri.co.id",
            "recommendationKey": "buy",
            "numberOfAnalystOpinions": 20,
            "targetMeanPrice": 5200.0,
        }
        self.news = [
            {
                "content": {
                    "title": "BBRI posts loan growth",
                    "provider": {"displayName": "UnitTest News"},
                    "canonicalUrl": {"url": "https://example.com/bbri-news"},
                    "pubDate": "2026-06-06T10:00:00Z",
                    "summary": "Loan growth remains resilient.",
                }
            }
        ]
        self.financials = pd.DataFrame(
            {"2025-12-31": [180_000_000_000_000, 60_000_000_000_000]},
            index=["Total Revenue", "Net Income"],
        )
        self.balance_sheet = pd.DataFrame({"2025-12-31": [2_000_000_000_000_000]}, index=["Total Assets"])
        self.cashflow = pd.DataFrame({"2025-12-31": [45_000_000_000_000]}, index=["Operating Cash Flow"])
        self.recommendations = pd.DataFrame({"firm": ["UnitTest Broker"], "toGrade": ["Buy"]})
        self.major_holders = pd.DataFrame({"Breakdown": ["Government"], "Value": ["53%"]})
        self.institutional_holders = pd.DataFrame({"Holder": ["Fund A"], "Shares": [1000]})
        self.mutualfund_holders = pd.DataFrame({"Holder": ["Fund B"], "Shares": [500]})
        self.analyst_price_targets = {"mean": 5200.0, "high": 6000.0, "low": 4300.0}

    def history(self, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        index = pd.date_range(datetime(2026, 1, 1), periods=30, freq="D")
        return pd.DataFrame(
            {
                "Open": [4000 + i for i in range(30)],
                "High": [4050 + i for i in range(30)],
                "Low": [3950 + i for i in range(30)],
                "Close": [4025 + i for i in range(30)],
                "Volume": [1_000_000 + i for i in range(30)],
            },
            index=index,
        )


def install_fake_yfinance(monkeypatch) -> None:
    FakeTicker.seen_symbols.clear()
    fake_yfinance = types.SimpleNamespace(Ticker=FakeTicker)
    monkeypatch.setitem(sys.modules, "yfinance", fake_yfinance)


def make_router(tmp_path: Path) -> CommandRouter:
    return CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=YFinanceProvider(),
        ai_provider=FakeAIProvider(),
    )


def test_yfinance_resolver_maps_common_indonesia_tickers_to_jk_suffix() -> None:
    assert resolve_yfinance_symbol("BBRI").symbol == "BBRI.JK"
    assert resolve_yfinance_symbol("bbca").symbol == "BBCA.JK"
    assert resolve_yfinance_symbol("BBRI.JK").symbol == "BBRI.JK"
    assert resolve_yfinance_symbol("AAPL").symbol == "AAPL"


def test_analyze_bbri_uses_yfinance_jk_symbol(tmp_path: Path, monkeypatch) -> None:
    install_fake_yfinance(monkeypatch)
    router = make_router(tmp_path)

    result = router.route("/analyze bbri 1d")

    assert result.status == "ready"
    assert "BBRI context received" in str(result.renderable)
    assert "BBRI.JK" in FakeTicker.seen_symbols


def test_yahoo_tables_cover_requested_yahoo_sections(monkeypatch) -> None:
    install_fake_yfinance(monkeypatch)
    provider = YFinanceProvider()

    sections = ["history", "statistics", "profile", "financials", "analysis", "holders", "news"]
    tables = [asyncio.run(provider.yahoo_table("BBRI", section)) for section in sections]

    assert {table.section for table in tables} == set(sections)
    assert all(table.symbol == "BBRI.JK" for table in tables)
    assert all(table.rows for table in tables)
    assert any("finance.yahoo.com/quote/BBRI.JK/key-statistics/" in table.source_url for table in tables)


def test_yahoo_command_outputs_rich_table(tmp_path: Path, monkeypatch) -> None:
    install_fake_yfinance(monkeypatch)
    router = make_router(tmp_path)

    result = router.route("/yahoo BBRI statistics")

    assert result.status == "ready"
    assert result.renderable.title == "Yahoo Finance statistics: BBRI.JK"
