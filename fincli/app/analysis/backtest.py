"""Lightweight rule-based backtesting for FinCLI."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.providers.market.base import Candle


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    pnl_percent: float
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    symbol: str
    strategy: str
    interval: str
    candles: int
    trades: list[BacktestTrade]
    total_return_percent: float
    win_rate: float
    max_drawdown_percent: float
    exposure_percent: float
    notes: tuple[str, ...]


def run_backtest(
    symbol: str,
    candles: list[Candle],
    strategy: str = "sma_cross",
    interval: str = "1d",
) -> BacktestResult:
    if len(candles) < 30:
        raise ValueError("Backtest needs at least 30 candles.")

    normalized = strategy.lower().strip()
    if normalized in {"sma", "sma_cross", "ma_cross"}:
        trades = _sma_cross_trades(candles)
    elif normalized in {"rsi", "rsi_reversion", "mean_reversion"}:
        trades = _rsi_reversion_trades(candles)
    else:
        raise ValueError("Unknown strategy. Use sma_cross or rsi_reversion.")

    equity_curve = _equity_curve(candles, trades)
    total_return = (equity_curve[-1] - 1.0) * 100
    max_drawdown = _max_drawdown(equity_curve)
    wins = sum(1 for trade in trades if trade.pnl_percent > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0.0
    exposure = _exposure(candles, trades)
    notes = _result_notes(trades, total_return, max_drawdown)
    return BacktestResult(
        symbol=symbol.upper(),
        strategy=normalized,
        interval=interval,
        candles=len(candles),
        trades=trades,
        total_return_percent=total_return,
        win_rate=win_rate,
        max_drawdown_percent=max_drawdown,
        exposure_percent=exposure,
        notes=notes,
    )


def _sma_cross_trades(candles: list[Candle], fast: int = 10, slow: int = 30) -> list[BacktestTrade]:
    closes = [float(candle.close) for candle in candles]
    position_entry: tuple[int, float] | None = None
    trades: list[BacktestTrade] = []
    for index in range(slow, len(closes)):
        fast_ma = _sma(closes[: index + 1], fast)
        slow_ma = _sma(closes[: index + 1], slow)
        previous_fast = _sma(closes[:index], fast)
        previous_slow = _sma(closes[:index], slow)
        if None in {fast_ma, slow_ma, previous_fast, previous_slow}:
            continue
        bullish_cross = previous_fast <= previous_slow and fast_ma > slow_ma
        bearish_cross = previous_fast >= previous_slow and fast_ma < slow_ma
        if position_entry is None and bullish_cross:
            position_entry = (index, closes[index])
        elif position_entry is not None and bearish_cross:
            entry_index, entry_price = position_entry
            trades.append(_trade(entry_index, index, entry_price, closes[index], "sma bearish cross"))
            position_entry = None
    if position_entry is not None:
        entry_index, entry_price = position_entry
        trades.append(_trade(entry_index, len(closes) - 1, entry_price, closes[-1], "end of test"))
    return trades


def _rsi_reversion_trades(candles: list[Candle], buy_level: float = 30, sell_level: float = 55) -> list[BacktestTrade]:
    closes = [float(candle.close) for candle in candles]
    position_entry: tuple[int, float] | None = None
    trades: list[BacktestTrade] = []
    for index in range(15, len(closes)):
        rsi = _rsi(closes[: index + 1], 14)
        if rsi is None:
            continue
        if position_entry is None and rsi < buy_level:
            position_entry = (index, closes[index])
        elif position_entry is not None and rsi > sell_level:
            entry_index, entry_price = position_entry
            trades.append(_trade(entry_index, index, entry_price, closes[index], "rsi mean reversion exit"))
            position_entry = None
    if position_entry is not None:
        entry_index, entry_price = position_entry
        trades.append(_trade(entry_index, len(closes) - 1, entry_price, closes[-1], "end of test"))
    return trades


def _trade(entry_index: int, exit_index: int, entry_price: float, exit_price: float, reason: str) -> BacktestTrade:
    pnl = ((exit_price / entry_price) - 1.0) * 100
    return BacktestTrade(entry_index, exit_index, entry_price, exit_price, pnl, reason)


def _equity_curve(candles: list[Candle], trades: list[BacktestTrade]) -> list[float]:
    equity = 1.0
    curve = [equity]
    trade_by_exit = {trade.exit_index: trade for trade in trades}
    for index in range(1, len(candles)):
        if index in trade_by_exit:
            equity *= 1 + (trade_by_exit[index].pnl_percent / 100)
        curve.append(equity)
    return curve


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drawdown = ((value / peak) - 1.0) * 100
        max_drawdown = min(max_drawdown, drawdown)
    return abs(max_drawdown)


def _exposure(candles: list[Candle], trades: list[BacktestTrade]) -> float:
    if not candles:
        return 0.0
    bars = sum(max(0, trade.exit_index - trade.entry_index) for trade in trades)
    return min(100.0, (bars / len(candles)) * 100)


def _result_notes(trades: list[BacktestTrade], total_return: float, max_drawdown: float) -> tuple[str, ...]:
    notes = ["Backtest is educational and ignores fees, slippage, spreads, liquidity, and survivorship bias."]
    if not trades:
        notes.append("No trades were generated by the selected strategy.")
    if max_drawdown > abs(total_return) and trades:
        notes.append("Drawdown is large relative to return; treat the result as fragile.")
    return tuple(notes)


def _sma(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _rsi(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-window - 1 : -1], values[-window:]):
        delta = current - previous
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))
    average_gain = sum(gains) / window
    average_loss = sum(losses) / window
    if average_loss == 0:
        return 100.0
    rs = average_gain / average_loss
    return 100 - (100 / (1 + rs))
