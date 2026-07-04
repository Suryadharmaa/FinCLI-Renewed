"""Tests for multi-portfolio transaction flows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fincli.app.modules.portfolio import PortfolioService
from fincli.app.modules.transactions import TransactionService
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


def _setup(tmp_path: Path) -> tuple[FinCLIDatabase, PortfolioService, TransactionService]:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    portfolio = PortfolioService(db, portfolio_name="main")
    transactions = TransactionService(db, portfolio)
    return db, portfolio, transactions


def test_transaction_uses_correct_portfolio(tmp_path: Path) -> None:
    """Transaction should only find positions in the active portfolio."""
    db, portfolio, transactions = _setup(tmp_path)

    # Create two portfolios
    portfolio.create("main")
    portfolio.create("crypto")

    # Add position to main
    portfolio.set_portfolio("main")
    portfolio.add("AAPL", 10, 150.0)

    # Add position to crypto
    portfolio.set_portfolio("crypto")
    portfolio.add("BTC-USD", 0.5, 60000.0)

    # Transaction in main should find AAPL
    portfolio.set_portfolio("main")
    result = transactions.add("sell", "AAPL", 5, 160.0)
    assert result["action"] == "sell"
    assert result["symbol"] == "AAPL"

    # Transaction in crypto should find BTC-USD
    portfolio.set_portfolio("crypto")
    result = transactions.add("sell", "BTC-USD", 0.1, 65000.0)
    assert result["action"] == "sell"
    assert result["symbol"] == "BTC-USD"


def test_transaction_cannot_sell_from_wrong_portfolio(tmp_path: Path) -> None:
    """Should fail when selling from a portfolio that doesn't have the position."""
    db, portfolio, transactions = _setup(tmp_path)

    # Add AAPL to main only
    portfolio.set_portfolio("main")
    portfolio.add("AAPL", 10, 150.0)

    # Switch to crypto (empty) and try to sell
    portfolio.set_portfolio("crypto")
    try:
        transactions.add("sell", "AAPL", 5, 160.0)
        raise AssertionError("Should have raised CommandError")
    except Exception as exc:
        assert "No position" in str(exc)


def test_transaction_buy_creates_position_in_active_portfolio(tmp_path: Path) -> None:
    """Buy transaction should create position in the active portfolio."""
    db, portfolio, transactions = _setup(tmp_path)

    portfolio.create("tech")
    portfolio.set_portfolio("tech")

    result = transactions.add("buy", "NVDA", 5, 500.0)
    assert result["action"] == "buy"
    assert result["symbol"] == "NVDA"

    # Verify position exists in tech portfolio
    positions = portfolio.list()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "NVDA"


def test_transaction_realized_pnl_per_portfolio(tmp_path: Path) -> None:
    """Realized PnL should be tracked per transaction, not per portfolio."""
    db, portfolio, transactions = _setup(tmp_path)

    portfolio.set_portfolio("main")
    portfolio.add("AAPL", 10, 100.0)

    # Sell at profit
    transactions.add("sell", "AAPL", 5, 150.0)
    pnl = transactions.realized_pnl_total()
    assert pnl == 250.0  # (150 - 100) * 5


def test_multi_portfolio_independent_positions(tmp_path: Path) -> None:
    """Positions in different portfolios should be independent."""
    db, portfolio, transactions = _setup(tmp_path)

    portfolio.create("main")
    portfolio.create("swing")

    # Same symbol in different portfolios
    portfolio.set_portfolio("main")
    portfolio.add("AAPL", 10, 150.0)

    portfolio.set_portfolio("swing")
    portfolio.add("AAPL", 20, 140.0)

    # Verify independent
    portfolio.set_portfolio("main")
    main_positions = portfolio.list()
    assert len(main_positions) == 1
    assert float(main_positions[0]["quantity"]) == 10.0

    portfolio.set_portfolio("swing")
    swing_positions = portfolio.list()
    assert len(swing_positions) == 1
    assert float(swing_positions[0]["quantity"]) == 20.0
