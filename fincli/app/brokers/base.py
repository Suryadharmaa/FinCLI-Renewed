"""Abstract broker interface for live trading."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"  # Good Till Cancelled
    IOC = "ioc"  # Immediate or Cancel
    FOK = "fok"  # Fill or Kill


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    """Position held at broker."""
    symbol: str
    quantity: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    side: str  # "long" or "short"


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    """Order submitted to broker."""
    broker_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None
    stop_price: float | None
    status: str
    filled_quantity: float
    filled_price: float | None
    time_in_force: str
    created_at: datetime
    updated_at: datetime
    broker: str


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    """Broker account info."""
    account_id: str
    cash: float
    portfolio_value: float
    buying_power: float
    equity: float
    currency: str
    broker: str


@dataclass(frozen=True, slots=True)
class BrokerConnectionStatus:
    """Connection status to broker."""
    connected: bool
    broker: str
    mode: str  # "paper" or "live"
    account_id: str | None
    message: str


class BaseBroker(ABC):
    """Abstract base class for broker integrations."""

    name: str
    supported_modes: tuple[str, ...]  # ("paper", "live")

    @abstractmethod
    async def connect(self, mode: str = "paper") -> BrokerConnectionStatus:
        """Connect to broker. Returns connection status."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from broker."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if connected to broker."""
        ...

    @abstractmethod
    async def get_account(self) -> BrokerAccount:
        """Get account info."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        """Get all open positions."""
        ...

    @abstractmethod
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
        """Place an order. Returns the submitted order."""
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        """Cancel a pending order."""
        ...

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        """Get order status."""
        ...

    @abstractmethod
    async def list_orders(self, status: str | None = None, limit: int = 50) -> list[BrokerOrder]:
        """List orders, optionally filtered by status."""
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> float:
        """Get current price for a symbol."""
        ...
