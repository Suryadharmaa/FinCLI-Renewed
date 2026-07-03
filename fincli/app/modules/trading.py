"""Trading capability catalog, risk guard, and local paper trading engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fincli.app.brokers.base import BaseBroker
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
        *,
        equity: float | None = None,
        current_notional: float | None = None,
        daily_pnl: float | None = None,
    ) -> RiskCheckResult:
        if self.is_kill_switch_active():
            return RiskCheckResult(False, "Kill switch active. Use /trading resume to re-enable orders.")

        if side not in ALLOWED_SIDES:
            return RiskCheckResult(False, f"Invalid side: {side}. Must be buy or sell.")

        if order_type not in ALLOWED_ORDER_TYPES:
            return RiskCheckResult(False, f"Invalid order type: {order_type}. Must be one of: {', '.join(sorted(ALLOWED_ORDER_TYPES))}.")

        if quantity <= 0:
            return RiskCheckResult(False, "Quantity must be greater than 0.")

        if order_type in {"market", "limit", "stop_limit"} and (price is None or not math.isfinite(price) or price <= 0):
            if order_type == "market":
                return RiskCheckResult(False, "Market orders require a valid reference price.")
            if order_type == "limit":
                return RiskCheckResult(False, "Limit orders require a positive price.")
            return RiskCheckResult(False, "Stop-limit orders require a positive price.")

        profile = self._get_profile()
        effective_equity = equity
        if effective_equity is None and profile is not None:
            effective_equity = float(profile["equity"])
        if effective_equity is not None:
            notional = float(quantity) * float(price)
            existing = self._position_notional(symbol) if current_notional is None else float(current_notional)
            effective_daily_pnl = self._daily_pnl() if daily_pnl is None else float(daily_pnl)

            # Max position size check
            if notional > 0 and effective_equity > 0:
                new_total = existing + notional if side == "buy" else existing - notional
                projected_exposure = abs(new_total)
                if projected_exposure > effective_equity * self.max_position_pct:
                    return RiskCheckResult(
                        False,
                        f"Position size ${projected_exposure:,.2f} exceeds {self.max_position_pct:.0%} of equity (${effective_equity:,.2f}). Max allowed: ${effective_equity * self.max_position_pct:,.2f}.",
                    )

            # Daily loss limit check
            if effective_equity > 0 and effective_daily_pnl < -(effective_equity * self.daily_loss_limit_pct):
                return RiskCheckResult(
                    False,
                    f"Daily loss ${abs(effective_daily_pnl):,.2f} exceeds {self.daily_loss_limit_pct:.0%} limit (${effective_equity * self.daily_loss_limit_pct:,.2f}). Trading suspended for today.",
                )

            # Leverage warning (not a block, but flagged)
            if notional > effective_equity and side == "buy":
                return RiskCheckResult(
                    False,
                    f"Order notional ${notional:,.2f} exceeds available equity ${effective_equity:,.2f}. Leverage not allowed in paper trading.",
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
            FROM paper_orders WHERE symbol = ? AND status IN ('filled', 'queued', 'triggered')""",
            (symbol.upper(),),
        )
        if rows and rows[0]["total"] is not None:
            return float(rows[0]["total"])
        return 0.0

    def _daily_pnl(self) -> float:
        today = date.today().isoformat()
        return float(sum(
            realized
            for state in _paper_position_states(self.db).values()
            for fill_date, realized in state["daily_realized"]
            if fill_date == today
        ))


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

        if normalized_type == "stop_limit" and (stop_price is None or not math.isfinite(stop_price) or stop_price <= 0):
            raise CommandError("Stop-limit orders require a positive stop price.")

        # Risk guard check
        risk = self.risk_guard.check(normalized_side, normalized_symbol, quantity, normalized_type, price)
        if not risk.passed:
            self.audit.record("risk_blocked", f"{normalized_side} {normalized_symbol} {quantity} {normalized_type}: {risk.reason}")
            raise CommandError(f"Risk guard blocked: {risk.reason}")

        # Validation
        if normalized_side not in ALLOWED_SIDES:
            raise CommandError("Paper order side must be buy or sell.")
        if normalized_type not in ALLOWED_ORDER_TYPES:
            raise CommandError(f"Paper order type must be one of: {', '.join(sorted(ALLOWED_ORDER_TYPES))}.")
        if quantity <= 0:
            raise CommandError("Paper order quantity must be greater than 0.")
        if price is not None and price <= 0:
            raise CommandError("Paper order price must be greater than 0.")
        if normalized_type == "stop_limit" and stop_price is not None and stop_price <= 0:
            raise CommandError("Stop price must be greater than 0.")

        if normalized_side == "sell" and self._filled_quantity(normalized_symbol) + 1e-9 < quantity:
            raise CommandError("Paper sell order exceeds the filled position. Short selling is not supported.")

        status = "filled" if normalized_type == "market" else "queued"
        notional = float(quantity) * float(price)
        order_id = self.db.execute(
            """
            INSERT INTO paper_orders(side, symbol, quantity, order_type, price, stop_price, notional, status, strategy)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (normalized_side, normalized_symbol, quantity, normalized_type, price, stop_price, notional, status, strategy),
        )

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

    def process_market_price(self, symbol: str, market_price: float) -> list[dict[str, object]]:
        """Fill queued paper orders whose limit and stop conditions match a quote."""
        if not math.isfinite(market_price) or market_price <= 0:
            raise CommandError("Market price must be a positive number.")

        normalized_symbol = normalize_symbol(symbol)
        rows = self.db.query(
            """SELECT * FROM paper_orders
               WHERE symbol = ? AND status IN ('queued', 'triggered')
               ORDER BY id""",
            (normalized_symbol,),
        )
        filled: list[dict[str, object]] = []
        for row in rows:
            order = dict(row)
            status = str(order["status"])
            side = str(order["side"])
            order_type = str(order["order_type"])
            limit_price = float(order["price"])
            stop_price = order["stop_price"]

            if order_type == "stop_limit" and status == "queued":
                stop = float(stop_price)
                triggered = market_price >= stop if side == "buy" else market_price <= stop
                if not triggered:
                    continue
                self.db.execute("UPDATE paper_orders SET status = 'triggered' WHERE id = ?", (order["id"],))
                status = "triggered"
                self.audit.record("triggered", f"Order {order['id']} triggered at {market_price}", int(order["id"]))

            if status not in {"queued", "triggered"}:
                continue
            matches_limit = market_price <= limit_price if side == "buy" else market_price >= limit_price
            if not matches_limit:
                continue
            if side == "sell" and self._filled_quantity(normalized_symbol) + 1e-9 < float(order["quantity"]):
                self.db.execute("UPDATE paper_orders SET status = 'rejected' WHERE id = ?", (order["id"],))
                self.audit.record("rejected", f"Order {order['id']} exceeds filled position", int(order["id"]))
                continue
            self.db.execute("UPDATE paper_orders SET status = 'filled' WHERE id = ?", (order["id"],))
            order["status"] = "filled"
            self.audit.record("filled", f"Order {order['id']} filled at limit {limit_price}", int(order["id"]))
            filled.append(order)
        return filled

    def cancel_order(self, order_id: int) -> dict[str, object]:
        rows = self.db.query("SELECT * FROM paper_orders WHERE id = ?", (order_id,))
        if not rows:
            self.audit.record("cancel_failed", f"Order {order_id} not found")
            raise CommandError(f"Order not found: {order_id}")
        order = dict(rows[0])
        if order["status"] not in {"queued", "pending", "triggered"}:
            self.audit.record("cancel_failed", f"Order {order_id} status={order['status']}")
            raise CommandError(f"Order {order_id} cannot be cancelled (status: {order['status']}).")
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
        """Aggregate filled orders into positions using FIFO cost basis."""
        positions: list[dict[str, object]] = []
        for symbol, state in sorted(_paper_position_states(self.db).items()):
            if state["quantity"] <= 1e-9:
                continue
            positions.append({
                "symbol": symbol,
                "net_quantity": state["quantity"],
                "avg_price": state["cost"] / state["quantity"],
                "buy_notional": state["buy_notional"],
                "sell_notional": state["sell_notional"],
                "realized_pnl": state["realized_pnl"],
                "order_count": state["order_count"],
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

    def _filled_quantity(self, symbol: str) -> float:
        state = _paper_position_states(self.db).get(symbol.upper())
        return float(state["quantity"]) if state else 0.0


def _paper_position_states(db: FinCLIDatabase) -> dict[str, dict[str, object]]:
    """Replay filled orders to derive FIFO lots and realized PnL."""
    rows = db.query(
        """SELECT id, side, symbol, quantity, price, notional, created_at
           FROM paper_orders WHERE status = 'filled' ORDER BY id"""
    )
    states: dict[str, dict[str, object]] = {}
    for row in rows:
        symbol = str(row["symbol"])
        state = states.setdefault(
            symbol,
            {
                "lots": [],
                "quantity": 0.0,
                "cost": 0.0,
                "buy_notional": 0.0,
                "sell_notional": 0.0,
                "realized_pnl": 0.0,
                "daily_realized": [],
                "order_count": 0,
            },
        )
        quantity = float(row["quantity"])
        price = float(row["price"] or 0.0)
        notional = float(row["notional"])
        state["order_count"] = int(state["order_count"]) + 1
        lots: list[list[float]] = state["lots"]  # [remaining_quantity, entry_price]

        if row["side"] == "buy":
            lots.append([quantity, price])
            state["quantity"] = float(state["quantity"]) + quantity
            state["cost"] = float(state["cost"]) + notional
            state["buy_notional"] = float(state["buy_notional"]) + notional
            continue

        remaining = quantity
        realized = 0.0
        while remaining > 1e-9 and lots:
            lot_quantity, lot_price = lots[0]
            matched = min(remaining, lot_quantity)
            realized += (price - lot_price) * matched
            lot_quantity -= matched
            remaining -= matched
            state["quantity"] = float(state["quantity"]) - matched
            state["cost"] = float(state["cost"]) - lot_price * matched
            if lot_quantity <= 1e-9:
                lots.pop(0)
            else:
                lots[0][0] = lot_quantity

        state["sell_notional"] = float(state["sell_notional"]) + notional
        state["realized_pnl"] = float(state["realized_pnl"]) + realized
        fill_date = str(row["created_at"])[:10]
        daily_realized: list[tuple[str, float]] = state["daily_realized"]
        daily_realized.append((fill_date, realized))
    return states


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
    def broker(self) -> BaseBroker | None:
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
        reference_price = price or current_price
        risk = self.risk_guard.check(side, symbol, quantity, order_type, reference_price)

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
        reference_price: float | None = None,
    ) -> dict:
        """Place a live order through broker with risk checks."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker not connected. Use /trading live connect <broker>.")

        # Normalize
        normalized_side = side.strip().lower()
        normalized_type = order_type.strip().lower()
        normalized_symbol = symbol.strip().upper()

        resolved_price = await self._resolve_reference_price(
            normalized_symbol,
            normalized_type,
            price,
            reference_price,
        )
        account = await self._broker.get_account()
        positions = await self._broker.get_positions()
        existing_notional = self._live_position_notional(positions, normalized_symbol)

        # The live risk context must come from the broker, never the paper ledger.
        risk = self.risk_guard.check(
            normalized_side,
            normalized_symbol,
            quantity,
            normalized_type,
            resolved_price,
            equity=float(account.equity),
            current_notional=existing_notional,
        )
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

    async def _resolve_reference_price(
        self,
        symbol: str,
        order_type: str,
        price: float | None,
        reference_price: float | None,
    ) -> float:
        candidate = reference_price if reference_price is not None else price
        if candidate is not None and math.isfinite(candidate) and candidate > 0:
            return float(candidate)
        if order_type != "market":
            raise CommandError("Limit and stop-limit orders require a positive price.")
        get_quote = getattr(self._broker, "get_quote", None)
        if get_quote is None:
            raise CommandError("Live market orders require a reference price.")
        quote = await get_quote(symbol)
        quote_price = getattr(quote, "price", quote)
        if quote_price is None or not math.isfinite(float(quote_price)) or float(quote_price) <= 0:
            raise CommandError("Live market orders require a valid reference price.")
        return float(quote_price)

    @staticmethod
    def _live_position_notional(positions: list[object], symbol: str) -> float:
        for position in positions:
            if str(getattr(position, "symbol", "")).upper() != symbol:
                continue
            market_value = float(getattr(position, "market_value", 0.0) or 0.0)
            if market_value == 0.0:
                market_value = float(getattr(position, "quantity", 0.0)) * float(
                    getattr(position, "current_price", 0.0) or getattr(position, "avg_entry_price", 0.0)
                )
            return -abs(market_value) if str(getattr(position, "side", "long")).lower() == "short" else abs(market_value)
        return 0.0

    async def get_positions(self) -> list:
        """Get positions from broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker not connected.")
        return await self._broker.get_positions()

    async def get_account(self):
        """Get account info from broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker not connected.")
        return await self._broker.get_account()

    async def list_orders(self, status: str | None = None, limit: int = 50) -> list:
        """List orders from broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker not connected.")
        return await self._broker.list_orders(status=status, limit=limit)

    async def cancel_order(self, broker_order_id: str):
        """Cancel order at broker."""
        if not self._broker:
            from fincli.app.utils.errors import CommandError
            raise CommandError("Broker not connected.")
        result = await self._broker.cancel_order(broker_order_id)
        self.audit.record("live_order_cancelled", f"broker_order_id={broker_order_id}")
        return result
