"""Broker registry and factory for live trading."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.brokers.alpaca import AlpacaBroker
from fincli.app.brokers.base import BaseBroker, BrokerConnectionStatus


@dataclass(frozen=True, slots=True)
class BrokerInfo:
    """Info about a supported broker."""
    name: str
    display_name: str
    regions: tuple[str, ...]
    asset_classes: tuple[str, ...]
    modes: tuple[str, ...]  # "paper", "live"
    env_keys: tuple[str, ...]  # required env vars
    description: str


# Supported brokers
BROKER_CATALOG: dict[str, BrokerInfo] = {
    "alpaca": BrokerInfo(
        name="alpaca",
        display_name="Alpaca",
        regions=("US",),
        asset_classes=("equity", "options", "etf"),
        modes=("paper", "live"),
        env_keys=("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        description="US equity broker. Paper and live trading. Free API for paper trading.",
    ),
    "binance": BrokerInfo(
        name="binance",
        display_name="Binance",
        regions=("Global",),
        asset_classes=("crypto",),
        modes=("testnet", "live"),
        env_keys=("BINANCE_API_KEY", "BINANCE_API_SECRET"),
        description="Crypto exchange. Testnet and live trading. Largest crypto exchange by volume.",
    ),
}


class BrokerRegistry:
    """Registry and factory for broker instances."""

    def __init__(self) -> None:
        self._active_broker: BaseBroker | None = None
        self._active_name: str | None = None
        self._connection_status: BrokerConnectionStatus | None = None

    def list_brokers(self) -> list[BrokerInfo]:
        """List all supported brokers."""
        return list(BROKER_CATALOG.values())

    def get_info(self, name: str) -> BrokerInfo | None:
        """Get broker info by name."""
        return BROKER_CATALOG.get(name.lower())

    def create(self, name: str) -> BaseBroker:
        """Create a broker instance by name."""
        name_lower = name.lower()
        if name_lower == "alpaca":
            return AlpacaBroker()
        if name_lower == "binance":
            from fincli.app.brokers.binance import BinanceBroker
            return BinanceBroker()
        raise ValueError(f"Unsupported broker: {name}. Available brokers: {', '.join(BROKER_CATALOG.keys())}")

    async def connect(self, name: str, mode: str = "paper") -> BrokerConnectionStatus:
        """Connect to a broker."""
        broker = self.create(name)
        status = await broker.connect(mode)
        if status.connected:
            self._active_broker = broker
            self._active_name = name.lower()
            self._connection_status = status
        return status

    async def disconnect(self) -> None:
        """Disconnect from active broker."""
        if self._active_broker:
            await self._active_broker.disconnect()
            self._active_broker = None
            self._active_name = None
            self._connection_status = None

    @property
    def active_broker(self) -> BaseBroker | None:
        """Get the active broker instance."""
        return self._active_broker

    @property
    def active_name(self) -> str | None:
        """Get the active broker name."""
        return self._active_name

    @property
    def connection_status(self) -> BrokerConnectionStatus | None:
        """Get the connection status."""
        return self._connection_status

    def is_connected(self) -> bool:
        """Check if a broker is connected."""
        return self._active_broker is not None
