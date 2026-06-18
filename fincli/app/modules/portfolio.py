"""Portfolio management service."""

from __future__ import annotations

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.formatting import normalize_symbol


class PortfolioService:
    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def add(self, symbol: str, quantity: float, average_price: float, currency: str = "USD") -> None:
        self.db.execute(
            """
            INSERT INTO portfolio_positions(symbol, quantity, average_price, currency)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                quantity = excluded.quantity,
                average_price = excluded.average_price,
                currency = excluded.currency,
                updated_at = CURRENT_TIMESTAMP
            """,
            (normalize_symbol(symbol), quantity, average_price, currency.upper()),
        )

    def update(self, symbol: str, quantity: float, price: float, currency: str = "USD") -> dict[str, object]:
        """Add to existing position with weighted average (DCA)."""
        normalized = normalize_symbol(symbol)
        existing = self.db.query(
            "SELECT quantity, average_price, currency FROM portfolio_positions WHERE symbol = ?",
            (normalized,),
        )
        if existing:
            old_qty = float(existing[0]["quantity"])
            old_price = float(existing[0]["average_price"])
            cur = str(existing[0]["currency"]) or currency.upper()
            new_qty = old_qty + quantity
            if new_qty <= 0:
                self.remove(normalized)
                return {"action": "closed", "symbol": normalized, "quantity": 0}
            new_avg = (old_qty * old_price + quantity * price) / new_qty
            self.db.execute(
                """UPDATE portfolio_positions SET quantity = ?, average_price = ?, currency = ?, updated_at = CURRENT_TIMESTAMP WHERE symbol = ?""",
                (new_qty, new_avg, cur, normalized),
            )
            return {"action": "updated", "symbol": normalized, "quantity": new_qty, "average_price": new_avg, "old_quantity": old_qty, "old_average_price": old_price}
        else:
            self.add(normalized, quantity, price, currency)
            return {"action": "created", "symbol": normalized, "quantity": quantity, "average_price": price}

    def remove(self, symbol: str) -> None:
        self.db.execute("DELETE FROM portfolio_positions WHERE symbol = ?", (normalize_symbol(symbol),))

    def list(self) -> list[dict[str, object]]:
        rows = self.db.query(
            "SELECT symbol, quantity, average_price, currency, updated_at FROM portfolio_positions ORDER BY symbol"
        )
        return [dict(row) for row in rows]
