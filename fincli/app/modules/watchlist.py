"""Watchlist commands backed by local SQLite."""

from __future__ import annotations

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.formatting import normalize_symbol


class WatchlistService:
    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def add(self, symbol: str, group_name: str = "default") -> None:
        normalized = normalize_symbol(symbol)
        self.db.execute(
            "INSERT OR REPLACE INTO watchlist(symbol, group_name) VALUES (?, ?)",
            (normalized, group_name),
        )

    def remove(self, symbol: str) -> None:
        self.db.execute("DELETE FROM watchlist WHERE symbol = ?", (normalize_symbol(symbol),))

    def list(self) -> list[dict[str, str]]:
        rows = self.db.query("SELECT symbol, group_name, created_at FROM watchlist ORDER BY symbol")
        return [dict(row) for row in rows]
