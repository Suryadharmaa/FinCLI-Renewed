"""Trading capability catalog and local paper trading engine."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError
from fincli.app.utils.formatting import normalize_symbol


@dataclass(frozen=True, slots=True)
class RealtimeConnector:
    name: str
    transport: str
    asset_classes: tuple[str, ...]
    status: str
    note: str


@dataclass(frozen=True, slots=True)
class BrokerIntegration:
    name: str
    region: str
    asset_classes: tuple[str, ...]
    mode: str
    note: str


class RealtimeConnectorCatalog:
    """Connector catalog for realtime/push market data capability planning."""

    def all(self) -> tuple[RealtimeConnector, ...]:
        return (
            RealtimeConnector(
                "Kraken WebSocket",
                "websocket",
                ("crypto",),
                "adapter_stub",
                "Crypto realtime feed scaffold. Requires Kraken WS adapter before live streaming.",
            ),
            RealtimeConnector(
                "HyperLiquid WebSocket",
                "websocket",
                ("crypto", "perpetuals"),
                "adapter_stub",
                "HyperLiquid realtime/orderbook scaffold. No live execution in v0.4.0.",
            ),
            RealtimeConnector(
                "Equity Quote Feed",
                "polling/provider",
                ("equity", "etf", "index"),
                "provider_backed",
                "Uses configured market providers; realtime depends on provider entitlement.",
            ),
        )


class BrokerCatalog:
    """Catalog of planned broker integrations with safe non-live defaults."""

    def all(self) -> tuple[BrokerIntegration, ...]:
        india = ("equity", "fno", "mutual_fund")
        global_assets = ("equity", "options", "etf")
        return (
            BrokerIntegration("Zerodha", "India", india, "adapter_stub", "Kite Connect adapter planned."),
            BrokerIntegration("Angel One", "India", india, "adapter_stub", "SmartAPI adapter planned."),
            BrokerIntegration("Upstox", "India", india, "adapter_stub", "Upstox API adapter planned."),
            BrokerIntegration("Fyers", "India", india, "adapter_stub", "Fyers API adapter planned."),
            BrokerIntegration("Dhan", "India", india, "adapter_stub", "Dhan API adapter planned."),
            BrokerIntegration("Groww", "India", ("equity", "mutual_fund"), "adapter_stub", "Broker API availability varies."),
            BrokerIntegration("Kotak", "India", india, "adapter_stub", "Kotak Neo adapter planned."),
            BrokerIntegration("IIFL", "India", india, "adapter_stub", "IIFL API adapter planned."),
            BrokerIntegration("5paisa", "India", india, "adapter_stub", "5paisa API adapter planned."),
            BrokerIntegration("AliceBlue", "India", india, "adapter_stub", "Ant API adapter planned."),
            BrokerIntegration("Shoonya", "India", india, "adapter_stub", "Shoonya/Noren adapter planned."),
            BrokerIntegration("Motilal", "India", india, "adapter_stub", "Motilal Oswal adapter planned."),
            BrokerIntegration("IBKR", "Global", ("equity", "options", "futures", "forex"), "adapter_stub", "TWS/Gateway adapter planned."),
            BrokerIntegration("Alpaca", "US", global_assets, "paper_ready", "Paper/live adapter candidate; v0.4.0 remains local paper only."),
            BrokerIntegration("Tradier", "US", global_assets, "adapter_stub", "Tradier brokerage adapter planned."),
            BrokerIntegration("Saxo", "Global", ("equity", "forex", "cfd", "futures"), "adapter_stub", "OpenAPI adapter planned."),
        )


class PaperTradingEngine:
    """Local paper trading engine. It never sends live broker orders."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def place_order(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        strategy: str = "manual",
    ) -> dict[str, object]:
        normalized_side = side.strip().lower()
        normalized_type = order_type.strip().lower()
        normalized_symbol = normalize_symbol(symbol)
        if normalized_side not in {"buy", "sell"}:
            raise CommandError("Paper order side harus buy atau sell.")
        if normalized_type not in {"market", "limit"}:
            raise CommandError("Paper order type harus market atau limit.")
        if quantity <= 0:
            raise CommandError("Paper order quantity harus lebih besar dari 0.")
        if price is not None and price <= 0:
            raise CommandError("Paper order price harus lebih besar dari 0.")

        status = "filled" if normalized_type == "market" or price is not None else "queued"
        notional = float(quantity) * float(price or 0)
        self.db.execute(
            """
            INSERT INTO paper_orders(side, symbol, quantity, order_type, price, notional, status, strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (normalized_side, normalized_symbol, quantity, normalized_type, price, notional, status, strategy),
        )
        return {
            "side": normalized_side,
            "symbol": normalized_symbol,
            "quantity": quantity,
            "order_type": normalized_type,
            "price": price,
            "notional": notional,
            "status": status,
            "strategy": strategy,
        }

    def list_orders(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self.db.query(
            """
            SELECT id, side, symbol, quantity, order_type, price, notional, status, strategy, created_at
            FROM paper_orders
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]
