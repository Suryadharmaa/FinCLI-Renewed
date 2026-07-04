from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from fincli.app.analysis.backtest import BacktestTrade, _monte_carlo
from fincli.app.brokers.base import BrokerAccount, BrokerOrder, BrokerPosition
from fincli.app.modules.alerts import AlertDaemon, AlertService
from fincli.app.modules.trading import LiveTradingEngine, PaperTradingEngine
from fincli.app.providers.market.base import ProviderStatus, Quote
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage import secrets as secret_store
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.secrets import read_secrets, save_secret
from fincli.app.utils.errors import CommandError, ConfigError

if TYPE_CHECKING:
    from pathlib import Path


class LiveBrokerStub:
    name = "live-stub"

    def __init__(self) -> None:
        self.submitted: list[dict[str, object]] = []

    async def get_account(self) -> BrokerAccount:
        return BrokerAccount("account", cash=1_000, portfolio_value=1_000, buying_power=1_000, equity=1_000, currency="USD", broker=self.name)

    async def get_positions(self) -> list[BrokerPosition]:
        return [BrokerPosition("AAPL", 2, 100, 100, 200, 0, "long")]

    async def place_order(self, **kwargs: object) -> BrokerOrder:
        self.submitted.append(kwargs)
        now = datetime.now(UTC)
        return BrokerOrder("live-1", "AAPL", "buy", "market", 1, None, None, "submitted", 0, None, "day", now, now, self.name)


class AlertMarketStub:
    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, 200.0, "USD", "stub", datetime.now(UTC), "delayed")


class PartialQuoteProvider:
    name = "partial"
    realtime = False

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, None, "USD", self.name, datetime.now(UTC), "partial")

    async def history(self, *args: object) -> list[object]:
        return []

    async def news(self, *args: object) -> list[object]:
        return []

    async def fundamentals(self, *args: object) -> None:
        return None

    async def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, False, "configured", "")


class ValidQuoteProvider(PartialQuoteProvider):
    name = "valid"

    async def quote(self, symbol: str) -> Quote:
        return Quote(symbol, 123.0, "USD", self.name, datetime.now(UTC), "delayed")


class FakeKeyring:
    priority = 1

    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_keyring(self) -> FakeKeyring:
        return self

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def test_market_order_requires_reference_price(tmp_path: Path) -> None:
    engine = PaperTradingEngine(FinCLIDatabase(tmp_path / "fincli.db"))

    with pytest.raises(CommandError, match="reference price"):
        engine.place_order("buy", "AAPL", 1, "market")


def test_live_order_uses_broker_position_for_risk_limit(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    db.execute(
        "INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment, gameplay) "
        "VALUES (1, 'Test', 1000, 'USD', '1:1', 1, 'Scalper')"
    )
    broker = LiveBrokerStub()
    engine = LiveTradingEngine(db)
    engine.set_broker(broker, "live")

    with pytest.raises(CommandError, match="Position size"):
        asyncio.run(engine.place_order("AAPL", "buy", 1, "market", price=100.0))

    assert broker.submitted == []


def test_limit_order_is_queued_and_stop_limit_requires_stop_price(tmp_path: Path) -> None:
    engine = PaperTradingEngine(FinCLIDatabase(tmp_path / "fincli.db"))

    limit = engine.place_order("buy", "AAPL", 1, "limit", price=100.0)
    assert limit["status"] == "queued"

    with pytest.raises(CommandError, match="Stop-limit orders require"):
        engine.place_order("buy", "AAPL", 1, "stop_limit", price=105.0)


def test_queued_limit_order_fills_when_market_price_matches(tmp_path: Path) -> None:
    engine = PaperTradingEngine(FinCLIDatabase(tmp_path / "fincli.db"))
    engine.place_order("buy", "AAPL", 1, "limit", price=100.0)

    filled = engine.process_market_price("AAPL", 99.0)

    assert len(filled) == 1
    assert filled[0]["status"] == "filled"
    assert engine.get_positions()[0]["net_quantity"] == 1


def test_partial_sell_preserves_cost_basis_and_realized_pnl(tmp_path: Path) -> None:
    engine = PaperTradingEngine(FinCLIDatabase(tmp_path / "fincli.db"))
    engine.place_order("buy", "AAPL", 10, "market", price=100.0)
    engine.place_order("sell", "AAPL", 5, "market", price=110.0)

    position = engine.get_positions()[0]
    assert position["net_quantity"] == 5
    assert position["avg_price"] == 100.0
    assert position["realized_pnl"] == 50.0


def test_alert_daemon_runs_in_a_managed_background_thread(tmp_path: Path) -> None:
    service = AlertService(FinCLIDatabase(tmp_path / "fincli.db"))
    service.add("AAPL", "above", 100.0)
    daemon = AlertDaemon(service, AlertMarketStub(), check_interval=0.01)

    daemon.start()
    try:
        deadline = time.monotonic() + 1.0
        while daemon.triggered_count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert daemon.is_running
        assert daemon.triggered_count == 1
        assert daemon.last_check is not None
    finally:
        daemon.stop()
    assert not daemon.is_running


def test_partial_provider_response_falls_back_to_valid_provider() -> None:
    service = MarketDataService([PartialQuoteProvider(), ValidQuoteProvider()])

    quote = service.run(service.quote("AAPL"))

    assert quote.provider == "valid"
    assert quote.price == 123.0


def test_monte_carlo_bootstrap_has_nonzero_variance() -> None:
    trades = [
        BacktestTrade(0, 1, 1, 1, 1, 10, 100, 0, "win"),
        BacktestTrade(1, 2, 1, 1, 1, -5, -50, 0, "loss"),
        BacktestTrade(2, 3, 1, 1, 1, 3, 30, 0, "win"),
    ]

    result = _monte_carlo(trades, 1_000, 100, seed=7)

    assert result.std_return > 0
    assert result.percentile_5 < result.percentile_95


def test_secret_store_does_not_write_secret_file_after_keyring_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "secrets.env"
    monkeypatch.setattr(secret_store, "_keyring", FakeKeyring())

    save_secret("GROQ_API_KEY", "test-groq-key", path=target)

    assert not target.exists()


def test_secret_store_migrates_legacy_file_to_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "secrets.env"
    target.write_text('GROQ_API_KEY="legacy-key"\n', encoding="utf-8")
    monkeypatch.setattr(secret_store, "_keyring", FakeKeyring())

    assert read_secrets(target) == {"GROQ_API_KEY": "legacy-key"}
    assert not target.exists()


def test_secret_store_reports_unavailable_keyring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_store, "_keyring", None)

    with pytest.raises(ConfigError):
        save_secret("GROQ_API_KEY", "blocked", path=tmp_path / "secrets.env")
