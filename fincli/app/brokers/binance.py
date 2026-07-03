"""Binance broker integration for crypto trading."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

from fincli.app.brokers.base import (
    BaseBroker,
    BrokerAccount,
    BrokerConnectionStatus,
    BrokerOrder,
    BrokerPosition,
)
from fincli.app.utils.errors import ProviderError

logger = logging.getLogger(__name__)

# Binance API endpoints
BINANCE_BASE_URL = "https://api.binance.com"
BINANCE_TESTNET_URL = "https://testnet.binance.vision"

# Status mapping from Binance to our standard
STATUS_MAP = {
    "NEW": "submitted",
    "PARTIALLY_FILLED": "partially_filled",
    "FILLED": "filled",
    "CANCELED": "cancelled",
    "PENDING_CANCEL": "pending",
    "REJECTED": "rejected",
    "EXPIRED": "expired",
}


def _parse_binance_order(data: dict, symbol: str, broker: str = "binance") -> BrokerOrder:
    """Parse Binance order response into BrokerOrder."""
    side = data.get("side", "BUY").lower()
    order_type = data.get("type", "MARKET").lower()
    status = STATUS_MAP.get(data.get("status", "NEW"), "submitted")

    created_ts = data.get("time", 0)
    updated_ts = data.get("updateTime", created_ts)
    created_at = datetime.fromtimestamp(created_ts / 1000, tz=UTC) if created_ts else datetime.now(UTC)
    updated_at = datetime.fromtimestamp(updated_ts / 1000, tz=UTC) if updated_ts else created_at

    return BrokerOrder(
        broker_order_id=str(data.get("orderId", "")),
        symbol=symbol.upper(),
        side=side,
        order_type=order_type,
        quantity=float(data.get("origQty", 0)),
        price=float(data.get("price", 0)) if data.get("price") else None,
        stop_price=float(data.get("stopPrice", 0)) if data.get("stopPrice") else None,
        status=status,
        filled_quantity=float(data.get("executedQty", 0)),
        filled_price=_calculate_avg_price(data),
        time_in_force=data.get("timeInForce", "GTC").lower(),
        created_at=created_at,
        updated_at=updated_at,
        broker=broker,
    )


def _calculate_avg_price(data: dict) -> float | None:
    """Calculate average fill price from order data."""
    executed_qty = float(data.get("executedQty", 0))
    if executed_qty <= 0:
        return None
    # Binance doesn't directly provide avg price, use cummulativeQuoteQty
    cum_quote = float(data.get("cummulativeQuoteQty", 0))
    if cum_quote > 0:
        return cum_quote / executed_qty
    return None


class BinanceBroker(BaseBroker):
    """Binance exchange integration for crypto trading."""

    name = "binance"
    supported_modes = ("live", "testnet")

    def __init__(self) -> None:
        self._connected = False
        self._mode = "testnet"
        self._api_key = ""
        self._api_secret = ""
        self._base_url = BINANCE_TESTNET_URL
        self._client: httpx.AsyncClient | None = None

    def _get_signature(self, params: dict) -> str:
        """Create HMAC SHA256 signature for Binance API."""
        query_string = urlencode(params)
        return hmac.new(
            self._api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with API key."""
        return {"X-MBX-APIKEY": self._api_key}

    async def _signed_request(self, method: str, endpoint: str, params: dict | None = None) -> dict:
        """Make a signed API request."""
        if not self._client:
            raise ProviderError("Not connected to Binance")

        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = self._get_signature(params)

        url = f"{self._base_url}{endpoint}"
        resp = await self._client.request(method, url, params=params, headers=self._get_headers(), timeout=10)

        if resp.status_code != 200:
            try:
                error = resp.json().get("msg", resp.text)
            except (ValueError, AttributeError):
                error = resp.text[:200] if resp.text else f"HTTP {resp.status_code}"
            raise ProviderError(f"Binance API error: {error}")

        return resp.json()

    async def _public_request(self, method: str, endpoint: str, params: dict | None = None) -> dict:
        """Make a public API request (no signature)."""
        if not self._client:
            raise ProviderError("Not connected to Binance")

        url = f"{self._base_url}{endpoint}"
        resp = await self._client.request(method, url, params=params, timeout=10)

        if resp.status_code != 200:
            try:
                error = resp.json().get("msg", resp.text)
            except (ValueError, AttributeError):
                error = resp.text[:200] if resp.text else f"HTTP {resp.status_code}"
            raise ProviderError(f"Binance API error: {error}")

        return resp.json()

    async def connect(self, mode: str = "testnet") -> BrokerConnectionStatus:
        """Connect to Binance."""
        self._mode = mode
        self._api_key = os.getenv("BINANCE_API_KEY", "")
        self._api_secret = os.getenv("BINANCE_API_SECRET", "")

        if not self._api_key or not self._api_secret:
            return BrokerConnectionStatus(
                connected=False,
                broker="binance",
                mode=mode,
                account_id=None,
                message="BINANCE_API_KEY and BINANCE_API_SECRET required. Set in ~/.fincli/secrets.env",
            )

        self._base_url = BINANCE_TESTNET_URL if mode == "testnet" else BINANCE_BASE_URL
        self._client = httpx.AsyncClient()

        try:
            # Test connection by getting account info
            account = await self.get_account()
            self._connected = True
            return BrokerConnectionStatus(
                connected=True,
                broker="binance",
                mode=mode,
                account_id=account.account_id,
                message=f"Connected to Binance {mode}. Balance: {account.cash:.2f} USDT",
            )
        except Exception as exc:
            self._client = None
            return BrokerConnectionStatus(
                connected=False,
                broker="binance",
                mode=mode,
                account_id=None,
                message=f"Connection failed: {exc}",
            )

    async def disconnect(self) -> None:
        """Disconnect from Binance."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    async def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected and self._client is not None

    async def get_account(self) -> BrokerAccount:
        """Get Binance account info."""
        data = await self._signed_request("GET", "/api/v3/account")

        # Find USDT balance
        balances = data.get("balances", [])
        usdt_balance = next((b for b in balances if b["asset"] == "USDT"), None)
        cash = float(usdt_balance["free"]) if usdt_balance else 0.0

        # Calculate total portfolio value
        total_value = cash
        for balance in balances:
            if float(balance["free"]) > 0 or float(balance["locked"]) > 0:
                if balance["asset"] != "USDT":
                    # Approximate value using current price
                    try:
                        ticker = await self._public_request("GET", "/api/v3/ticker/price", {"symbol": f"{balance['asset']}USDT"})
                        price = float(ticker.get("price", 0))
                        total_value += (float(balance["free"]) + float(balance["locked"])) * price
                    except Exception as exc:
                        logger.warning("Failed to fetch %s price for account: %s", balance["asset"], exc)

        return BrokerAccount(
            account_id="binance",
            cash=cash,
            portfolio_value=total_value,
            buying_power=cash,  # Simplified
            equity=total_value,
            currency="USDT",
            broker="binance",
        )

    async def get_positions(self) -> list[BrokerPosition]:
        """Get all open positions."""
        data = await self._signed_request("GET", "/api/v3/account")
        positions: list[BrokerPosition] = []

        for balance in data.get("balances", []):
            free = float(balance["free"])
            locked = float(balance["locked"])
            total = free + locked

            if total <= 0 or balance["asset"] == "USDT":
                continue

            # Get current price
            try:
                ticker = await self._public_request("GET", "/api/v3/ticker/price", {"symbol": f"{balance['asset']}USDT"})
                current_price = float(ticker.get("price", 0))
            except Exception as exc:
                logger.warning("Failed to fetch %s price for position: %s", balance["asset"], exc)
                current_price = 0

            positions.append(BrokerPosition(
                symbol=f"{balance['asset']}-USD",
                quantity=total,
                avg_entry_price=0,  # Binance doesn't provide this directly
                current_price=current_price,
                market_value=total * current_price,
                unrealized_pnl=0,  # Requires entry price tracking
                side="long",
            ))

        return positions

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "gtc",
    ) -> BrokerOrder:
        """Place an order on Binance."""
        # Normalize symbol: BTC-USD -> BTCUSDT
        base = symbol.upper().replace("-USD", "").replace("USDT", "")
        binance_symbol = f"{base}USDT"

        params = {
            "symbol": binance_symbol,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": f"{quantity:.8f}",
        }

        if order_type == "limit" and price:
            params["price"] = f"{price:.2f}"
            params["timeInForce"] = time_in_force.upper()

        if stop_price:
            params["stopPrice"] = f"{stop_price:.2f}"

        data = await self._signed_request("POST", "/api/v3/order", params)
        return _parse_binance_order(data, symbol)

    async def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        """Cancel a pending order."""
        # Binance requires symbol to cancel - look up from recent orders
        orders = await self.list_orders(status="open", limit=100)
        target = next((o for o in orders if o.broker_order_id == broker_order_id), None)
        if not target:
            # Try all orders
            orders = await self.list_orders(status="all", limit=100)
            target = next((o for o in orders if o.broker_order_id == broker_order_id), None)
        if not target:
            raise ProviderError(f"Order {broker_order_id} not found. Cannot determine symbol for cancel.")

        # Normalize symbol for Binance API
        base = target.symbol.upper().replace("-USD", "").replace("USDT", "")
        binance_symbol = f"{base}USDT"

        params = {
            "symbol": binance_symbol,
            "orderId": int(broker_order_id),
        }
        data = await self._signed_request("DELETE", "/api/v3/order", params)
        return _parse_binance_order(data, target.symbol)

    async def list_orders(self, status: str = "all", limit: int = 50) -> list[BrokerOrder]:
        """List recent orders."""
        data = await self._signed_request("GET", "/api/v3/allOrders", {"limit": limit})
        orders: list[BrokerOrder] = []

        for order in data:
            order_status = STATUS_MAP.get(order.get("status", ""), "submitted")
            if status != "all" and order_status != status:
                continue
            orders.append(_parse_binance_order(order, order.get("symbol", "")))

        return orders

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        """Get order status by ID."""
        # Look up from recent orders to get the symbol
        orders = await self.list_orders(status="all", limit=500)
        target = next((o for o in orders if o.broker_order_id == broker_order_id), None)
        if not target:
            raise ProviderError(f"Order {broker_order_id} not found.")

        # Get fresh status from Binance
        base = target.symbol.upper().replace("-USD", "").replace("USDT", "")
        binance_symbol = f"{base}USDT"
        params = {
            "symbol": binance_symbol,
            "orderId": int(broker_order_id),
        }
        data = await self._signed_request("GET", "/api/v3/order", params)
        return _parse_binance_order(data, target.symbol)

    async def get_quote(self, symbol: str) -> float:
        """Get current price for a symbol."""
        base = symbol.upper().replace("-USD", "").replace("USDT", "")
        binance_symbol = f"{base}USDT"

        data = await self._public_request("GET", "/api/v3/ticker/price", {"symbol": binance_symbol})
        return float(data.get("price", 0))
