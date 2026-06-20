"""Portfolio management service."""

from __future__ import annotations

from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.formatting import normalize_symbol


class PortfolioService:
    def __init__(self, db: FinCLIDatabase, portfolio_name: str = "main") -> None:
        self.db = db
        self.portfolio_name = portfolio_name

    def set_portfolio(self, name: str) -> None:
        """Switch active portfolio."""
        self.portfolio_name = name

    def create(self, name: str, description: str = "") -> None:
        """Create a new portfolio."""
        self.db.execute(
            "INSERT OR IGNORE INTO portfolios (name, description) VALUES (?, ?)",
            (name.lower(), description),
        )

    def delete(self, name: str) -> bool:
        """Delete a portfolio and its positions."""
        if name.lower() == "main":
            return False
        self.db.execute("DELETE FROM portfolio_positions WHERE portfolio_name = ?", (name.lower(),))
        self.db.execute("DELETE FROM portfolios WHERE name = ?", (name.lower(),))
        return True

    def list_portfolios(self) -> list[dict[str, object]]:
        """List all portfolios."""
        rows = self.db.query("SELECT name, description, created_at FROM portfolios ORDER BY name")
        return [dict(row) for row in rows]

    def add(self, symbol: str, quantity: float, average_price: float, currency: str = "USD") -> None:
        self.db.execute(
            """
            INSERT INTO portfolio_positions(symbol, portfolio_name, quantity, average_price, currency)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol, portfolio_name) DO UPDATE SET
                quantity = excluded.quantity,
                average_price = excluded.average_price,
                currency = excluded.currency,
                updated_at = CURRENT_TIMESTAMP
            """,
            (normalize_symbol(symbol), self.portfolio_name, quantity, average_price, currency.upper()),
        )

    def update(self, symbol: str, quantity: float, price: float, currency: str = "USD") -> dict[str, object]:
        """Add to existing position with weighted average (DCA)."""
        normalized = normalize_symbol(symbol)
        existing = self.db.query(
            "SELECT quantity, average_price, currency FROM portfolio_positions WHERE symbol = ? AND portfolio_name = ?",
            (normalized, self.portfolio_name),
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
                """UPDATE portfolio_positions SET quantity = ?, average_price = ?, currency = ?, updated_at = CURRENT_TIMESTAMP WHERE symbol = ? AND portfolio_name = ?""",
                (new_qty, new_avg, cur, normalized, self.portfolio_name),
            )
            return {"action": "updated", "symbol": normalized, "quantity": new_qty, "average_price": new_avg, "old_quantity": old_qty, "old_average_price": old_price}
        else:
            self.add(normalized, quantity, price, currency)
            return {"action": "created", "symbol": normalized, "quantity": quantity, "average_price": price}

    def remove(self, symbol: str) -> None:
        self.db.execute(
            "DELETE FROM portfolio_positions WHERE symbol = ? AND portfolio_name = ?",
            (normalize_symbol(symbol), self.portfolio_name),
        )

    def list(self) -> list[dict[str, object]]:
        rows = self.db.query(
            "SELECT symbol, quantity, average_price, currency, updated_at FROM portfolio_positions WHERE portfolio_name = ? ORDER BY symbol",
            (self.portfolio_name,),
        )
        return [dict(row) for row in rows]

    def compare(self, other_name: str) -> dict[str, list[dict[str, object]]]:
        """Compare two portfolios."""
        current = self.list()
        other_rows = self.db.query(
            "SELECT symbol, quantity, average_price, currency, updated_at FROM portfolio_positions WHERE portfolio_name = ? ORDER BY symbol",
            (other_name.lower(),),
        )
        other = [dict(row) for row in other_rows]
        return {self.portfolio_name: current, other_name: other}
