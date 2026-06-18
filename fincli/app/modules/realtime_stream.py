"""Realtime streaming adapters for crypto and equity (Phase 0.7.0).

Provides WebSocket adapters for Kraken and HyperLiquid, plus a polling-based
equity stream that uses the existing market provider chain.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from fincli.app.utils.errors import ProviderError


# ---------------------------------------------------------------------------
# Stream Event
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StreamEvent:
    """Normalized event from any realtime stream."""

    event_type: str  # ticker, trade, ohlc, l2_book, mid, error, connected, disconnected
    symbol: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""


# Type alias for event callbacks
StreamCallback = Callable[[StreamEvent], Awaitable[None] | None]


# ---------------------------------------------------------------------------
# Kraken WebSocket Adapter
# ---------------------------------------------------------------------------

KRAKEN_WS_PUBLIC = "wss://ws.kraken.com"
KRAKEN_WS_PRIVATE = "wss://ws-auth.kraken.com"


class KrakenWebSocketAdapter:
    """Kraken WebSocket adapter for crypto realtime data.

    Public channels: ticker, trade, ohlc, spread, book.
    Private channels: ownTrades, openOrders (requires API key).
    Docs: https://docs.kraken.com/websockets/
    """

    name = "Kraken WebSocket"
    status = "configurable"

    def __init__(self, api_key: str = "", api_secret: str = "") -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self._callbacks: list[StreamCallback] = []
        self._connected = False
        self._subscriptions: list[dict[str, Any]] = []
        self._ws: Any = None
        self._task: asyncio.Task[None] | None = None

    def on_event(self, callback: StreamCallback) -> None:
        self._callbacks.append(callback)

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError:
            raise ProviderError(
                "websockets library not installed.",
                "Install with: pip install websockets",
            )
        self._ws = await websockets.connect(KRAKEN_WS_PUBLIC)
        self._connected = True
        await self._emit(StreamEvent("connected", "", {"server": "kraken"}, source="kraken"))

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self._connected = False
        await self._emit(StreamEvent("disconnected", "", {"server": "kraken"}, source="kraken"))

    async def subscribe_ticker(self, symbols: list[str]) -> None:
        pairs = [_kraken_pair(s) for s in symbols]
        msg = {"event": "subscribe", "pair": [{"name": p} for p in pairs], "subscription": {"name": "ticker"}}
        await self._send(msg)
        self._subscriptions.append({"channel": "ticker", "symbols": symbols})

    async def subscribe_trades(self, symbols: list[str]) -> None:
        pairs = [_kraken_pair(s) for s in symbols]
        msg = {"event": "subscribe", "pair": [{"name": p} for p in pairs], "subscription": {"name": "trade"}}
        await self._send(msg)
        self._subscriptions.append({"channel": "trade", "symbols": symbols})

    async def subscribe_ohlc(self, symbols: list[str], interval: int = 1) -> None:
        pairs = [_kraken_pair(s) for s in symbols]
        msg = {
            "event": "subscribe",
            "pair": [{"name": p} for p in pairs],
            "subscription": {"name": "ohlc", "interval": interval},
        }
        await self._send(msg)
        self._subscriptions.append({"channel": "ohlc", "symbols": symbols, "interval": interval})

    async def listen(self) -> None:
        if self._ws is None:
            raise ProviderError("Not connected. Call connect() first.")
        async for message in self._ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("event") == "heartbeat":
                continue
            if isinstance(data, list) and len(data) >= 3:
                channel = data[-2] if isinstance(data[-2], str) else "unknown"
                pair = data[-1] if isinstance(data[-1], str) else ""
                event_type = _kraken_channel_to_event_type(channel)
                await self._emit(StreamEvent(event_type, pair, {"raw": data}, source="kraken"))

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscriptions(self) -> list[dict[str, Any]]:
        return list(self._subscriptions)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise ProviderError("Not connected.")
        await self._ws.send(json.dumps(payload))

    async def _emit(self, event: StreamEvent) -> None:
        for callback in self._callbacks:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 - callbacks should not break the stream
                pass


# ---------------------------------------------------------------------------
# HyperLiquid WebSocket Adapter
# ---------------------------------------------------------------------------

HYPERLIQUID_WS = "wss://api.hyperliquid.xyz/ws"


class HyperLiquidWebSocketAdapter:
    """HyperLiquid WebSocket adapter for crypto and perpetuals.

    Channels: l2Book, trades, allMids, userEvents.
    Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket
    """

    name = "HyperLiquid WebSocket"
    status = "configurable"

    def __init__(self) -> None:
        self._callbacks: list[StreamCallback] = []
        self._connected = False
        self._subscriptions: list[dict[str, Any]] = []
        self._ws: Any = None

    def on_event(self, callback: StreamCallback) -> None:
        self._callbacks.append(callback)

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError:
            raise ProviderError(
                "websockets library not installed.",
                "Install with: pip install websockets",
            )
        self._ws = await websockets.connect(HYPERLIQUID_WS)
        self._connected = True
        await self._emit(StreamEvent("connected", "", {"server": "hyperliquid"}, source="hyperliquid"))

    async def disconnect(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self._connected = False
        await self._emit(StreamEvent("disconnected", "", {"server": "hyperliquid"}, source="hyperliquid"))

    async def subscribe_l2_book(self, coins: list[str]) -> None:
        for coin in coins:
            msg = {"method": "subscribe", "subscription": {"type": "l2Book", "coin": coin.upper()}}
            await self._send(msg)
        self._subscriptions.append({"channel": "l2Book", "coins": coins})

    async def subscribe_trades(self, coins: list[str]) -> None:
        for coin in coins:
            msg = {"method": "subscribe", "subscription": {"type": "trades", "coin": coin.upper()}}
            await self._send(msg)
        self._subscriptions.append({"channel": "trades", "coins": coins})

    async def subscribe_all_mids(self) -> None:
        msg = {"method": "subscribe", "subscription": {"type": "allMids"}}
        await self._send(msg)
        self._subscriptions.append({"channel": "allMids"})

    async def listen(self) -> None:
        if self._ws is None:
            raise ProviderError("Not connected. Call connect() first.")
        async for message in self._ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                channel = data.get("channel", "")
                event_type = _hyperliquid_channel_to_event_type(channel)
                coin = ""
                if isinstance(data.get("data"), dict):
                    coin = data["data"].get("coin", "")
                await self._emit(StreamEvent(event_type, coin, data, source="hyperliquid"))

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscriptions(self) -> list[dict[str, Any]]:
        return list(self._subscriptions)

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None:
            raise ProviderError("Not connected.")
        await self._ws.send(json.dumps(payload))

    async def _emit(self, event: StreamEvent) -> None:
        for callback in self._callbacks:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Equity Streaming Adapter (polling-based)
# ---------------------------------------------------------------------------


class EquityStreamingAdapter:
    """Polling-based equity quote stream using configured market providers.

    Polls MarketDataService.quote() at a configurable interval.
    Status: provider_dependent — realtime depends on provider entitlement.
    """

    name = "Equity Quote Feed"
    status = "provider_dependent"

    def __init__(self, market_service: Any, interval_seconds: float = 5.0) -> None:
        self._market_service = market_service
        self._interval = max(1.0, interval_seconds)
        self._callbacks: list[StreamCallback] = []
        self._connected = False
        self._symbols: list[str] = []
        self._task: asyncio.Task[None] | None = None

    def on_event(self, callback: StreamCallback) -> None:
        self._callbacks.append(callback)

    async def subscribe_quote(self, symbols: list[str]) -> None:
        self._symbols = [s.upper() for s in symbols]

    async def connect(self) -> None:
        self._connected = True
        self._task = asyncio.create_task(self._poll_loop())
        await self._emit(StreamEvent("connected", "", {"server": "equity_polling", "symbols": self._symbols}, source="equity"))

    async def disconnect(self) -> None:
        self._connected = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await self._emit(StreamEvent("disconnected", "", {"server": "equity_polling"}, source="equity"))

    async def listen(self) -> None:
        if self._task is not None:
            await self._task

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscriptions(self) -> list[dict[str, Any]]:
        return [{"channel": "quote", "symbols": self._symbols, "interval": self._interval}]

    async def _poll_loop(self) -> None:
        while self._connected:
            for symbol in self._symbols:
                try:
                    quote = await self._market_service.quote(symbol)
                    await self._emit(
                        StreamEvent(
                            "ticker",
                            symbol,
                            {
                                "price": quote.price,
                                "currency": quote.currency,
                                "provider": quote.provider,
                                "status": quote.status,
                            },
                            source="equity",
                        )
                    )
                except Exception:  # noqa: BLE001 - poll failures should not crash the loop
                    pass
            await asyncio.sleep(self._interval)

    async def _emit(self, event: StreamEvent) -> None:
        for callback in self._callbacks:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stream Manager
# ---------------------------------------------------------------------------


class StreamManager:
    """Manages active realtime stream connections."""

    def __init__(self) -> None:
        self._streams: dict[str, Any] = {}

    def register(self, name: str, adapter: Any) -> None:
        self._streams[name.lower()] = adapter

    def get(self, name: str) -> Any | None:
        return self._streams.get(name.lower())

    def list_streams(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name, adapter in self._streams.items():
            result.append({
                "name": getattr(adapter, "name", name),
                "status": getattr(adapter, "status", "unknown"),
                "connected": getattr(adapter, "is_connected", False),
                "subscriptions": getattr(adapter, "subscriptions", []),
            })
        return result

    async def disconnect_all(self) -> None:
        for adapter in self._streams.values():
            if getattr(adapter, "is_connected", False):
                try:
                    await adapter.disconnect()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kraken_pair(symbol: str) -> str:
    """Convert common symbol formats to Kraken pair names."""
    symbol = symbol.upper().replace("-", "").replace("/", "")
    # Common mappings
    mappings = {
        "BTCUSD": "XBT/USD",
        "ETHUSD": "ETH/USD",
        "SOLUSD": "SOL/USD",
        "XRPUSD": "XRP/USD",
        "DOGEUSD": "DOGE/USD",
        "ADAUSD": "ADA/USD",
        "BTCUSDT": "XBT/USDT",
        "ETHUSDT": "ETH/USDT",
    }
    return mappings.get(symbol, symbol)


def _kraken_channel_to_event_type(channel: str) -> str:
    mapping = {
        "ticker": "ticker",
        "trade": "trade",
        "ohlc": "ohlc",
        "spread": "spread",
        "book": "l2_book",
    }
    return mapping.get(channel.lower(), channel)


def _hyperliquid_channel_to_event_type(channel: str) -> str:
    mapping = {
        "l2Book": "l2_book",
        "trades": "trade",
        "allMids": "mid",
        "userEvents": "user_event",
    }
    return mapping.get(channel, channel)
