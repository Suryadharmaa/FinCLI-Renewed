from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console

from fincli.app.cli.router import CommandRouter
from fincli.app.modules.portfolio_analytics import PortfolioAnalytics
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase

if TYPE_CHECKING:
    from pathlib import Path


def render_text(renderable: object) -> str:
    console = Console(record=True, width=160)
    console.print(renderable)
    return console.export_text()


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------


def test_portfolio_analytics_saves_and_retrieves_snapshots(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    analytics.save_snapshot(10000, 9500, 500, 100)
    analytics.save_snapshot(10200, 9500, 700, 100)

    snapshots = analytics.get_snapshots()
    assert len(snapshots) == 2
    assert snapshots[0].total_value == 10200  # latest first
    assert snapshots[1].total_value == 10000


def test_portfolio_analytics_latest_snapshot(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    analytics.save_snapshot(10000, 9500, 500, 100)
    analytics.save_snapshot(10200, 9500, 700, 100)

    latest = analytics.get_latest_snapshot()
    assert latest is not None
    assert latest.total_value == 10200


def test_portfolio_analytics_no_snapshots(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    assert analytics.get_latest_snapshot() is None
    assert analytics.get_snapshots() == []


# ---------------------------------------------------------------------------
# Risk ratio tests
# ---------------------------------------------------------------------------


def test_risk_ratios_with_insufficient_data(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    ratios = analytics.calculate_risk_ratios()
    assert ratios.sharpe == 0
    assert ratios.trading_days == 0


def test_risk_ratios_with_data(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    # Save 30 days of increasing values
    for i in range(30):
        analytics.save_snapshot(10000 + i * 50, 9500, 500 + i * 50, 100)

    ratios = analytics.calculate_risk_ratios()
    assert ratios.trading_days == 30
    assert ratios.annualized_return > 0
    assert ratios.max_drawdown >= 0


# ---------------------------------------------------------------------------
# Rebalancing tests
# ---------------------------------------------------------------------------


def test_rebalance_suggestions_concentrated(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    positions = [
        {"symbol": "AAPL", "quantity": 10, "average_price": 100, "currency": "USD"},
        {"symbol": "BTC-USD", "quantity": 0.01, "average_price": 50000, "currency": "USD"},
    ]
    market_values = {
        "AAPL": (150.0, 500.0, 50.0),
        "BTC-USD": (60000.0, 100.0, 20.0),
    }

    report = analytics.suggest_rebalance(positions, market_values, max_concentration_pct=25.0)

    assert report.total_trades > 0  # Should suggest rebalancing due to concentration
    assert any(s.action == "trim" for s in report.suggestions)


def test_rebalance_no_positions(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    report = analytics.suggest_rebalance([], {})
    assert report.total_trades == 0


# ---------------------------------------------------------------------------
# What-if tests
# ---------------------------------------------------------------------------


def test_whatif_add_position(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    positions = [{"symbol": "AAPL", "quantity": 10, "average_price": 100, "currency": "USD"}]
    market_values = {"AAPL": (150.0, 500.0, 50.0)}

    result = analytics.what_if("add", "BTC-USD", 0.1, 50000, positions, market_values)

    assert result.action == "add"
    assert result.symbol == "BTC-USD"
    assert "Adding" in result.note


def test_whatif_sell_position(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    positions = [
        {"symbol": "AAPL", "quantity": 10, "average_price": 100, "currency": "USD"},
        {"symbol": "BTC-USD", "quantity": 0.1, "average_price": 50000, "currency": "USD"},
    ]
    market_values = {
        "AAPL": (150.0, 500.0, 50.0),
        "BTC-USD": (60000.0, 1000.0, 20.0),
    }

    result = analytics.what_if("sell", "AAPL", 5, 150, positions, market_values)

    assert result.action == "sell"
    assert result.symbol == "AAPL"


# ---------------------------------------------------------------------------
# Benchmark tests
# ---------------------------------------------------------------------------


def test_benchmark_comparison_insufficient_data(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    comparison = analytics.compare_benchmark([100, 105], [1000], "SPY")
    assert comparison.period_days == 0


def test_benchmark_comparison_with_data(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    analytics = PortfolioAnalytics(db)

    portfolio_values = [10000 + i * 10 for i in range(20)]
    benchmark_values = [400 + i * 0.5 for i in range(20)]

    comparison = analytics.compare_benchmark(benchmark_values, portfolio_values, "SPY")

    assert comparison.benchmark_symbol == "SPY"
    assert comparison.period_days > 0
    assert isinstance(comparison.alpha, float)
    assert isinstance(comparison.beta, float)
    assert isinstance(comparison.correlation, float)


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------


def test_portfolio_snapshot_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/portfolio add AAPL 10 100")

    result = router.route("/portfolio snapshot")
    output = render_text(result.renderable)

    assert result.status == "ready"
    assert "snapshot" in output.lower()


def test_portfolio_chart_command_no_snapshots(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))

    result = router.route("/portfolio chart")
    output = render_text(result.renderable)

    assert "snapshot" in output.lower() or "No portfolio" in output


def test_portfolio_chart_command_with_snapshots(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=db)
    router.route("/portfolio add AAPL 10 100")
    router.route("/portfolio snapshot")

    result = router.route("/portfolio chart")
    output = render_text(result.renderable)

    assert "Sharpe" in output
    assert "Sortino" in output


def test_portfolio_whatif_command(tmp_path: Path) -> None:
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=FinCLIDatabase(tmp_path / "fincli.db"))
    router.route("/portfolio add AAPL 10 100")

    result = router.route("/portfolio whatif add BTC-USD 0.1 50000")
    output = render_text(result.renderable)

    assert result.status == "ready"
    assert "BTC-USD" in output


def test_portfolio_benchmark_command(tmp_path: Path) -> None:
    db = FinCLIDatabase(tmp_path / "fincli.db")
    router = CommandRouter(config=ConfigManager(tmp_path / "config.json"), db=db)
    router.route("/portfolio add AAPL 10 100")
    router.route("/portfolio snapshot")

    result = router.route("/portfolio benchmark SPY")
    render_text(result.renderable)

    # Should either show benchmark or say insufficient data
    assert result.status == "ready"
