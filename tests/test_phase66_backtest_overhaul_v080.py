from __future__ import annotations

from datetime import datetime

from fincli.app.analysis.backtest import (
    BacktestResult,
    FeeProfile,
    MonteCarloResult,
    PositionSizer,
    WalkForwardResult,
    get_fee_profile,
    run_backtest,
)
from fincli.app.providers.market.base import Candle


def make_candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, index % 24),
            open=close - 0.5,
            high=close + 1.0,
            low=close - 1.0,
            close=close,
            volume=1_000 + index,
        )
        for index, close in enumerate(closes)
    ]


def trending_candles(count: int = 100) -> list[Candle]:
    """Generate candles with a clear uptrend then downtrend."""
    up = [100 + i * 0.5 for i in range(count // 2)]
    down = [up[-1] - i * 0.5 for i in range(count // 2)]
    return make_candles(up + down)


# ---------------------------------------------------------------------------
# Fee profile tests
# ---------------------------------------------------------------------------


def test_fee_profiles_cover_asset_classes() -> None:
    classes = ["equity", "forex", "crypto", "commodity", "index", "etf"]
    for cls in classes:
        profile = get_fee_profile(cls)
        assert profile.fee_pct >= 0
        assert profile.slippage_pct >= 0
        assert profile.total_cost_pct > 0


def test_fee_profile_falls_back_to_default() -> None:
    profile = get_fee_profile("unknown_asset")
    assert profile == get_fee_profile("default")


# ---------------------------------------------------------------------------
# Position sizer tests
# ---------------------------------------------------------------------------


def test_position_sizer_fixed_fractional() -> None:
    sizer = PositionSizer(method="fixed_fractional", fraction=0.02)
    qty = sizer.size(equity=10000, win_rate=50, avg_win=5, avg_loss=3, price=100)
    assert qty == 2.0  # 10000 * 0.02 / 100


def test_position_sizer_kelly() -> None:
    sizer = PositionSizer(method="kelly", fraction=0.02, kelly_fraction=0.25)
    qty = sizer.size(equity=10000, win_rate=60, avg_win=10, avg_loss=5, price=100)
    assert qty > 0


# ---------------------------------------------------------------------------
# Strategy tests
# ---------------------------------------------------------------------------


def test_backtest_sma_cross_with_fees() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d", asset_class="equity")

    assert result.symbol == "TEST"
    assert result.strategy == "sma_cross"
    assert result.total_fees >= 0
    assert result.fee_profile_used != ""
    assert result.position_sizer_used != ""
    assert result.initial_equity == 10000.0


def test_backtest_rsi_reversion() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "rsi_reversion", "1d")

    assert result.strategy == "rsi_reversion"
    assert result.candles == 100


def test_backtest_momentum() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "momentum", "1d")

    assert result.strategy == "momentum"


def test_backtest_bollinger() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "bollinger", "1d")

    assert result.strategy == "bollinger"


def test_backtest_multi_factor() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "multi_factor", "1d")

    assert result.strategy == "multi_factor"


# ---------------------------------------------------------------------------
# Risk ratio tests
# ---------------------------------------------------------------------------


def test_backtest_calculates_sharpe_sortino_calmar() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d")

    assert isinstance(result.sharpe_ratio, float)
    assert isinstance(result.sortino_ratio, float)
    assert isinstance(result.calmar_ratio, float)


# ---------------------------------------------------------------------------
# Trade statistics tests
# ---------------------------------------------------------------------------


def test_backtest_calculates_trade_statistics() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d")

    assert result.total_trades >= 0
    assert result.winning_trades + result.losing_trades == result.total_trades
    assert isinstance(result.profit_factor, float)
    assert isinstance(result.expectancy, float)
    assert isinstance(result.consecutive_wins, int)
    assert isinstance(result.consecutive_losses, int)


# ---------------------------------------------------------------------------
# Monte Carlo tests
# ---------------------------------------------------------------------------


def test_backtest_monte_carlo() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d", include_monte_carlo=True, monte_carlo_sims=100)

    if result.trades:  # MC only runs if there are trades
        assert result.monte_carlo is not None
        assert result.monte_carlo.simulations == 100
        assert isinstance(result.monte_carlo.percentile_5, float)
        assert isinstance(result.monte_carlo.percentile_50, float)
        assert isinstance(result.monte_carlo.percentile_95, float)


# ---------------------------------------------------------------------------
# Walk-forward tests
# ---------------------------------------------------------------------------


def test_backtest_walk_forward() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d", walk_forward=True)

    assert result.walk_forward is not None
    assert isinstance(result.walk_forward.in_sample, BacktestResult)
    assert isinstance(result.walk_forward.out_of_sample, BacktestResult)
    assert isinstance(result.walk_forward.overfit_ratio, float)


# ---------------------------------------------------------------------------
# Position sizing tests
# ---------------------------------------------------------------------------


def test_backtest_with_kelly_sizing() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d", position_method="kelly", position_fraction=0.02)

    assert "kelly" in result.position_sizer_used


# ---------------------------------------------------------------------------
# Equity curve tests
# ---------------------------------------------------------------------------


def test_backtest_equity_curve_populated() -> None:
    candles = trending_candles(100)
    result = run_backtest("TEST", candles, "sma_cross", "1d")

    assert len(result.equity_curve) == len(candles)
    assert result.equity_curve[0] == result.initial_equity
