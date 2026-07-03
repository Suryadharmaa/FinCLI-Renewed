"""Professional backtesting engine for FinCLI (v0.8.0).

Features: fees/slippage modeling, walk-forward split, position sizing,
risk-adjusted ratios (Sharpe/Sortino/Calmar), trade statistics,
Monte Carlo robustness testing, and exportable reports.

Note on Monte Carlo:
    Monte Carlo simulation bootstraps observed trade returns with replacement
    and compounds the sampled sequence. `_monte_carlo(..., seed=N)` supports
    deterministic regression tests without mutating global RNG state.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import sqrt
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fincli.app.providers.market.base import Candle

# ---------------------------------------------------------------------------
# Fee/slippage profiles per asset class
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FeeProfile:
    """Trading cost profile for an asset class."""

    fee_pct: float  # commission as % of notional
    slippage_pct: float  # slippage as % of price
    spread_pct: float = 0.0  # bid-ask spread as % of price

    @property
    def total_cost_pct(self) -> float:
        return self.fee_pct + self.slippage_pct + self.spread_pct


FEE_PROFILES: dict[str, FeeProfile] = {
    "equity": FeeProfile(fee_pct=0.10, slippage_pct=0.05, spread_pct=0.01),
    "forex": FeeProfile(fee_pct=0.0, slippage_pct=0.02, spread_pct=0.08),
    "crypto": FeeProfile(fee_pct=0.20, slippage_pct=0.10, spread_pct=0.05),
    "commodity": FeeProfile(fee_pct=0.15, slippage_pct=0.08, spread_pct=0.03),
    "index": FeeProfile(fee_pct=0.05, slippage_pct=0.03, spread_pct=0.01),
    "etf": FeeProfile(fee_pct=0.05, slippage_pct=0.03, spread_pct=0.01),
    "default": FeeProfile(fee_pct=0.10, slippage_pct=0.05, spread_pct=0.02),
}


def get_fee_profile(asset_class: str) -> FeeProfile:
    return FEE_PROFILES.get(asset_class.lower().strip(), FEE_PROFILES["default"])


# ---------------------------------------------------------------------------
# Position sizing models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionSizer:
    """Position sizing configuration."""

    method: str  # fixed, fixed_fractional, kelly
    fraction: float = 0.02  # 2% of equity per trade (fixed_fractional)
    kelly_fraction: float = 0.25  # quarter-Kelly for safety

    def size(self, equity: float, win_rate: float, avg_win: float, avg_loss: float, price: float) -> float:
        if self.method == "fixed":
            return equity * self.fraction / price if price > 0 else 0
        if self.method == "fixed_fractional":
            return equity * self.fraction / price if price > 0 else 0
        if self.method == "kelly":
            return self._kelly_size(equity, win_rate, avg_win, avg_loss, price)
        return equity * self.fraction / price if price > 0 else 0

    def _kelly_size(self, equity: float, win_rate: float, avg_win: float, avg_loss: float, price: float) -> float:
        if price <= 0:
            return 0.0
        if avg_loss >= 0:  # avg_loss should be negative for losing trades
            return equity * self.fraction / price
        b = avg_win / abs(avg_loss)  # win/loss ratio (avg_loss is negative)
        p = win_rate / 100.0
        q = 1 - p
        kelly_pct = (b * p - q) / b
        kelly_pct = max(0, kelly_pct) * self.kelly_fraction  # apply safety fraction
        return equity * kelly_pct / price


# ---------------------------------------------------------------------------
# Trade model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    """One completed trade from backtest."""

    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl_percent: float
    pnl_absolute: float
    fees_paid: float
    reason: str


# ---------------------------------------------------------------------------
# Monte Carlo result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Monte Carlo simulation output.

    Note: Results are non-deterministic. Each run shuffles trade order
    randomly, producing different equity curves. Use percentile ranges
    (5th/50th/95th) to understand outcome distribution, not exact values.
    """

    simulations: int
    percentile_5: float
    percentile_50: float
    percentile_95: float
    mean_return: float
    std_return: float
    worst_case: float
    best_case: float


# ---------------------------------------------------------------------------
# Walk-forward result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """Walk-forward split result."""

    in_sample: BacktestResult
    out_of_sample: BacktestResult
    overfit_ratio: float  # how much worse out-of-sample is vs in-sample


# ---------------------------------------------------------------------------
# Backtest result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Complete backtest output."""

    symbol: str
    strategy: str
    interval: str
    candles: int
    trades: tuple[BacktestTrade, ...]
    total_return_percent: float
    total_return_absolute: float
    win_rate: float
    max_drawdown_percent: float
    exposure_percent: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    profit_factor: float
    expectancy: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    consecutive_wins: int
    consecutive_losses: int
    total_fees: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    notes: tuple[str, ...]
    equity_curve: list[float] = field(default_factory=list)
    monte_carlo: MonteCarloResult | None = None
    walk_forward: WalkForwardResult | None = None
    fee_profile_used: str = ""
    position_sizer_used: str = ""
    initial_equity: float = 10000.0


# ---------------------------------------------------------------------------
# Main backtest runner
# ---------------------------------------------------------------------------


def run_backtest(
    symbol: str,
    candles: list[Candle],
    strategy: str = "sma_cross",
    interval: str = "1d",
    asset_class: str = "equity",
    initial_equity: float = 10000.0,
    position_method: str = "fixed_fractional",
    position_fraction: float = 0.02,
    fee_override: FeeProfile | None = None,
    include_monte_carlo: bool = False,
    monte_carlo_sims: int = 1000,
    walk_forward: bool = False,
    strategy_params: dict[str, Any] | None = None,
) -> BacktestResult:
    """Run a professional backtest with fees, slippage, and position sizing."""
    if len(candles) < 30:
        raise ValueError("Backtest needs at least 30 candles.")

    fee_profile = fee_override or get_fee_profile(asset_class)
    sizer = PositionSizer(method=position_method, fraction=position_fraction)
    normalized = strategy.lower().strip()

    if walk_forward:
        return _run_walk_forward(symbol, candles, normalized, interval, fee_profile, sizer, initial_equity, include_monte_carlo, monte_carlo_sims, asset_class, strategy_params)

    trades = _run_strategy(normalized, candles, fee_profile, sizer, initial_equity, strategy_params)
    result = _build_result(symbol, normalized, interval, candles, trades, fee_profile, sizer, initial_equity)

    if include_monte_carlo and trades:
        mc = _monte_carlo(trades, initial_equity, monte_carlo_sims)
        result = _replace_monte_carlo(result, mc)

    return result


# ---------------------------------------------------------------------------
# Strategy dispatch
# ---------------------------------------------------------------------------


def _run_strategy(
    strategy: str,
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    params: dict[str, Any] | None = None,
) -> list[BacktestTrade]:
    p = params or {}
    if strategy in {"sma", "sma_cross", "ma_cross"}:
        return _sma_cross_trades(candles, fee_profile, sizer, initial_equity,
            fast=int(p.get("fast_period", 10)), slow=int(p.get("slow_period", 30)))
    if strategy in {"rsi", "rsi_reversion", "mean_reversion"}:
        return _rsi_reversion_trades(candles, fee_profile, sizer, initial_equity,
            buy_level=float(p.get("oversold", 30)), sell_level=float(p.get("overbought", 55)))
    if strategy in {"momentum", "mom"}:
        return _momentum_trades(candles, fee_profile, sizer, initial_equity)
    if strategy in {"bollinger", "bollinger_breakout", "bollinger_squeeze", "bb"}:
        return _bollinger_trades(candles, fee_profile, sizer, initial_equity,
            period=int(p.get("period", 20)), num_std=float(p.get("num_std", 2.0)))
    if strategy in {"macd_divergence", "macd"}:
        return _macd_divergence_trades(candles, fee_profile, sizer, initial_equity)
    if strategy in {"volume_breakout", "volume"}:
        return _volume_breakout_trades(candles, fee_profile, sizer, initial_equity,
            volume_mult=float(p.get("volume_multiplier", 2.0)), lookback=int(p.get("lookback", 20)))
    if strategy in {"zscore", "z_score", "mean_reversion_zscore"}:
        return _zscore_trades(candles, fee_profile, sizer, initial_equity,
            lookback=int(p.get("lookback", 30)), threshold=float(p.get("z_threshold", 2.0)))
    if strategy in {"multi_factor", "multifactor", "combo"}:
        return _multi_factor_trades(candles, fee_profile, sizer, initial_equity)
    raise ValueError(
        f"Unknown strategy: {strategy}. Use: sma_cross, rsi_reversion, momentum, bollinger_squeeze, "
        "macd_divergence, volume_breakout, mean_reversion_zscore, or multi_factor."
    )


# ---------------------------------------------------------------------------
# Result builder
# ---------------------------------------------------------------------------


def _build_result(
    symbol: str,
    strategy: str,
    interval: str,
    candles: list[Candle],
    trades: list[BacktestTrade],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
) -> BacktestResult:
    equity_curve = _equity_curve(candles, trades, initial_equity)
    total_return_abs = equity_curve[-1] - initial_equity
    total_return_pct = (total_return_abs / initial_equity) * 100 if initial_equity else 0
    max_drawdown = _max_drawdown(equity_curve, initial_equity)
    wins = [t for t in trades if t.pnl_absolute > 0]
    losses = [t for t in trades if t.pnl_absolute <= 0]
    win_rate = (len(wins) / len(trades) * 100) if trades else 0.0
    exposure = _exposure(candles, trades)
    total_fees = sum(t.fees_paid for t in trades)

    # Risk-adjusted ratios (annualized assuming 252 trading days)
    daily_returns = _daily_returns(equity_curve)
    sharpe = _sharpe_ratio(daily_returns)
    sortino = _sortino_ratio(daily_returns)
    calmar = _calmar_ratio(total_return_pct, max_drawdown)

    # Trade statistics
    avg_win = _avg([t.pnl_percent for t in wins]) if wins else 0.0
    avg_loss = _avg([t.pnl_percent for t in losses]) if losses else 0.0
    largest_win = max((t.pnl_percent for t in wins), default=0.0)
    largest_loss = min((t.pnl_percent for t in losses), default=0.0)
    profit_factor = _profit_factor(wins, losses)
    expectancy = _expectancy(win_rate, avg_win, avg_loss)
    consec_wins, consec_losses = _streaks(trades)

    notes = _result_notes(trades, total_return_pct, max_drawdown, fee_profile)

    return BacktestResult(
        symbol=symbol.upper(),
        strategy=strategy,
        interval=interval,
        candles=len(candles),
        trades=tuple(trades),
        total_return_percent=total_return_pct,
        total_return_absolute=total_return_abs,
        win_rate=win_rate,
        max_drawdown_percent=max_drawdown,
        exposure_percent=exposure,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        profit_factor=profit_factor,
        expectancy=expectancy,
        avg_win=avg_win,
        avg_loss=avg_loss,
        largest_win=largest_win,
        largest_loss=largest_loss,
        consecutive_wins=consec_wins,
        consecutive_losses=consec_losses,
        total_fees=total_fees,
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        notes=notes,
        equity_curve=equity_curve,
        fee_profile_used=f"fee={fee_profile.fee_pct:.2f}% slippage={fee_profile.slippage_pct:.2f}% spread={fee_profile.spread_pct:.2f}%",
        position_sizer_used=f"{sizer.method} ({sizer.fraction:.1%})",
        initial_equity=initial_equity,
    )


# ---------------------------------------------------------------------------
# SMA Cross strategy
# ---------------------------------------------------------------------------


def _sma_cross_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    fast: int = 10,
    slow: int = 30,
) -> list[BacktestTrade]:
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None  # (index, price, quantity)
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(slow, len(closes)):
        fast_ma = _sma(closes[: index + 1], fast)
        slow_ma = _sma(closes[: index + 1], slow)
        prev_fast = _sma(closes[:index], fast)
        prev_slow = _sma(closes[:index], slow)
        if None in {fast_ma, slow_ma, prev_fast, prev_slow}:
            continue

        bullish = prev_fast <= prev_slow and fast_ma > slow_ma
        bearish = prev_fast >= prev_slow and fast_ma < slow_ma

        if position_entry is None and bullish:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and bearish:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "sma bearish cross")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# RSI Reversion strategy
# ---------------------------------------------------------------------------


def _rsi_reversion_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    buy_level: float = 30,
    sell_level: float = 55,
) -> list[BacktestTrade]:
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(15, len(closes)):
        rsi = _rsi(closes[: index + 1], 14)
        if rsi is None:
            continue

        if position_entry is None and rsi < buy_level:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and rsi > sell_level:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "rsi mean reversion exit")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Momentum strategy
# ---------------------------------------------------------------------------


def _momentum_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
) -> list[BacktestTrade]:
    """Buy when RSI > 50 and MACD > signal; sell when both bearish."""
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(35, len(closes)):
        rsi = _rsi(closes[: index + 1], 14)
        macd, signal = _macd(closes[: index + 1])
        if rsi is None or macd is None or signal is None:
            continue

        rsi_bull = rsi > 50
        macd_bull = macd > signal

        if position_entry is None and rsi_bull and macd_bull:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and not rsi_bull and not macd_bull:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "momentum exit")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Bollinger Band strategy
# ---------------------------------------------------------------------------


def _bollinger_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    period: int = 20,
    num_std: float = 2.0,
) -> list[BacktestTrade]:
    """Buy when price touches lower band; sell when price touches upper band."""
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(period, len(closes)):
        window = closes[index - period + 1 : index + 1]
        sma = sum(window) / period
        std = _std(window)
        upper = sma + num_std * std
        lower = sma - num_std * std

        if position_entry is None and closes[index] <= lower:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and closes[index] >= upper:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "bollinger upper exit")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Multi-factor strategy
# ---------------------------------------------------------------------------


def _multi_factor_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
) -> list[BacktestTrade]:
    """Buy when SMA bullish + RSI < 45 + MACD bullish; sell when SMA bearish or RSI > 70."""
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(35, len(closes)):
        fast_ma = _sma(closes[: index + 1], 10)
        slow_ma = _sma(closes[: index + 1], 30)
        prev_fast = _sma(closes[:index], 10)
        prev_slow = _sma(closes[:index], 30)
        rsi = _rsi(closes[: index + 1], 14)
        macd, signal = _macd(closes[: index + 1])
        if None in {fast_ma, slow_ma, prev_fast, prev_slow, rsi, macd, signal}:
            continue

        sma_bull = fast_ma > slow_ma
        sma_bear = fast_ma < slow_ma
        rsi_buy = rsi < 45
        macd_bull = macd > signal

        if position_entry is None and sma_bull and rsi_buy and macd_bull:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and (sma_bear or rsi > 70):
            entry_idx, entry_price, qty = position_entry
            reason = "sma bearish" if sma_bear else "rsi overbought"
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, f"multi-factor exit ({reason})")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# MACD Divergence strategy
# ---------------------------------------------------------------------------


def _macd_divergence_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
) -> list[BacktestTrade]:
    """Buy when MACD histogram turns positive, sell when negative."""
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(35, len(closes)):
        macd, signal = _macd(closes[: index + 1])
        prev_macd, prev_signal = _macd(closes[:index])
        if None in {macd, signal, prev_macd, prev_signal}:
            continue

        histogram = macd - signal
        prev_histogram = prev_macd - prev_signal

        # Buy: histogram crosses above zero
        bullish = prev_histogram <= 0 and histogram > 0 and macd > 0
        # Sell: histogram crosses below zero
        bearish = prev_histogram >= 0 and histogram < 0 and macd < 0

        if position_entry is None and bullish:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and bearish:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "MACD histogram negative")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Volume Breakout strategy
# ---------------------------------------------------------------------------


def _volume_breakout_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    volume_mult: float = 2.0,
    lookback: int = 20,
) -> list[BacktestTrade]:
    """Buy on volume spike + price breakout above resistance, sell on volume spike + breakdown below support."""
    closes = [float(c.close) for c in candles]
    volumes = [float(c.volume) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(lookback, len(closes)):
        avg_vol = sum(volumes[index - lookback : index]) / lookback
        vol_ratio = volumes[index] / avg_vol if avg_vol > 0 else 0
        is_spike = vol_ratio > volume_mult

        # Simple resistance/support: highest/lowest in lookback
        resistance = max(closes[index - lookback : index])
        support = min(closes[index - lookback : index])

        if position_entry is None and is_spike and closes[index] > resistance:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and is_spike and closes[index] < support:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "volume breakdown")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Z-Score Mean Reversion strategy
# ---------------------------------------------------------------------------


def _zscore_trades(
    candles: list[Candle],
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    lookback: int = 30,
    threshold: float = 2.0,
) -> list[BacktestTrade]:
    """Buy when Z-score < -threshold, sell when Z-score > threshold."""
    closes = [float(c.close) for c in candles]
    position_entry: tuple[int, float, float] | None = None
    trades: list[BacktestTrade] = []
    equity = initial_equity
    win_rate, avg_win, avg_loss = _running_stats(trades)

    for index in range(lookback, len(closes)):
        window = closes[index - lookback : index]
        mean = sum(window) / lookback
        variance = sum((x - mean) ** 2 for x in window) / lookback
        std = variance ** 0.5

        if std == 0:
            continue

        z_score = (closes[index] - mean) / std

        if position_entry is None and z_score < -threshold:
            qty = sizer.size(equity, win_rate, avg_win, avg_loss, closes[index])
            if qty > 0:
                position_entry = (index, closes[index], qty)
        elif position_entry is not None and z_score > threshold:
            entry_idx, entry_price, qty = position_entry
            trade = _make_trade(entry_idx, index, entry_price, closes[index], qty, fee_profile, "Z-score overbought")
            trades.append(trade)
            equity += trade.pnl_absolute
            position_entry = None
            win_rate, avg_win, avg_loss = _running_stats(trades)

    if position_entry is not None:
        entry_idx, entry_price, qty = position_entry
        trade = _make_trade(entry_idx, len(closes) - 1, entry_price, closes[-1], qty, fee_profile, "end of test")
        trades.append(trade)
    return trades


# ---------------------------------------------------------------------------
# Trade construction with fees/slippage
# ---------------------------------------------------------------------------


def _make_trade(
    entry_index: int,
    exit_index: int,
    entry_price: float,
    exit_price: float,
    quantity: float,
    fee_profile: FeeProfile,
    reason: str,
) -> BacktestTrade:
    # Apply slippage: buy at slightly higher, sell at slightly lower
    slipped_entry = entry_price * (1 + fee_profile.slippage_pct / 100)
    slipped_exit = exit_price * (1 - fee_profile.slippage_pct / 100)

    # Apply spread on both sides
    spread_cost = entry_price * fee_profile.spread_pct / 100

    gross_pnl = (slipped_exit - slipped_entry) * quantity
    entry_fee = slipped_entry * quantity * fee_profile.fee_pct / 100
    exit_fee = slipped_exit * quantity * fee_profile.fee_pct / 100
    spread_total = spread_cost * quantity
    total_fees = entry_fee + exit_fee + spread_total
    net_pnl = gross_pnl - total_fees

    notional = slipped_entry * quantity
    pnl_pct = (net_pnl / notional * 100) if notional > 0 else 0.0

    return BacktestTrade(
        entry_index=entry_index,
        exit_index=exit_index,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        pnl_percent=pnl_pct,
        pnl_absolute=net_pnl,
        fees_paid=total_fees,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Walk-forward split
# ---------------------------------------------------------------------------


def _run_walk_forward(
    symbol: str,
    candles: list[Candle],
    strategy: str,
    interval: str,
    fee_profile: FeeProfile,
    sizer: PositionSizer,
    initial_equity: float,
    include_mc: bool,
    mc_sims: int,
    asset_class: str,
    strategy_params: dict[str, Any] | None = None,
) -> BacktestResult:
    split = int(len(candles) * 0.7)
    in_sample_candles = candles[:split]
    out_sample_candles = candles[split:]

    in_trades = _run_strategy(strategy, in_sample_candles, fee_profile, sizer, initial_equity, strategy_params)
    in_result = _build_result(symbol, strategy, interval, in_sample_candles, in_trades, fee_profile, sizer, initial_equity)

    out_trades = _run_strategy(strategy, out_sample_candles, fee_profile, sizer, initial_equity, strategy_params)
    out_result = _build_result(symbol, strategy, interval, out_sample_candles, out_trades, fee_profile, sizer, initial_equity)

    overfit = 0.0
    if in_result.total_return_percent != 0:
        overfit = 1 - (out_result.total_return_percent / in_result.total_return_percent)

    wf = WalkForwardResult(in_sample=in_result, out_of_sample=out_result, overfit_ratio=overfit)

    # Build combined result using all candles
    all_trades = _run_strategy(strategy, candles, fee_profile, sizer, initial_equity, strategy_params)
    result = _build_result(symbol, strategy, interval, candles, all_trades, fee_profile, sizer, initial_equity)
    result = _replace_walk_forward(result, wf)

    if include_mc and all_trades:
        mc = _monte_carlo(all_trades, initial_equity, mc_sims)
        result = _replace_monte_carlo(result, mc)

    return result


# ---------------------------------------------------------------------------
# Monte Carlo simulation
# ---------------------------------------------------------------------------


def _monte_carlo(
    trades: list[BacktestTrade],
    initial_equity: float,
    simulations: int,
    seed: int | None = None,
) -> MonteCarloResult:
    trade_returns = [trade.pnl_percent / 100.0 for trade in trades]
    if not trade_returns or initial_equity <= 0:
        return MonteCarloResult(simulations, 0, 0, 0, 0, 0, 0, 0)

    rng = random.Random(seed)
    final_equities: list[float] = []
    for _ in range(simulations):
        sampled_returns = rng.choices(trade_returns, k=len(trade_returns))
        equity = initial_equity
        for trade_return in sampled_returns:
            equity = max(0.0, equity * (1.0 + trade_return))
        final_equities.append(equity)

    returns = [(e - initial_equity) / initial_equity * 100 for e in final_equities]
    returns.sort()

    p5 = returns[int(len(returns) * 0.05)]
    p50 = returns[int(len(returns) * 0.50)]
    p95 = returns[int(len(returns) * 0.95)]
    mean_ret = sum(returns) / len(returns)
    std_ret = _std(returns)

    return MonteCarloResult(
        simulations=simulations,
        percentile_5=p5,
        percentile_50=p50,
        percentile_95=p95,
        mean_return=mean_ret,
        std_return=std_ret,
        worst_case=returns[0],
        best_case=returns[-1],
    )


# ---------------------------------------------------------------------------
# Equity curve and metrics
# ---------------------------------------------------------------------------


def _equity_curve(candles: list[Candle], trades: list[BacktestTrade], initial_equity: float) -> list[float]:
    equity = initial_equity
    curve = [equity]
    trade_by_exit: dict[int, BacktestTrade] = {}
    for t in trades:
        trade_by_exit[t.exit_index] = t
    for index in range(1, len(candles)):
        if index in trade_by_exit:
            equity += trade_by_exit[index].pnl_absolute
        curve.append(equity)
    return curve


def _max_drawdown(equity_curve: list[float], initial_equity: float) -> float:
    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        dd = ((value / peak) - 1.0) * 100 if peak > 0 else 0
        max_dd = min(max_dd, dd)
    return abs(max_dd)


def _daily_returns(equity_curve: list[float]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    return [
        (equity_curve[i] / equity_curve[i - 1]) - 1.0
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]


def _sharpe_ratio(daily_returns: list[float], risk_free_rate: float = 0.05 / 252) -> float:
    if len(daily_returns) < 2:
        return 0.0
    excess = [r - risk_free_rate for r in daily_returns]
    mean = sum(excess) / len(excess)
    std = _std(excess)
    if std <= 0:
        return 0.0
    return (mean / std) * sqrt(252)


def _sortino_ratio(daily_returns: list[float], risk_free_rate: float = 0.05 / 252) -> float:
    if len(daily_returns) < 2:
        return 0.0
    excess = [r - risk_free_rate for r in daily_returns]
    mean = sum(excess) / len(excess)
    downside = [min(r, 0) ** 2 for r in excess]
    downside_dev = sqrt(sum(downside) / len(downside)) if downside else 0
    if downside_dev <= 0:
        return 0.0
    return (mean / downside_dev) * sqrt(252)


def _calmar_ratio(total_return_pct: float, max_drawdown_pct: float) -> float:
    if max_drawdown_pct <= 0:
        return 0.0
    return total_return_pct / max_drawdown_pct


def _profit_factor(wins: list[BacktestTrade], losses: list[BacktestTrade]) -> float:
    gross_profit = sum(t.pnl_absolute for t in wins)
    gross_loss = abs(sum(t.pnl_absolute for t in losses))
    if gross_loss <= 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _expectancy(win_rate: float, avg_win: float, avg_loss: float) -> float:
    wr = win_rate / 100
    return wr * avg_win + (1 - wr) * avg_loss


def _streaks(trades: list[BacktestTrade]) -> tuple[int, int]:
    if not trades:
        return 0, 0
    max_win = max_loss = 0
    cur_win = cur_loss = 0
    for t in trades:
        if t.pnl_absolute > 0:
            cur_win += 1
            cur_loss = 0
            max_win = max(max_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            max_loss = max(max_loss, cur_loss)
    return max_win, max_loss


def _running_stats(trades: list[BacktestTrade]) -> tuple[float, float, float]:
    if not trades:
        return 50.0, 0.0, 0.0
    wins = [t for t in trades if t.pnl_absolute > 0]
    losses = [t for t in trades if t.pnl_absolute <= 0]
    wr = len(wins) / len(trades) * 100
    aw = _avg([t.pnl_percent for t in wins]) if wins else 0.0
    al = _avg([t.pnl_percent for t in losses]) if losses else 0.0
    return wr, aw, al


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exposure(candles: list[Candle], trades: list[BacktestTrade]) -> float:
    if not candles:
        return 0.0
    bars = sum(max(0, t.exit_index - t.entry_index) for t in trades)
    return min(100.0, (bars / len(candles)) * 100)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return sqrt(variance)


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _rsi(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for prev, cur in zip(values[-window - 1 : -1], values[-window:], strict=False):
        delta = cur - prev
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(values: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> tuple[float | None, float | None]:
    if len(values) < slow + signal_period:
        return None, None
    fast_ema = _ema(values, fast)
    slow_ema = _ema(values, slow)
    if fast_ema is None or slow_ema is None:
        return None, None
    macd_line = fast_ema - slow_ema
    # Simplified signal: use SMA of recent MACD-like values
    macd_values: list[float] = []
    for i in range(slow, len(values)):
        fe = _ema(values[:i + 1], fast)
        se = _ema(values[:i + 1], slow)
        if fe is not None and se is not None:
            macd_values.append(fe - se)
    if len(macd_values) < signal_period:
        return macd_line, None
    signal_line = sum(macd_values[-signal_period:]) / signal_period
    return macd_line, signal_line


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for val in values[period:]:
        ema = (val - ema) * multiplier + ema
    return ema


def _result_notes(trades: list[BacktestTrade], total_return: float, max_drawdown: float, fee_profile: FeeProfile) -> tuple[str, ...]:
    notes = [
        f"Fees: {fee_profile.fee_pct:.2f}%, slippage: {fee_profile.slippage_pct:.2f}%, spread: {fee_profile.spread_pct:.2f}%.",
        "Backtest is educational. Past performance does not guarantee future results.",
    ]
    if not trades:
        notes.append("No trades were generated by the selected strategy.")
    if max_drawdown > abs(total_return) and trades:
        notes.append("Drawdown is large relative to return; treat the result as fragile.")
    return tuple(notes)


def _replace_monte_carlo(result: BacktestResult, mc: MonteCarloResult) -> BacktestResult:
    return BacktestResult(
        symbol=result.symbol, strategy=result.strategy, interval=result.interval,
        candles=result.candles, trades=result.trades,
        total_return_percent=result.total_return_percent, total_return_absolute=result.total_return_absolute,
        win_rate=result.win_rate, max_drawdown_percent=result.max_drawdown_percent,
        exposure_percent=result.exposure_percent, sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio, calmar_ratio=result.calmar_ratio,
        profit_factor=result.profit_factor, expectancy=result.expectancy,
        avg_win=result.avg_win, avg_loss=result.avg_loss,
        largest_win=result.largest_win, largest_loss=result.largest_loss,
        consecutive_wins=result.consecutive_wins, consecutive_losses=result.consecutive_losses,
        total_fees=result.total_fees, total_trades=result.total_trades,
        winning_trades=result.winning_trades, losing_trades=result.losing_trades,
        notes=result.notes, equity_curve=result.equity_curve,
        monte_carlo=mc, walk_forward=result.walk_forward,
        fee_profile_used=result.fee_profile_used, position_sizer_used=result.position_sizer_used,
        initial_equity=result.initial_equity,
    )


def _replace_walk_forward(result: BacktestResult, wf: WalkForwardResult) -> BacktestResult:
    return BacktestResult(
        symbol=result.symbol, strategy=result.strategy, interval=result.interval,
        candles=result.candles, trades=result.trades,
        total_return_percent=result.total_return_percent, total_return_absolute=result.total_return_absolute,
        win_rate=result.win_rate, max_drawdown_percent=result.max_drawdown_percent,
        exposure_percent=result.exposure_percent, sharpe_ratio=result.sharpe_ratio,
        sortino_ratio=result.sortino_ratio, calmar_ratio=result.calmar_ratio,
        profit_factor=result.profit_factor, expectancy=result.expectancy,
        avg_win=result.avg_win, avg_loss=result.avg_loss,
        largest_win=result.largest_win, largest_loss=result.largest_loss,
        consecutive_wins=result.consecutive_wins, consecutive_losses=result.consecutive_losses,
        total_fees=result.total_fees, total_trades=result.total_trades,
        winning_trades=result.winning_trades, losing_trades=result.losing_trades,
        notes=result.notes, equity_curve=result.equity_curve,
        monte_carlo=result.monte_carlo, walk_forward=wf,
        fee_profile_used=result.fee_profile_used, position_sizer_used=result.position_sizer_used,
        initial_equity=result.initial_equity,
    )
