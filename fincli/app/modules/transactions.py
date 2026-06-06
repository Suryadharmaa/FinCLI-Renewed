"""Portfolio transaction ledger."""

from __future__ import annotations

from fincli.app.modules.portfolio import PortfolioService
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.utils.errors import CommandError
from fincli.app.utils.formatting import normalize_symbol


class TransactionService:
    def __init__(self, db: FinCLIDatabase, portfolio: PortfolioService) -> None:
        self.db = db
        self.portfolio = portfolio

    def add(self, action: str, symbol: str, quantity: float, price: float, currency: str = "USD") -> dict[str, object]:
        normalized_action = action.lower()
        normalized_symbol = normalize_symbol(symbol)
        if normalized_action not in {"buy", "sell"}:
            raise CommandError("Action transaksi harus buy atau sell.")
        if quantity <= 0 or price <= 0:
            raise CommandError("Quantity dan price harus lebih besar dari 0.")

        current = self._position(normalized_symbol)
        realized_pnl = 0.0

        if normalized_action == "buy":
            old_qty = float(current["quantity"]) if current else 0.0
            old_avg = float(current["average_price"]) if current else 0.0
            new_qty = old_qty + quantity
            new_avg = ((old_qty * old_avg) + (quantity * price)) / new_qty
            self.portfolio.add(normalized_symbol, new_qty, new_avg, currency)
        else:
            if current is None:
                raise CommandError(f"Tidak ada posisi {normalized_symbol} untuk dijual.")
            old_qty = float(current["quantity"])
            old_avg = float(current["average_price"])
            if quantity > old_qty:
                raise CommandError(f"Quantity sell melebihi posisi {normalized_symbol}.")
            realized_pnl = (price - old_avg) * quantity
            remaining = old_qty - quantity
            if remaining == 0:
                self.portfolio.remove(normalized_symbol)
            else:
                self.portfolio.add(normalized_symbol, remaining, old_avg, currency)

        self.db.execute(
            """
            INSERT INTO portfolio_transactions(action, symbol, quantity, price, currency, realized_pnl)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (normalized_action, normalized_symbol, quantity, price, currency.upper(), realized_pnl),
        )
        return {
            "action": normalized_action,
            "symbol": normalized_symbol,
            "quantity": quantity,
            "price": price,
            "currency": currency.upper(),
            "realized_pnl": realized_pnl,
        }

    def list(self, limit: int = 50) -> list[dict[str, object]]:
        rows = self.db.query(
            """
            SELECT id, action, symbol, quantity, price, currency, realized_pnl, created_at
            FROM portfolio_transactions
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in rows]

    def realized_pnl_total(self) -> float:
        rows = self.db.query("SELECT COALESCE(SUM(realized_pnl), 0) AS total FROM portfolio_transactions")
        return float(rows[0]["total"]) if rows else 0.0

    def _position(self, symbol: str) -> dict[str, object] | None:
        rows = self.db.query(
            "SELECT symbol, quantity, average_price, currency FROM portfolio_positions WHERE symbol = ?",
            (symbol,),
        )
        return dict(rows[0]) if rows else None
