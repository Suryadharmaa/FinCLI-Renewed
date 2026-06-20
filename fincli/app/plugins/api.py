"""Public API for FinCLI plugins (v1.2.0).

Plugins access FinCLI data through this API, not directly through
filesystem or internal modules. This provides a security boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class PluginAPIError(Exception):
    """Error raised by plugin API calls."""


@dataclass(frozen=True, slots=True)
class QuoteData:
    """Quote data exposed to plugins."""
    symbol: str
    price: float | None
    currency: str
    provider: str
    status: str


@dataclass(frozen=True, slots=True)
class PositionData:
    """Portfolio position exposed to plugins."""
    symbol: str
    quantity: float
    average_price: float
    currency: str


@dataclass(frozen=True, slots=True)
class WatchlistData:
    """Watchlist entry exposed to plugins."""
    symbol: str
    group: str
    notes: str


class FinCLIPluginAPI:
    """Public API boundary for plugins.

    Plugins interact with FinCLI through this API only.
    Direct access to filesystem, database, secrets, or network is blocked.
    """

    def __init__(
        self,
        quote_getter: Any = None,
        portfolio_getter: Any = None,
        watchlist_getter: Any = None,
        alert_adder: Any = None,
    ) -> None:
        self._quote_getter = quote_getter
        self._portfolio_getter = portfolio_getter
        self._watchlist_getter = watchlist_getter
        self._alert_adder = alert_adder
        self._log_entries: list[str] = []

    def get_quote(self, symbol: str) -> QuoteData:
        """Get current quote for a symbol.

        Returns QuoteData with price, currency, provider info.
        Raises PluginAPIError if quote unavailable.
        """
        if not self._quote_getter:
            raise PluginAPIError("Quote provider not available.")

        try:
            quote = self._quote_getter(symbol)
            return QuoteData(
                symbol=getattr(quote, "symbol", symbol),
                price=getattr(quote, "price", None),
                currency=getattr(quote, "currency", "USD"),
                provider=getattr(quote, "provider", "unknown"),
                status=getattr(quote, "status", "unknown"),
            )
        except Exception as exc:
            raise PluginAPIError(f"Failed to get quote for {symbol}: {exc}") from exc

    def get_portfolio(self) -> list[PositionData]:
        """Get all portfolio positions.

        Returns list of PositionData.
        """
        if not self._portfolio_getter:
            raise PluginAPIError("Portfolio not available.")

        try:
            rows = self._portfolio_getter()
            return [
                PositionData(
                    symbol=str(row.get("symbol", "")),
                    quantity=float(row.get("quantity", 0)),
                    average_price=float(row.get("average_price", 0)),
                    currency=str(row.get("currency", "USD")),
                )
                for row in rows
            ]
        except Exception as exc:
            raise PluginAPIError(f"Failed to get portfolio: {exc}") from exc

    def get_watchlist(self, group: str = "") -> list[WatchlistData]:
        """Get watchlist entries, optionally filtered by group.

        Returns list of WatchlistData.
        """
        if not self._watchlist_getter:
            raise PluginAPIError("Watchlist not available.")

        try:
            rows = self._watchlist_getter(group)
            return [
                WatchlistData(
                    symbol=str(row.get("symbol", "")),
                    group=str(row.get("group", "")),
                    notes=str(row.get("notes", "")),
                )
                for row in rows
            ]
        except Exception as exc:
            raise PluginAPIError(f"Failed to get watchlist: {exc}") from exc

    def add_alert(self, symbol: str, condition: str, value: float) -> bool:
        """Add a price alert.

        Args:
            symbol: Instrument symbol
            condition: "above" or "below"
            value: Price threshold

        Returns True if alert added successfully.
        """
        if not self._alert_adder:
            raise PluginAPIError("Alert service not available.")

        try:
            self._alert_adder(symbol, condition, value)
            return True
        except Exception as exc:
            raise PluginAPIError(f"Failed to add alert: {exc}") from exc

    def log(self, message: str) -> None:
        """Log a message from plugin.

        Messages are collected and can be displayed to user.
        """
        self._log_entries.append(str(message))

    def get_logs(self) -> list[str]:
        """Get all plugin log messages."""
        return list(self._log_entries)

    def clear_logs(self) -> None:
        """Clear plugin log messages."""
        self._log_entries.clear()


def create_plugin_api(router: Any) -> FinCLIPluginAPI:
    """Create a PluginAPI instance from a CommandRouter.

    This is the factory that connects plugin API to FinCLI internals.
    """
    def quote_getter(symbol: str):
        return router._get_quote(symbol)

    def portfolio_getter():
        return router.portfolio.list()

    def watchlist_getter(group: str = ""):
        if group:
            return router.watchlist.list(group=group)
        return router.watchlist.list()

    def alert_adder(symbol: str, condition: str, value: float):
        router.alerts.add(symbol, condition, value)

    return FinCLIPluginAPI(
        quote_getter=quote_getter,
        portfolio_getter=portfolio_getter,
        watchlist_getter=watchlist_getter,
        alert_adder=alert_adder,
    )
