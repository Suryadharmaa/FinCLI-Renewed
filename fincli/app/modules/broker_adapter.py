"""Broker sandbox adapters for paper/live trading (Phase 0.7.0).

All adapters are disabled by default. When activated via /trading broker use,
paper orders can optionally route through the adapter. Without the --live flag,
orders stay local-only even when a broker adapter is active.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from fincli.app.utils.errors import ProviderError


# ---------------------------------------------------------------------------
# Standardized broker models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BrokerOrder:
    """Normalized order representation across all broker adapters."""

    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    status: str
    price: float | None = None
    filled_qty: float = 0.0
    filled_price: float | None = None
    submitted_at: str = ""


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    """Normalized position representation."""

    symbol: str
    quantity: float
    avg_entry_price: float
    market_value: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass(frozen=True, slots=True)
class BrokerAccount:
    """Normalized account summary."""

    equity: float
    cash: float
    buying_power: float
    currency: str = "USD"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BrokerAdapter(Protocol):
    """Interface that all broker adapters must implement."""

    name: str
    status: str

    async def place_order(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> BrokerOrder: ...

    async def get_orders(self, status: str = "open") -> list[BrokerOrder]: ...

    async def cancel_order(self, broker_order_id: str) -> bool: ...

    async def get_positions(self) -> list[BrokerPosition]: ...

    async def get_account(self) -> BrokerAccount: ...


# ---------------------------------------------------------------------------
# Alpaca Paper Trading Adapter
# ---------------------------------------------------------------------------

ALPACA_PAPER_BASE = "https://paper-api.alpaca.markets/v2"


class AlpacaPaperAdapter:
    """Full Alpaca paper trading adapter.

    Requires ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables.
    Docs: https://alpaca.markets/docs/api-references/trading-api/
    """

    name = "Alpaca"
    status = "paper_ready"

    def __init__(self, api_key: str, secret_key: str) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self._base = ALPACA_PAPER_BASE

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    async def place_order(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> BrokerOrder:
        payload: dict[str, object] = {
            "symbol": symbol.upper(),
            "qty": str(quantity),
            "side": side.lower(),
            "type": _alpaca_order_type(order_type, stop_price),
            "time_in_force": "day",
        }
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if stop_price is not None:
            payload["stop_price"] = str(stop_price)

        data = await _alpaca_post(self._base, "/orders", self._headers(), payload)
        return BrokerOrder(
            broker_order_id=str(data.get("id", "")),
            symbol=str(data.get("symbol", symbol)),
            side=str(data.get("side", side)),
            quantity=float(data.get("qty", quantity)),
            order_type=str(data.get("type", order_type)),
            status=_alpaca_status(str(data.get("status", "submitted"))),
            submitted_at=str(data.get("submitted_at", "")),
        )

    async def get_orders(self, status: str = "open") -> list[BrokerOrder]:
        params = {"status": status, "limit": "50"}
        data = await _alpaca_get(self._base, "/orders", self._headers(), params)
        orders: list[BrokerOrder] = []
        for item in data if isinstance(data, list) else []:
            orders.append(
                BrokerOrder(
                    broker_order_id=str(item.get("id", "")),
                    symbol=str(item.get("symbol", "")),
                    side=str(item.get("side", "")),
                    quantity=float(item.get("qty", 0)),
                    order_type=str(item.get("type", "")),
                    status=_alpaca_status(str(item.get("status", ""))),
                    filled_qty=float(item.get("filled_qty", 0)),
                    filled_price=_optional_float(item.get("filled_avg_price")),
                    submitted_at=str(item.get("submitted_at", "")),
                )
            )
        return orders

    async def cancel_order(self, broker_order_id: str) -> bool:
        await _alpaca_delete(self._base, f"/orders/{broker_order_id}", self._headers())
        return True

    async def get_positions(self) -> list[BrokerPosition]:
        data = await _alpaca_get(self._base, "/positions", self._headers())
        positions: list[BrokerPosition] = []
        for item in data if isinstance(data, list) else []:
            positions.append(
                BrokerPosition(
                    symbol=str(item.get("symbol", "")),
                    quantity=float(item.get("qty", 0)),
                    avg_entry_price=float(item.get("avg_entry_price", 0)),
                    market_value=float(item.get("market_value", 0)),
                    unrealized_pnl=float(item.get("unrealized_pl", 0)),
                )
            )
        return positions

    async def get_account(self) -> BrokerAccount:
        data = await _alpaca_get(self._base, "/account", self._headers())
        return BrokerAccount(
            equity=float(data.get("equity", 0)),
            cash=float(data.get("cash", 0)),
            buying_power=float(data.get("buying_power", 0)),
        )


# ---------------------------------------------------------------------------
# Tradier Sandbox Adapter
# ---------------------------------------------------------------------------

TRADIER_SANDBOX_BASE = "https://sandbox.tradier.com/v1"


class TradierSandboxAdapter:
    """Full Tradier sandbox trading adapter.

    Requires TRADIER_TOKEN environment variable.
    Docs: https://documentation.tradier.com/brokerage-api
    """

    name = "Tradier"
    status = "sandbox_ready"

    def __init__(self, token: str) -> None:
        self.token = token
        self._base = TRADIER_SANDBOX_BASE

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    async def place_order(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> BrokerOrder:
        payload: dict[str, str] = {
            "symbol": symbol.upper(),
            "side": side.lower(),
            "quantity": str(int(quantity)),
            "type": _tradier_order_type(order_type, stop_price),
            "duration": "day",
        }
        if limit_price is not None:
            payload["price"] = str(limit_price)
        if stop_price is not None:
            payload["stop"] = str(stop_price)

        data = await _tradier_post(self._base, "/accounts/sandbox/orders", self._headers(), payload)
        order_data = data.get("order", data) if isinstance(data, dict) else data
        order_id = str(order_data.get("id", "")) if isinstance(order_data, dict) else ""
        return BrokerOrder(
            broker_order_id=order_id,
            symbol=symbol.upper(),
            side=side.lower(),
            quantity=quantity,
            order_type=order_type,
            status="submitted",
        )

    async def get_orders(self, status: str = "open") -> list[BrokerOrder]:
        data = await _tradier_get(self._base, "/accounts/sandbox/orders", self._headers())
        orders_data = data.get("orders", data) if isinstance(data, dict) else data
        if isinstance(orders_data, dict) and "order" in orders_data:
            orders_data = orders_data["order"]
        if not isinstance(orders_data, list):
            orders_data = [orders_data] if isinstance(orders_data, dict) else []
        orders: list[BrokerOrder] = []
        for item in orders_data:
            if not isinstance(item, dict):
                continue
            orders.append(
                BrokerOrder(
                    broker_order_id=str(item.get("id", "")),
                    symbol=str(item.get("symbol", "")),
                    side=str(item.get("side", "")),
                    quantity=float(item.get("quantity", 0)),
                    order_type=str(item.get("type", "")),
                    status=_tradier_status(str(item.get("status", ""))),
                )
            )
        return orders

    async def cancel_order(self, broker_order_id: str) -> bool:
        await _tradier_delete(self._base, f"/accounts/sandbox/orders/{broker_order_id}", self._headers())
        return True

    async def get_positions(self) -> list[BrokerPosition]:
        data = await _tradier_get(self._base, "/accounts/sandbox/positions", self._headers())
        positions_data = data.get("positions", data) if isinstance(data, dict) else data
        if isinstance(positions_data, dict) and "position" in positions_data:
            positions_data = positions_data["position"]
        if not isinstance(positions_data, list):
            positions_data = [positions_data] if isinstance(positions_data, dict) else []
        positions: list[BrokerPosition] = []
        for item in positions_data:
            if not isinstance(item, dict):
                continue
            positions.append(
                BrokerPosition(
                    symbol=str(item.get("symbol", "")),
                    quantity=float(item.get("quantity", 0)),
                    avg_entry_price=float(item.get("cost_basis", 0)) / max(float(item.get("quantity", 1)), 1),
                )
            )
        return positions

    async def get_account(self) -> BrokerAccount:
        data = await _tradier_get(self._base, "/accounts/sandbox/balances", self._headers())
        balances = data.get("balances", data) if isinstance(data, dict) else data
        if not isinstance(balances, dict):
            balances = {}
        return BrokerAccount(
            equity=float(balances.get("total_equity", 0)),
            cash=float(balances.get("cash", 0)),
            buying_power=float(balances.get("margin", {}).get("buying_power", 0) if isinstance(balances.get("margin"), dict) else balances.get("buying_power", 0)),
        )


# ---------------------------------------------------------------------------
# IBKR Paper Adapter (scaffold)
# ---------------------------------------------------------------------------


class IBKRPaperAdapter:
    """IBKR TWS/Gateway paper trading adapter.

    Requires IB Gateway running locally on port 4002 (paper) or 7497 (TWS paper).
    Full implementation requires ib_insync or ibapi library integration.
    Status: gateway_required — interface defined, methods raise setup instructions.
    """

    name = "IBKR"
    status = "gateway_required"

    def __init__(self, host: str = "127.0.0.1", port: int = 4002, client_id: int = 1) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id

    async def place_order(
        self,
        side: str,
        symbol: str,
        quantity: float,
        order_type: str,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> BrokerOrder:
        raise ProviderError(
            "IBKR adapter requires IB Gateway running locally.",
            f"Start IB Gateway on {self.host}:{self.port} (paper mode). Then configure client_id={self.client_id}.",
        )

    async def get_orders(self, status: str = "open") -> list[BrokerOrder]:
        raise ProviderError("IBKR adapter requires IB Gateway running locally.", self._setup_hint())

    async def cancel_order(self, broker_order_id: str) -> bool:
        raise ProviderError("IBKR adapter requires IB Gateway running locally.", self._setup_hint())

    async def get_positions(self) -> list[BrokerPosition]:
        raise ProviderError("IBKR adapter requires IB Gateway running locally.", self._setup_hint())

    async def get_account(self) -> BrokerAccount:
        raise ProviderError("IBKR adapter requires IB Gateway running locally.", self._setup_hint())

    def _setup_hint(self) -> str:
        return f"Start IB Gateway on {self.host}:{self.port} (paper mode). Install ib_insync: pip install ib_insync."


# ---------------------------------------------------------------------------
# Broker Adapter Registry
# ---------------------------------------------------------------------------


class BrokerAdapterRegistry:
    """Registry for broker sandbox adapters. Adapters are created on demand."""

    def __init__(self) -> None:
        self._active: str = ""
        self._adapters: dict[str, object] = {}

    @property
    def active_name(self) -> str:
        return self._active

    def activate(self, name: str, adapter: object) -> None:
        self._active = name
        self._adapters[name.lower()] = adapter

    def deactivate(self) -> None:
        self._active = ""

    def get(self, name: str) -> object | None:
        return self._adapters.get(name.lower())

    def get_active(self) -> object | None:
        if not self._active:
            return None
        return self._adapters.get(self._active.lower())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alpaca_order_type(order_type: str, stop_price: float | None) -> str:
    if order_type == "stop_limit" or (order_type == "limit" and stop_price is not None):
        return "stop_limit"
    if order_type == "limit":
        return "limit"
    return "market"


def _tradier_order_type(order_type: str, stop_price: float | None) -> str:
    if order_type == "stop_limit":
        return "stoplimit"
    if order_type == "limit":
        return "limit"
    return "market"


def _alpaca_status(status: str) -> str:
    mapping = {
        "new": "submitted",
        "accepted": "submitted",
        "pending_new": "submitted",
        "accepted_for_bidding": "submitted",
        "filled": "filled",
        "partially_filled": "partial",
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
        "pending_cancel": "pending_cancel",
        "pending_replace": "pending_replace",
        "stopped": "stopped",
        "suspended": "suspended",
    }
    return mapping.get(status.lower(), status)


def _tradier_status(status: str) -> str:
    mapping = {
        "open": "submitted",
        "pending": "submitted",
        "filled": "filled",
        "partial_fill": "partial",
        "canceled": "cancelled",
        "cancelled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
        "queued": "queued",
    }
    return mapping.get(status.lower(), status)


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


async def _alpaca_get(base: str, path: str, headers: dict[str, str], params: dict[str, str] | None = None) -> object:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{base}{path}", headers=headers, params=params)
        if response.status_code == 401:
            raise ProviderError("Alpaca authentication failed. Check ALPACA_API_KEY and ALPACA_SECRET_KEY.")
        if response.status_code == 403:
            raise ProviderError("Alpaca access denied. Verify your account has paper trading enabled.")
        response.raise_for_status()
        return response.json()


async def _alpaca_post(base: str, path: str, headers: dict[str, str], payload: dict[str, object]) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{base}{path}", headers=headers, json=payload)
        if response.status_code == 401:
            raise ProviderError("Alpaca authentication failed. Check ALPACA_API_KEY and ALPACA_SECRET_KEY.")
        if response.status_code == 422:
            detail = response.text[:200]
            raise ProviderError(f"Alpaca order rejected: {detail}")
        response.raise_for_status()
        return response.json()


async def _alpaca_delete(base: str, path: str, headers: dict[str, str]) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(f"{base}{path}", headers=headers)
        if response.status_code == 401:
            raise ProviderError("Alpaca authentication failed.")
        response.raise_for_status()


async def _tradier_get(base: str, path: str, headers: dict[str, str]) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{base}{path}", headers=headers)
        if response.status_code == 401:
            raise ProviderError("Tradier authentication failed. Check TRADIER_TOKEN.")
        response.raise_for_status()
        return response.json()


async def _tradier_post(base: str, path: str, headers: dict[str, str], payload: dict[str, str]) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{base}{path}", headers=headers, data=payload)
        if response.status_code == 401:
            raise ProviderError("Tradier authentication failed. Check TRADIER_TOKEN.")
        if response.status_code == 400:
            detail = response.text[:200]
            raise ProviderError(f"Tradier order rejected: {detail}")
        response.raise_for_status()
        return response.json()


async def _tradier_delete(base: str, path: str, headers: dict[str, str]) -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.delete(f"{base}{path}", headers=headers)
        if response.status_code == 401:
            raise ProviderError("Tradier authentication failed.")
        response.raise_for_status()
