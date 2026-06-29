"""Tests for v1.1.0 live trading features: broker integration, live trading engine, order confirmation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fincli.app.brokers.base import (
    BaseBroker,
    BrokerAccount,
    BrokerConnectionStatus,
    BrokerOrder,
    BrokerPosition,
)
from fincli.app.brokers.registry import BrokerInfo, BrokerRegistry, BROKER_CATALOG
from fincli.app.modules.trading import LiveTradingEngine, LiveOrderConfirmation
from fincli.app.storage.database import FinCLIDatabase


# --- Mock Broker ---


class MockBroker(BaseBroker):
    """Mock broker for testing."""

    name = "mock"
    supported_modes = ("paper", "live")

    def __init__(self) -> None:
        self._connected = False
        self._mode = "paper"
        self._orders: list[BrokerOrder] = []

    async def connect(self, mode: str = "paper") -> BrokerConnectionStatus:
        self._connected = True
        self._mode = mode
        return BrokerConnectionStatus(
            connected=True,
            broker=self.name,
            mode=mode,
            account_id="mock-account-123",
            message=f"Connected to mock broker ({mode})",
        )

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    async def get_account(self) -> BrokerAccount:
        return BrokerAccount(
            account_id="mock-account-123",
            cash=100000.0,
            portfolio_value=150000.0,
            buying_power=200000.0,
            equity=150000.0,
            currency="USD",
            broker=self.name,
        )

    async def get_positions(self) -> list[BrokerPosition]:
        return [
            BrokerPosition(
                symbol="AAPL",
                quantity=10,
                avg_entry_price=150.0,
                current_price=175.0,
                market_value=1750.0,
                unrealized_pnl=250.0,
                side="long",
            )
        ]

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "day",
    ) -> BrokerOrder:
        order = BrokerOrder(
            broker_order_id=f"mock-order-{len(self._orders) + 1}",
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status="submitted",
            filled_quantity=0,
            filled_price=None,
            time_in_force=time_in_force,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            broker=self.name,
        )
        self._orders.append(order)
        return order

    async def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        for order in self._orders:
            if order.broker_order_id == broker_order_id:
                return BrokerOrder(
                    broker_order_id=order.broker_order_id,
                    symbol=order.symbol,
                    side=order.side,
                    order_type=order.order_type,
                    quantity=order.quantity,
                    price=order.price,
                    stop_price=order.stop_price,
                    status="cancelled",
                    filled_quantity=order.filled_quantity,
                    filled_price=order.filled_price,
                    time_in_force=order.time_in_force,
                    created_at=order.created_at,
                    updated_at=datetime.now(UTC),
                    broker=self.name,
                )
        raise ValueError(f"Order not found: {broker_order_id}")

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        for order in self._orders:
            if order.broker_order_id == broker_order_id:
                return order
        raise ValueError(f"Order not found: {broker_order_id}")

    async def list_orders(self, status: str | None = None, limit: int = 50) -> list[BrokerOrder]:
        return self._orders[:limit]

    async def get_quote(self, symbol: str) -> float:
        return 175.0


# --- Broker Base Tests ---


class TestBrokerBase:
    def test_broker_interface_is_abstract(self):
        with pytest.raises(TypeError):
            BaseBroker()  # type: ignore


# --- Broker Registry Tests ---


class TestBrokerRegistry:
    def test_list_brokers(self):
        registry = BrokerRegistry()
        brokers = registry.list_brokers()
        assert len(brokers) >= 1
        assert any(b.name == "alpaca" for b in brokers)

    def test_get_info_alpaca(self):
        registry = BrokerRegistry()
        info = registry.get_info("alpaca")
        assert info is not None
        assert info.name == "alpaca"
        assert "paper" in info.modes
        assert "live" in info.modes

    def test_get_info_unknown(self):
        registry = BrokerRegistry()
        info = registry.get_info("unknown_broker")
        assert info is None

    def test_create_alpaca(self):
        registry = BrokerRegistry()
        broker = registry.create("alpaca")
        assert broker.name == "alpaca"

    def test_create_unknown_raises(self):
        registry = BrokerRegistry()
        with pytest.raises(ValueError, match="Unsupported broker"):
            registry.create("unknown")

    def test_broker_catalog_has_alpaca(self):
        assert "alpaca" in BROKER_CATALOG
        info = BROKER_CATALOG["alpaca"]
        assert "ALPACA_API_KEY" in info.env_keys
        assert "ALPACA_SECRET_KEY" in info.env_keys


# --- Live Trading Engine Tests ---


class TestLiveTradingEngine:
    def _make_engine(self, tmp_path: Path) -> tuple[LiveTradingEngine, MockBroker]:
        db = FinCLIDatabase(tmp_path / "fincli.db")
        engine = LiveTradingEngine(db)
        broker = MockBroker()
        engine.set_broker(broker, "paper")
        return engine, broker

    def test_initial_state(self, tmp_path: Path):
        db = FinCLIDatabase(tmp_path / "fincli.db")
        engine = LiveTradingEngine(db)
        assert not engine.is_connected()
        assert engine.broker is None
        assert engine.broker_name is None

    def test_set_broker(self, tmp_path: Path):
        engine, broker = self._make_engine(tmp_path)
        assert engine.is_connected()
        assert engine.broker_name == "mock"
        assert engine.mode == "paper"

    def test_build_confirmation(self, tmp_path: Path):
        engine, _ = self._make_engine(tmp_path)
        conf = engine.build_confirmation(
            symbol="AAPL",
            side="buy",
            quantity=10,
            order_type="market",
            current_price=175.0,
        )
        assert conf.symbol == "AAPL"
        assert conf.side == "buy"
        assert conf.quantity == 10
        assert conf.estimated_cost == 1750.0
        assert conf.risk_check_passed is True
        assert conf.broker == "mock"
        assert conf.mode == "paper"

    def test_build_confirmation_with_limit_price(self, tmp_path: Path):
        engine, _ = self._make_engine(tmp_path)
        conf = engine.build_confirmation(
            symbol="AAPL",
            side="buy",
            quantity=10,
            order_type="limit",
            price=170.0,
            current_price=175.0,
        )
        assert conf.price == 170.0
        assert conf.estimated_cost == 1700.0

    def test_place_order(self, tmp_path: Path):
        engine, broker = self._make_engine(tmp_path)
        result = asyncio.run(engine.place_order(
            symbol="AAPL",
            side="buy",
            quantity=10,
            order_type="market",
        ))
        assert result["symbol"] == "AAPL"
        assert result["side"] == "buy"
        assert result["quantity"] == 10
        assert result["status"] == "submitted"
        assert result["broker"] == "mock"
        assert result["broker_order_id"].startswith("mock-order-")

    def test_place_order_no_broker(self, tmp_path: Path):
        db = FinCLIDatabase(tmp_path / "fincli.db")
        engine = LiveTradingEngine(db)
        with pytest.raises(Exception, match="Broker not connected"):
            asyncio.run(engine.place_order(symbol="AAPL", side="buy", quantity=10))

    def test_get_positions(self, tmp_path: Path):
        engine, _ = self._make_engine(tmp_path)
        positions = asyncio.run(engine.get_positions())
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 10

    def test_get_account(self, tmp_path: Path):
        engine, _ = self._make_engine(tmp_path)
        account = asyncio.run(engine.get_account())
        assert account.account_id == "mock-account-123"
        assert account.cash == 100000.0

    def test_list_orders(self, tmp_path: Path):
        engine, _ = self._make_engine(tmp_path)
        # Place an order first
        asyncio.run(engine.place_order(symbol="AAPL", side="buy", quantity=10))
        orders = asyncio.run(engine.list_orders())
        assert len(orders) == 1

    def test_cancel_order(self, tmp_path: Path):
        engine, _ = self._make_engine(tmp_path)
        result = asyncio.run(engine.place_order(symbol="AAPL", side="buy", quantity=10, order_type="limit", price=170.0))
        order_id = result["broker_order_id"]
        cancelled = asyncio.run(engine.cancel_order(order_id))
        assert cancelled.status == "cancelled"


# --- Order Confirmation Tests ---


class TestOrderConfirmation:
    def test_confirmation_fields(self):
        conf = LiveOrderConfirmation(
            symbol="AAPL",
            side="buy",
            quantity=10,
            order_type="market",
            price=None,
            stop_price=None,
            estimated_cost=1750.0,
            risk_check_passed=True,
            risk_check_reason="passed",
            broker="alpaca",
            mode="paper",
        )
        assert conf.symbol == "AAPL"
        assert conf.side == "buy"
        assert conf.risk_check_passed is True
        assert conf.broker == "alpaca"

    def test_confirmation_with_risk_block(self):
        conf = LiveOrderConfirmation(
            symbol="AAPL",
            side="buy",
            quantity=1000,
            order_type="market",
            price=None,
            stop_price=None,
            estimated_cost=175000.0,
            risk_check_passed=False,
            risk_check_reason="Position size exceeds 20% of equity",
            broker="alpaca",
            mode="live",
        )
        assert not conf.risk_check_passed
        assert "exceeds" in conf.risk_check_reason
