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

    def remove(self, symbol: str) -> None:
        self.db.execute("DELETE FROM portfolio_positions WHERE symbol = ?", (normalize_symbol(symbol),))

    def list(self) -> list[dict[str, object]]:
        rows = self.db.query(
            "SELECT symbol, quantity, average_price, currency, updated_at FROM portfolio_positions ORDER BY symbol"
        )
        return [dict(row) for row in rows]
