"""Watchlist commands backed by local SQLite."""

from __future__ import annotations

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.formatting import normalize_symbol


class WatchlistService:
    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def add(self, symbol: str, group_name: str = "default", notes: str = "") -> None:
        normalized = normalize_symbol(symbol)
        self.db.execute(
            "INSERT OR REPLACE INTO watchlist(symbol, group_name, notes) VALUES (?, ?, ?)",
            (normalized, group_name, notes),
        )

    def remove(self, symbol: str) -> None:
        self.db.execute("DELETE FROM watchlist WHERE symbol = ?", (normalize_symbol(symbol),))

    def get(self, symbol: str) -> dict[str, str] | None:
        rows = self.db.query(
            "SELECT symbol, group_name, notes, created_at FROM watchlist WHERE symbol = ?",
            (normalize_symbol(symbol),),
        )
        return dict(rows[0]) if rows else None

    def update_notes(self, symbol: str, notes: str) -> None:
        self.db.execute(
            "UPDATE watchlist SET notes = ? WHERE symbol = ?",
            (notes, normalize_symbol(symbol)),
        )

    def list(self, group: str | None = None) -> list[dict[str, str]]:
        if group:
            rows = self.db.query(
                "SELECT symbol, group_name, notes, created_at FROM watchlist WHERE group_name = ? ORDER BY symbol",
                (group,),
            )
        else:
            rows = self.db.query("SELECT symbol, group_name, notes, created_at FROM watchlist ORDER BY group_name, symbol")
        return [dict(row) for row in rows]

    def groups(self) -> list[str]:
        rows = self.db.query("SELECT DISTINCT group_name FROM watchlist ORDER BY group_name")
        return [str(row["group_name"]) for row in rows]
