"""Trading capability catalog, risk guard, and local paper trading engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError
from fincli.app.utils.formatting import normalize_symbol


# ---------------------------------------------------------------------------
# Catalog models
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Catalogs
# ---------------------------------------------------------------------------


class RealtimeConnectorCatalog:
    """Connector catalog for realtime/push market data capability planning."""

    def all(self) -> tuple[RealtimeConnector, ...]:
        return (
            RealtimeConnector(
                "Kraken WebSocket",
                "websocket",
                ("crypto",),
                "configurable",
                "Crypto realtime feed. Requires Kraken WS adapter. Public ticker/trades/ohlc; private with API key.",
            ),
            RealtimeConnector(
                "HyperLiquid WebSocket",
                "websocket",
                ("crypto", "perpetuals"),
                "configurable",
                "HyperLiquid realtime orderbook/trades/mids. Crypto/perps only.",
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
            BrokerIntegration("IBKR", "Global", ("equity", "options", "futures", "forex"), "gateway_required", "TWS/Gateway adapter. Requires local IB Gateway running."),
            BrokerIntegration("Alpaca", "US", global_assets, "paper_ready", "Paper trading adapter. Requires ALPACA_API_KEY + ALPACA_SECRET_KEY."),
            BrokerIntegration("Tradier", "US", global_assets, "sandbox_ready", "Sandbox adapter. Requires TRADIER_TOKEN."),
            BrokerIntegration("Saxo", "Global", ("equity", "forex", "cfd", "futures"), "adapter_stub", "OpenAPI adapter planned."),
        )


# ---------------------------------------------------------------------------
# Risk Guard
# ---------------------------------------------------------------------------

DEFAULT_MAX_POSITION_PCT = 0.20
DEFAULT_DAILY_LOSS_LIMIT_PCT = 0.05
ALLOWED_ORDER_TYPES = {"market", "limit", "stop_limit"}
ALLOWED_SIDES = {"buy", "sell"}


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    passed: bool
    reason: str


class RiskGuard:
    """Pre-trade risk checks. Applied before every paper order."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db
        self.max_position_pct: float = DEFAULT_MAX_POSITION_PCT
        self.daily_loss_limit_pct: float = DEFAULT_DAILY_LOSS_LIMIT_PCT

    def check(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str,
        price: float | None = None,
        asset_class: str = "equity",
    ) -> RiskCheckResult:
        if self.is_kill_switch_active():
            return RiskCheckResult(False, "Kill switch active. Use /trading resume to re-enable orders.")

        if side not in ALLOWED_SIDES:
            return RiskCheckResult(False, f"Invalid side: {side}. Must be buy or sell.")

        if order_type not in ALLOWED_ORDER_TYPES:
            return RiskCheckResult(False, f"Invalid order type: {order_type}. Must be one of: {', '.join(sorted(ALLOWED_ORDER_TYPES))}.")

        if quantity <= 0:
            return RiskCheckResult(False, "Quantity must be greater than 0.")

        if order_type == "limit" and (price is None or price <= 0):
            return RiskCheckResult(False, "Limit orders require a positive price.")

        if order_type == "stop_limit" and (price is None or price <= 0):
            return RiskCheckResult(False, "Stop-limit orders require a positive price.")

        profile = self._get_profile()
        if profile is not None:
            equity = float(profile["equity"])
            notional = float(quantity) * float(price or 0)

            # Max position size check
            if notional > 0 and equity > 0:
                existing = self._position_notional(symbol)
                new_total = existing + notional if side == "buy" else existing - notional
                if new_total > equity * self.max_position_pct:
                    return RiskCheckResult(
                        False,
                        f"Position size ${new_total:,.2f} exceeds {self.max_position_pct:.0%} of equity (${equity:,.2f}). Max allowed: ${equity * self.max_position_pct:,.2f}.",
                    )

            # Daily loss limit check
            daily_pnl = self._daily_pnl()
            if equity > 0 and daily_pnl < -(equity * self.daily_loss_limit_pct):
                return RiskCheckResult(
                    False,
                    f"Daily loss ${abs(daily_pnl):,.2f} exceeds {self.daily_loss_limit_pct:.0%} limit (${equity * self.daily_loss_limit_pct:,.2f}). Trading suspended for today.",
                )

            # Leverage warning (not a block, but flagged)
            if notional > equity and side == "buy":
                return RiskCheckResult(
                    False,
                    f"Order notional ${notional:,.2f} exceeds available equity ${equity:,.2f}. Leverage not allowed in paper trading.",
                )

        return RiskCheckResult(True, "passed")

    def is_kill_switch_active(self) -> bool:
        rows = self.db.query("SELECT active FROM kill_switch WHERE id = 1")
        if not rows:
            return False
        return bool(rows[0]["active"])

    def set_kill_switch(self, active: bool, reason: str = "") -> None:
        self.db.execute(
            """
            INSERT INTO kill_switch (id, active, reason, updated_at)
            VALUES (1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET active = excluded.active, reason = excluded.reason, updated_at = CURRENT_TIMESTAMP
            """,
            (int(active), reason),
        )

    def _get_profile(self) -> object | None:
        rows = self.db.query("SELECT * FROM user_profile WHERE id = 1")
        return rows[0] if rows else None

    def _position_notional(self, symbol: str) -> float:
        # Net notional: buy orders minus sell orders
        rows = self.db.query(
            """SELECT
                SUM(CASE WHEN side = 'buy' THEN notional ELSE 0 END) -
                SUM(CASE WHEN side = 'sell' THEN notional ELSE 0 END) as total
            FROM paper_orders WHERE symbol = ? AND status IN ('filled', 'queued')""",
            (symbol.upper(),),
        )
        if rows and rows[0]["total"] is not None:
            return float(rows[0]["total"])
        return 0.0

    def _daily_pnl(self) -> float:
        today = date.today().isoformat()
        rows = self.db.query(
            "SELECT SUM(notional) as total FROM paper_orders WHERE date(created_at) = ? AND status = 'filled' AND side = 'sell'",
            (today,),
        )
        sell_total = float(rows[0]["total"]) if rows and rows[0]["total"] is not None else 0.0
        rows = self.db.query(
            "SELECT SUM(notional) as total FROM paper_orders WHERE date(created_at) = ? AND status = 'filled' AND side = 'buy'",
            (today,),
        )
        buy_total = float(rows[0]["total"]) if rows and rows[0]["total"] is not None else 0.0
        return sell_total - buy_total


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------


class OrderAuditLog:
    """Immutable audit log for all order attempts."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def record(self, action: str, detail: str = "", order_id: int | None = None) -> None:
        self.db.execute(
            "INSERT INTO order_audit_log (order_id, action, detail) VALUES (?, ?, ?)",
            (order_id, action, detail),
        )

    def list_entries(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self.db.query(
            "SELECT id, order_id, action, detail, created_at FROM order_audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Paper Trading Engine (enhanced v0.7.0)
# ---------------------------------------------------------------------------


class PaperTradingEngine:
    """Local paper trading engine with risk guard and audit log.

    It never sends live broker orders.
    """

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db
        self.risk_guard = RiskGuard(db)
        self.audit = OrderAuditLog(db)

    def place_order(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
        strategy: str = "manual",
    ) -> dict[str, object]:
        normalized_side = side.strip().lower()
        normalized_type = order_type.strip().lower()
        normalized_symbol = normalize_symbol(symbol)

        # Risk guard check
        risk = self.risk_guard.check(normalized_side, normalized_symbol, quantity, normalized_type, price)
        if not risk.passed:
            self.audit.record("risk_blocked", f"{normalized_side} {normalized_symbol} {quantity} {normalized_type}: {risk.reason}")
            raise CommandError(f"Risk guard blocked: {risk.reason}")

        # Validation
        if normalized_side not in ALLOWED_SIDES:
            raise CommandError("Paper order side harus buy atau sell.")
        if normalized_type not in ALLOWED_ORDER_TYPES:
            raise CommandError(f"Paper order type harus salah satu dari: {', '.join(sorted(ALLOWED_ORDER_TYPES))}.")
        if quantity <= 0:
            raise CommandError("Paper order quantity harus lebih besar dari 0.")
        if price is not None and price <= 0:
            raise CommandError("Paper order price harus lebih besar dari 0.")
        if normalized_type == "stop_limit" and stop_price is not None and stop_price <= 0:
            raise CommandError("Stop price harus lebih besar dari 0.")

        status = "filled" if normalized_type == "market" or price is not None else "queued"
        # For market orders without price, use 0 notional (risk guard will skip position check)
        # For limit/stop orders, calculate notional from price
        notional = float(quantity) * float(price or 0)
        self.db.execute(
            """
            INSERT INTO paper_orders(side, symbol, quantity, order_type, price, stop_price, notional, status, strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (normalized_side, normalized_symbol, quantity, normalized_type, price, stop_price, notional, status, strategy),
        )

        # Get the order ID from the most recent insert
        rows = self.db.query("SELECT MAX(id) as id FROM paper_orders WHERE symbol = ? AND side = ? AND status = ?", (normalized_symbol, normalized_side, status))
        order_id = int(rows[0]["id"]) if rows and rows[0]["id"] is not None else None

        self.audit.record("placed", f"{normalized_side} {normalized_symbol} {quantity} {normalized_type} status={status}", order_id)

        return {
            "id": order_id,
            "side": normalized_side,
            "symbol": normalized_symbol,
            "quantity": quantity,
            "order_type": normalized_type,
            "price": price,
            "stop_price": stop_price,
            "notional": notional,
            "status": status,
            "strategy": strategy,
        }

    def cancel_order(self, order_id: int) -> dict[str, object]:
        rows = self.db.query("SELECT * FROM paper_orders WHERE id = ?", (order_id,))
        if not rows:
            self.audit.record("cancel_failed", f"Order {order_id} not found")
            raise CommandError(f"Order tidak ditemukan: {order_id}")
        order = dict(rows[0])
        if order["status"] not in {"queued", "pending"}:
            self.audit.record("cancel_failed", f"Order {order_id} status={order['status']}")
            raise CommandError(f"Order {order_id} tidak bisa dibatalkan (status: {order['status']}).")
        self.db.execute("UPDATE paper_orders SET status = 'cancelled' WHERE id = ?", (order_id,))
        self.audit.record("cancelled", f"Order {order_id} cancelled", order_id)
        order["status"] = "cancelled"
        return order

    def list_orders(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self.db.query(
            """
            SELECT id, side, symbol, quantity, order_type, price, stop_price, notional, status, strategy, created_at
            FROM paper_orders
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def get_positions(self) -> list[dict[str, object]]:
        """Aggregate filled orders into net positions per symbol."""
        rows = self.db.query(
            """
            SELECT symbol,
                   SUM(CASE WHEN side = 'buy' THEN quantity ELSE -quantity END) as net_qty,
                   SUM(CASE WHEN side = 'buy' THEN notional ELSE 0 END) as buy_notional,
                   SUM(CASE WHEN side = 'sell' THEN notional ELSE 0 END) as sell_notional,
                   COUNT(*) as order_count
            FROM paper_orders
            WHERE status = 'filled'
            GROUP BY symbol
            HAVING ABS(net_qty) > 0.00000001
            ORDER BY symbol
            """
        )
        positions: list[dict[str, object]] = []
        for row in rows:
            net_qty = float(row["net_qty"])
            buy_not = float(row["buy_notional"])
            sell_not = float(row["sell_notional"])
            avg_price = buy_not / net_qty if net_qty > 0 else 0.0
            positions.append({
                "symbol": row["symbol"],
                "net_quantity": net_qty,
                "avg_price": avg_price,
                "buy_notional": buy_not,
                "sell_notional": sell_not,
                "realized_pnl": sell_not - buy_not if net_qty <= 0 else 0.0,
                "order_count": row["order_count"],
            })
        return positions

    def daily_pnl(self) -> float:
        return self.risk_guard._daily_pnl()

    def is_kill_switch_active(self) -> bool:
        return self.risk_guard.is_kill_switch_active()

    def set_kill_switch(self, active: bool, reason: str = "") -> None:
        self.risk_guard.set_kill_switch(active, reason)
        action = "kill_switch_activated" if active else "kill_switch_deactivated"
        self.audit.record(action, reason)


# ---------------------------------------------------------------------------
# Live Trading Engine (v1.1.0)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiveOrderConfirmation:
    """Order confirmation details for user review before live execution."""
    symbol: str
    side: str
    quantity: float
    order_type: str
    price: float | None
    stop_price: float | None
    estimated_cost: float
    risk_check_passed: bool
    risk_check_reason: str
    broker: str
    mode: str  # "paper" or "live"


class LiveTradingEngine:
    """Live trading engine with broker integration, risk guard, and audit log.

    Wraps broker connections with the same safety layer as paper trading.
    """

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db
        self.risk_guard = RiskGuard(db)
        self.audit = OrderAuditLog(db)
        self._broker = None
        self._broker_name: str | None = None
        self._mode: str = "paper"

    @property
    def broker(self):
        return self._broker

    @property
    def broker_name(self) -> str | None:
        return self._broker_name

    @property
    def mode(self) -> str:
        return self._mode

    def set_broker(self, broker, mode: str = "paper") -> None:
        """Set the active broker instance."""
        self._broker = broker
        self._broker_name = broker.name if broker else None
        self._mode = mode

    def is_connected(self) -> bool:
        """Check if broker is connected."""
        return self._broker is not None

    def build_confirmation(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
        current_price: float = 0.0,
    ) -> LiveOrderConfirmation:
        """Build order confirmation for user review."""
        # Run risk check
        risk = self.risk_guard.check(side, symbol, quantity, order_type, price)

        # Estimate cost
        estimated_price = price or current_price
        estimated_cost = quantity * estimated_price

        return LiveOrderConfirmation(
            symbol=symbol.upper(),
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
            stop_price=stop_price,
            estimated_cost=estimated_cost,
            risk_check_passed=risk.passed,
            risk_check_reason=risk.reason,
            broker=self._broker_name or "none",
            mode=self._mode,
        )

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "day",
    ) -> dict:
        """Place a live order through broker with risk checks."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker belum terhubung. Gunakan /trading live connect <broker>.")

        # Normalize
        normalized_side = side.strip().lower()
        normalized_type = order_type.strip().lower()
        normalized_symbol = symbol.strip().upper()

        # Risk guard check (same as paper trading)
        risk = self.risk_guard.check(normalized_side, normalized_symbol, quantity, normalized_type, price)
        if not risk.passed:
            self.audit.record(
                "live_risk_blocked",
                f"{normalized_side} {normalized_symbol} {quantity} {normalized_type}: {risk.reason}",
            )
            from fincli.app.utils.errors import CommandError
            raise CommandError(f"Risk guard blocked: {risk.reason}")

        # Place order via broker
        try:
            broker_order = await self._broker.place_order(
                symbol=normalized_symbol,
                side=normalized_side,
                quantity=quantity,
                order_type=normalized_type,
                price=price,
                stop_price=stop_price,
                time_in_force=time_in_force,
            )

            # Record in audit log
            self.audit.record(
                "live_order_placed",
                f"{normalized_side} {normalized_symbol} {quantity} {normalized_type} "
                f"broker={self._broker_name} mode={self._mode} "
                f"broker_order_id={broker_order.broker_order_id} status={broker_order.status}",
            )

            return {
                "broker_order_id": broker_order.broker_order_id,
                "symbol": broker_order.symbol,
                "side": broker_order.side,
                "quantity": broker_order.quantity,
                "order_type": broker_order.order_type,
                "price": broker_order.price,
                "status": broker_order.status,
                "broker": self._broker_name,
                "mode": self._mode,
            }
        except Exception as exc:
            self.audit.record(
                "live_order_failed",
                f"{normalized_side} {normalized_symbol} {quantity} {normalized_type}: {exc}",
            )
            raise

    async def get_positions(self) -> list:
        """Get positions from broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker belum terhubung.")
        return await self._broker.get_positions()

    async def get_account(self):
        """Get account info from broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker belum terhubung.")
        return await self._broker.get_account()

    async def list_orders(self, status: str | None = None, limit: int = 50) -> list:
        """List orders from broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker belum terhubung.")
        return await self._broker.list_orders(status=status, limit=limit)

    async def cancel_order(self, broker_order_id: str):
        """Cancel order at broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker belum terhubung.")
        result = await self._broker.cancel_order(broker_order_id)
        self.audit.record("live_order_cancelled", f"broker_order_id={broker_order_id}")
        return result
