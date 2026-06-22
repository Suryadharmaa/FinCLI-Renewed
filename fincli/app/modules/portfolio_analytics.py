"""Portfolio analytics: time-series snapshots, risk ratios, rebalancing, benchmarks (v0.8.0)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from math import sqrt

from fincli.app.storage.database import FinCLIDatabase


# ---------------------------------------------------------------------------
# Snapshot model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    total_value: float
    cost_basis: float
    unrealized_pnl: float
    realized_pnl: float
    positions_json: str
    created_at: str


# ---------------------------------------------------------------------------
# Risk ratios
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskRatios:
    sharpe: float
    sortino: float
    calmar: float
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    trading_days: int


# ---------------------------------------------------------------------------
# Rebalancing suggestion
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RebalanceSuggestion:
    symbol: str
    current_weight: float
    target_weight: float
    action: str  # trim, add
    amount: float  # dollar amount to trim/add
    reason: str


@dataclass(frozen=True, slots=True)
class RebalanceReport:
    suggestions: tuple[RebalanceSuggestion, ...]
    total_trades: int
    estimated_cost: float
    note: str


# ---------------------------------------------------------------------------
# Benchmark comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    portfolio_return: float
    benchmark_return: float
    alpha: float
    beta: float
    correlation: float
    benchmark_symbol: str
    period_days: int
    note: str


# ---------------------------------------------------------------------------
# What-if analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WhatIfResult:
    action: str
    symbol: str
    current_weight: float
    new_weight: float
    current_sharpe: float
    new_sharpe: float
    current_concentration: str
    new_concentration: str
    note: str


# ---------------------------------------------------------------------------
# Portfolio Analytics Service
# ---------------------------------------------------------------------------


class PortfolioAnalytics:
    """Portfolio analytics with time-series storage and risk calculations."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def save_snapshot(self, total_value: float, cost_basis: float, unrealized_pnl: float, realized_pnl: float, positions: dict[str, object] | None = None) -> None:
        self.db.execute(
            """INSERT INTO portfolio_snapshots (total_value, cost_basis, unrealized_pnl, realized_pnl, positions_json)
               VALUES (?, ?, ?, ?, ?)""",
            (total_value, cost_basis, unrealized_pnl, realized_pnl, json.dumps(positions or {})),
        )

    def get_snapshots(self, limit: int = 365) -> list[PortfolioSnapshot]:
        rows = self.db.query(
            "SELECT total_value, cost_basis, unrealized_pnl, realized_pnl, positions_json, created_at "
            "FROM portfolio_snapshots ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [
            PortfolioSnapshot(
                total_value=float(r["total_value"]),
                cost_basis=float(r["cost_basis"]),
                unrealized_pnl=float(r["unrealized_pnl"]),
                realized_pnl=float(r["realized_pnl"]),
                positions_json=str(r["positions_json"]),
                created_at=str(r["created_at"]),
            )
            for r in rows
        ]

    def get_latest_snapshot(self) -> PortfolioSnapshot | None:
        rows = self.db.query(
            "SELECT total_value, cost_basis, unrealized_pnl, realized_pnl, positions_json, created_at "
            "FROM portfolio_snapshots ORDER BY id DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return PortfolioSnapshot(
            total_value=float(r["total_value"]),
            cost_basis=float(r["cost_basis"]),
            unrealized_pnl=float(r["unrealized_pnl"]),
            realized_pnl=float(r["realized_pnl"]),
            positions_json=str(r["positions_json"]),
            created_at=str(r["created_at"]),
        )

    def calculate_risk_ratios(self, risk_free_rate: float = 0.05) -> RiskRatios:
        snapshots = self.get_snapshots(limit=365)
        if len(snapshots) < 2:
            return RiskRatios(0, 0, 0, 0, 0, 0, len(snapshots))

        # Reverse to chronological order
        values = [s.total_value for s in reversed(snapshots)]
        daily_returns = [(values[i] / values[i - 1]) - 1.0 for i in range(1, len(values)) if values[i - 1] > 0]

        if not daily_returns:
            return RiskRatios(0, 0, 0, 0, 0, 0, len(snapshots))

        daily_rf = risk_free_rate / 252
        excess = [r - daily_rf for r in daily_returns]
        mean_excess = sum(excess) / len(excess)
        std_ret = _std(daily_returns)

        # Sharpe (annualized)
        sharpe = (mean_excess / std_ret) * sqrt(252) if std_ret > 0 else 0.0

        # Sortino (annualized)
        downside = [min(r - daily_rf, 0) ** 2 for r in daily_returns]
        downside_dev = sqrt(sum(downside) / len(downside)) if downside else 0
        sortino = (mean_excess / downside_dev) * sqrt(252) if downside_dev > 0 else 0.0

        # Max drawdown
        peak = values[0]
        max_dd = 0.0
        for v in values:
            peak = max(peak, v)
            dd = ((v / peak) - 1.0) * 100 if peak > 0 else 0
            max_dd = min(max_dd, dd)
        max_dd = abs(max_dd)

        # Annualized return — use actual date range, not snapshot count
        total_return = (values[-1] / values[0] - 1.0) * 100 if values[0] > 0 else 0
        try:
            first_date = datetime.fromisoformat(str(snapshots[-1].created_at))
            last_date = datetime.fromisoformat(str(snapshots[0].created_at))
            actual_days = max((last_date - first_date).days, 1)
            years = actual_days / 365.25
        except (ValueError, TypeError):
            years = len(values) / 252  # fallback to old behavior
        ann_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else total_return

        # Annualized volatility
        ann_vol = std_ret * sqrt(252) * 100

        # Calmar
        calmar = ann_return / max_dd if max_dd > 0 else 0.0

        return RiskRatios(
            sharpe=sharpe,
            sortino=sortino,
            calmar=calmar,
            annualized_return=ann_return,
            annualized_volatility=ann_vol,
            max_drawdown=max_dd,
            trading_days=len(values),
        )

    def suggest_rebalance(self, positions: list[dict[str, object]], market_values: dict[str, tuple[float | None, float | None, float | None]], max_concentration_pct: float = 25.0) -> RebalanceReport:
        if not positions:
            return RebalanceReport((), 0, 0.0, "No positions to rebalance.")

        total_value = 0.0
        symbol_values: dict[str, float] = {}
        for pos in positions:
            sym = str(pos["symbol"]).upper()
            qty = float(pos["quantity"])
            current, _, _ = market_values.get(sym, (None, None, None))
            mv = qty * float(current) if current is not None else qty * float(pos["average_price"])
            symbol_values[sym] = mv
            total_value += mv

        if total_value <= 0:
            return RebalanceReport((), 0, 0.0, "No market value available.")

        # Equal-weight target
        n = len(symbol_values)
        target_weight = 100.0 / n
        # Cap at max_concentration
        target_weight = min(target_weight, max_concentration_pct)

        suggestions: list[RebalanceSuggestion] = []
        for sym, mv in sorted(symbol_values.items()):
            current_weight = mv / total_value * 100
            diff = current_weight - target_weight
            if abs(diff) > 2.0:  # threshold: 2%
                action = "trim" if diff > 0 else "add"
                amount = abs(diff) / 100 * total_value
                suggestions.append(RebalanceSuggestion(
                    symbol=sym,
                    current_weight=current_weight,
                    target_weight=target_weight,
                    action=action,
                    amount=amount,
                    reason=f"{sym} at {current_weight:.1f}% vs target {target_weight:.1f}%",
                ))

        return RebalanceReport(
            suggestions=tuple(suggestions),
            total_trades=len(suggestions),
            estimated_cost=sum(s.amount * 0.002 for s in suggestions),  # ~0.2% trading cost
            note="Rebalancing suggestions are informational, not financial advice.",
        )

    def compare_benchmark(self, benchmark_values: list[float], portfolio_values: list[float], benchmark_symbol: str) -> BenchmarkComparison:
        if len(portfolio_values) < 2 or len(benchmark_values) < 2:
            return BenchmarkComparison(0, 0, 0, 0, 0, benchmark_symbol, 0, "Insufficient data for comparison.")

        min_len = min(len(portfolio_values), len(benchmark_values))
        pv = portfolio_values[-min_len:]
        bv = benchmark_values[-min_len:]

        port_ret = [(pv[i] / pv[i - 1]) - 1.0 for i in range(1, len(pv)) if pv[i - 1] > 0]
        bench_ret = [(bv[i] / bv[i - 1]) - 1.0 for i in range(1, len(bv)) if bv[i - 1] > 0]

        if not port_ret or not bench_ret:
            return BenchmarkComparison(0, 0, 0, 0, 0, benchmark_symbol, 0, "Insufficient return data.")

        min_ret = min(len(port_ret), len(bench_ret))
        port_ret = port_ret[-min_ret:]
        bench_ret = bench_ret[-min_ret:]

        port_total = (pv[-1] / pv[0] - 1.0) * 100 if pv[0] > 0 else 0
        bench_total = (bv[-1] / bv[0] - 1.0) * 100 if bv[0] > 0 else 0

        # Beta = cov(port, bench) / var(bench)
        bench_mean = sum(bench_ret) / len(bench_ret)
        port_mean = sum(port_ret) / len(port_ret)
        cov = sum((p - port_mean) * (b - bench_mean) for p, b in zip(port_ret, bench_ret)) / len(bench_ret)
        var_bench = sum((b - bench_mean) ** 2 for b in bench_ret) / len(bench_ret)
        beta = cov / var_bench if var_bench > 0 else 0

        # Alpha (Jensen's): port_return - (risk_free + beta * (bench_return - risk_free))
        alpha = port_total - beta * bench_total

        # Correlation
        std_port = _std(port_ret)
        std_bench = _std(bench_ret)
        correlation = cov / (std_port * std_bench) if std_port > 0 and std_bench > 0 else 0

        return BenchmarkComparison(
            portfolio_return=port_total,
            benchmark_return=bench_total,
            alpha=alpha,
            beta=beta,
            correlation=correlation,
            benchmark_symbol=benchmark_symbol,
            period_days=min_len,
            note=f"Alpha {alpha:+.2f}%, beta {beta:.2f} vs {benchmark_symbol}.",
        )

    def what_if(self, action: str, symbol: str, quantity: float, price: float, current_positions: list[dict[str, object]], market_values: dict[str, tuple[float | None, float | None, float | None]]) -> WhatIfResult:
        total_value = 0.0
        symbol_values: dict[str, float] = {}
        for pos in current_positions:
            sym = str(pos["symbol"]).upper()
            qty = float(pos["quantity"])
            current, _, _ = market_values.get(sym, (None, None, None))
            mv = qty * float(current) if current is not None else qty * float(pos["average_price"])
            symbol_values[sym] = mv
            total_value += mv

        notional = quantity * price
        sym_upper = symbol.upper()

        if action == "add":
            total_value += notional
            symbol_values[sym_upper] = symbol_values.get(sym_upper, 0) + notional
        elif action in {"sell", "remove"}:
            total_value -= notional
            symbol_values[sym_upper] = max(0, symbol_values.get(sym_upper, 0) - notional)

        # Calculate new weights
        current_weight = symbol_values.get(sym_upper, 0) / total_value * 100 if total_value > 0 else 0
        old_total = total_value - notional if action == "add" else total_value + notional
        old_weight = (symbol_values.get(sym_upper, 0) - (notional if action == "add" else -notional)) / old_total * 100 if old_total > 0 else 0

        # Top concentration
        if symbol_values:
            top_sym = max(symbol_values, key=lambda k: symbol_values[k])
            top_weight = symbol_values[top_sym] / total_value * 100 if total_value > 0 else 0
            new_conc = f"{top_sym} at {top_weight:.1f}%"
        else:
            new_conc = "empty"

        # Estimate new Sharpe (simplified: assume same volatility)
        old_conc_sym = max(symbol_values, key=lambda k: symbol_values[k]) if symbol_values else "-"
        old_conc_weight = symbol_values.get(old_conc_sym, 0) / old_total * 100 if old_total > 0 else 0
        old_conc = f"{old_conc_sym} at {old_conc_weight:.1f}%"

        return WhatIfResult(
            action=action,
            symbol=sym_upper,
            current_weight=old_weight,
            new_weight=current_weight,
            current_sharpe=0,  # Would need historical data
            new_sharpe=0,
            current_concentration=old_conc,
            new_concentration=new_conc,
            note=f"{'Adding' if action == 'add' else 'Removing'} {quantity} {sym_upper} @ ${price:,.2f} changes weight from {old_weight:.1f}% to {current_weight:.1f}%.",
        )


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return sqrt(variance)
