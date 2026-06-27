"""Alpaca broker integration for live and paper trading."""

from __future__ import annotations

import json
import os
from datetime import datetime

import httpx

from fincli.app.brokers.base import (
    BaseBroker,
    BrokerAccount,
    BrokerConnectionStatus,
    BrokerOrder,
    BrokerPosition,
)
from fincli.app.utils.errors import ProviderError


# Alpaca API endpoints
ALPACA_PAPER_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_URL = "https://api.alpaca.markets"


def _parse_order(data: dict, broker: str = "alpaca") -> BrokerOrder:
    """Parse Alpaca order response into BrokerOrder."""
    side = data.get("side", "buy")
    order_type = data.get("type", "market")
    status_map = {
        "new": "submitted",
        "accepted": "submitted",
        "pending_new": "pending",
        "accepted_for_bidding": "submitted",
        "stopped": "submitted",
        "pending_replace": "pending",
        "replaced": "submitted",
        "pending_cancel": "pending",
        "calculated": "submitted",
        "filled": "filled",
        "partially_filled": "partially_filled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
        "suspended": "submitted",
    }
    raw_status = data.get("status", "pending")
    status = status_map.get(raw_status, raw_status)

    created_str = data.get("created_at", "")
    updated_str = data.get("updated_at", created_str)
    try:
        created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.now()
    except (ValueError, AttributeError):
        created_at = datetime.now()
    try:
        updated_at = datetime.fromisoformat(updated_str.replace("Z", "+00:00")) if updated_str else datetime.now()
    except (ValueError, AttributeError):
        updated_at = datetime.now()

    filled_qty = float(data.get("filled_qty", 0) or 0)
    filled_avg = data.get("filled_avg_price")
    filled_price = float(filled_avg) if filled_avg else None

    return BrokerOrder(
        broker_order_id=data.get("id", ""),
        symbol=data.get("symbol", ""),
        side=side,
        order_type=order_type,
        quantity=float(data.get("qty", 0) or 0),
        price=float(data["limit_price"]) if data.get("limit_price") else None,
        stop_price=float(data["stop_price"]) if data.get("stop_price") else None,
        status=status,
        filled_quantity=filled_qty,
        filled_price=filled_price,
        time_in_force=data.get("time_in_force", "day"),
        created_at=created_at,
        updated_at=updated_at,
        broker=broker,
    )


class AlpacaBroker(BaseBroker):
    """Alpaca broker integration supporting paper and live trading."""

    name = "alpaca"
    supported_modes = ("paper", "live")

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self._base_url = base_url or os.getenv("ALPACA_BASE_URL", ALPACA_PAPER_URL)
        self._client: httpx.AsyncClient | None = None
        self._connected = False
        self._mode = "paper"

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=30.0,
            )
        return self._client

    async def connect(self, mode: str = "paper") -> BrokerConnectionStatus:
        """Connect to Alpaca. Verifies credentials by fetching account."""
        if mode not in self.supported_modes:
            return BrokerConnectionStatus(
                connected=False,
                broker=self.name,
                mode=mode,
                account_id=None,
                message=f"Mode tidak didukung: {mode}. Gunakan 'paper' atau 'live'.",
            )

        if not self.api_key or not self.secret_key:
            return BrokerConnectionStatus(
                connected=False,
                broker=self.name,
                mode=mode,
                account_id=None,
                message="API key atau secret key belum diatur. Set ALPACA_API_KEY dan ALPACA_SECRET_KEY.",
            )

        # Set correct base URL
        if mode == "paper":
            self._base_url = ALPACA_PAPER_URL
        else:
            self._base_url = ALPACA_LIVE_URL

        # Reset client with new base URL
        if self._client:
            await self._client.aclose()
            self._client = None

        self._mode = mode

        try:
            account = await self.get_account()
            self._connected = True
            return BrokerConnectionStatus(
                connected=True,
                broker=self.name,
                mode=mode,
                account_id=account.account_id,
                message=f"Terhubung ke Alpaca ({mode}). Account: {account.account_id}, Cash: ${account.cash:,.2f}",
            )
        except Exception as exc:
            self._connected = False
            return BrokerConnectionStatus(
                connected=False,
                broker=self.name,
                mode=mode,
                account_id=None,
                message=f"Gagal terhubung ke Alpaca: {exc}",
            )

    async def disconnect(self) -> None:
        """Disconnect from Alpaca."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connected = False

    async def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected

    async def get_account(self) -> BrokerAccount:
        """Get Alpaca account info."""
        client = self._get_client()
        try:
            response = await client.get("/v2/account")
            response.raise_for_status()
            data = response.json()
            return BrokerAccount(
                account_id=data.get("id", ""),
                cash=float(data.get("cash", 0)),
                portfolio_value=float(data.get("portfolio_value", 0)),
                buying_power=float(data.get("buying_power", 0)),
                equity=float(data.get("equity", 0)),
                currency=data.get("currency", "USD"),
                broker=self.name,
            )
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gagal mengambil account info: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil account info: {exc}") from exc

    async def get_positions(self) -> list[BrokerPosition]:
        """Get all open positions."""
        client = self._get_client()
        try:
            response = await client.get("/v2/positions")
            response.raise_for_status()
            positions = []
            for data in response.json():
                positions.append(BrokerPosition(
                    symbol=data.get("symbol", ""),
                    quantity=float(data.get("qty", 0)),
                    avg_entry_price=float(data.get("avg_entry_price", 0)),
                    current_price=float(data.get("current_price", 0)),
                    market_value=float(data.get("market_value", 0)),
                    unrealized_pnl=float(data.get("unrealized_pl", 0)),
                    side=data.get("side", "long"),
                ))
            return positions
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gagal mengambil posisi: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil posisi: {exc}") from exc

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
        """Place an order via Alpaca API."""
        client = self._get_client()

        # Map order type to Alpaca type
        type_map = {
            "market": "market",
            "limit": "limit",
            "stop_limit": "stop_limit",
        }
        alpaca_type = type_map.get(order_type, "market")

        payload: dict = {
            "symbol": symbol.upper(),
            "qty": str(quantity),
            "side": side,
            "type": alpaca_type,
            "time_in_force": time_in_force.upper(),
        }

        if price is not None and order_type in ("limit", "stop_limit"):
            payload["limit_price"] = str(price)

        if stop_price is not None and order_type == "stop_limit":
            payload["stop_price"] = str(stop_price)

        try:
            response = await client.post("/v2/orders", json=payload)
            response.raise_for_status()
            return _parse_order(response.json(), self.name)
        except httpx.HTTPStatusError as exc:
            error_data = {}
            try:
                error_data = exc.response.json()
            except (json.JSONDecodeError, ValueError):
                pass
            msg = error_data.get("message", f"HTTP {exc.response.status_code}")
            raise ProviderError(f"Gagal place order: {msg}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal place order: {exc}") from exc

    async def cancel_order(self, broker_order_id: str) -> BrokerOrder:
        """Cancel a pending order."""
        client = self._get_client()
        try:
            response = await client.delete(f"/v2/orders/{broker_order_id}")
            response.raise_for_status()
            return _parse_order(response.json(), self.name)
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gagal cancel order: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal cancel order: {exc}") from exc

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        """Get order status."""
        client = self._get_client()
        try:
            response = await client.get(f"/v2/orders/{broker_order_id}")
            response.raise_for_status()
            return _parse_order(response.json(), self.name)
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gagal mengambil order: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil order: {exc}") from exc

    async def list_orders(self, status: str | None = None, limit: int = 50) -> list[BrokerOrder]:
        """List orders, optionally filtered by status."""
        client = self._get_client()
        params: dict = {"limit": str(limit)}
        if status:
            # Map our status to Alpaca status
            status_map = {
                "pending": "open",
                "submitted": "open",
                "filled": "closed",
                "cancelled": "closed",
            }
            alpaca_status = status_map.get(status, status)
            params["status"] = alpaca_status

        try:
            response = await client.get("/v2/orders", params=params)
            response.raise_for_status()
            return [_parse_order(order, self.name) for order in response.json()]
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gagal mengambil orders: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil orders: {exc}") from exc

    async def get_quote(self, symbol: str) -> float:
        """Get current price for a symbol."""
        client = self._get_client()
        try:
            response = await client.get(f"/v2/stocks/{symbol.upper()}/quotes/latest")
            response.raise_for_status()
            data = response.json()
            quote = data.get("quote", {})
            return float(quote.get("ap", 0) or quote.get("bp", 0) or 0)
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Gagal mengambil quote: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise ProviderError(f"Gagal mengambil quote: {exc}") from exc
