"""Unified export service for FinCLI (v0.8.0).

Supports CSV, JSON, and Markdown export for backtest results, portfolio data,
journal entries, alerts, and batch export of all data.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fincli.app.utils.errors import CommandError


# ---------------------------------------------------------------------------
# Core export
# ---------------------------------------------------------------------------


def export_rows(rows: list[dict[str, Any]], fmt: str, target: str | Path) -> Path:
    """Export rows to CSV or JSON and return the written path."""
    export_format = fmt.lower()
    path = _safe_export_path(target, {".csv", ".json"})
    path.parent.mkdir(parents=True, exist_ok=True)

    if export_format == "json":
        path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        return path

    if export_format == "csv":
        fieldnames = _fieldnames(rows)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    raise CommandError("Format export harus csv atau json.")


# ---------------------------------------------------------------------------
# Backtest export
# ---------------------------------------------------------------------------


def export_backtest(result: object, fmt: str, target: str | Path) -> Path:
    """Export backtest result to md/json/csv."""
    export_format = fmt.lower()
    path = _safe_export_path(target, {".md", ".json", ".csv"})
    path.parent.mkdir(parents=True, exist_ok=True)

    if export_format == "json":
        path.write_text(json.dumps(_backtest_payload(result), indent=2, default=str), encoding="utf-8")
        return path

    if export_format in {"md", "markdown"}:
        path.write_text(_backtest_markdown(result), encoding="utf-8")
        return path

    if export_format == "csv":
        trades = getattr(result, "trades", [])
        rows = [_trade_row(t) for t in trades]
        fieldnames = _fieldnames(rows)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    raise CommandError("Format export harus md, json, atau csv.")


def _backtest_payload(result: object) -> dict[str, Any]:
    trades = getattr(result, "trades", [])
    mc = getattr(result, "monte_carlo", None)
    wf = getattr(result, "walk_forward", None)
    return {
        "symbol": getattr(result, "symbol", ""),
        "strategy": getattr(result, "strategy", ""),
        "interval": getattr(result, "interval", ""),
        "candles": getattr(result, "candles", 0),
        "total_return_percent": getattr(result, "total_return_percent", 0),
        "total_return_absolute": getattr(result, "total_return_absolute", 0),
        "win_rate": getattr(result, "win_rate", 0),
        "max_drawdown_percent": getattr(result, "max_drawdown_percent", 0),
        "sharpe_ratio": getattr(result, "sharpe_ratio", 0),
        "sortino_ratio": getattr(result, "sortino_ratio", 0),
        "calmar_ratio": getattr(result, "calmar_ratio", 0),
        "profit_factor": getattr(result, "profit_factor", 0),
        "expectancy": getattr(result, "expectancy", 0),
        "total_fees": getattr(result, "total_fees", 0),
        "total_trades": getattr(result, "total_trades", 0),
        "winning_trades": getattr(result, "winning_trades", 0),
        "losing_trades": getattr(result, "losing_trades", 0),
        "avg_win": getattr(result, "avg_win", 0),
        "avg_loss": getattr(result, "avg_loss", 0),
        "largest_win": getattr(result, "largest_win", 0),
        "largest_loss": getattr(result, "largest_loss", 0),
        "consecutive_wins": getattr(result, "consecutive_wins", 0),
        "consecutive_losses": getattr(result, "consecutive_losses", 0),
        "fee_profile": getattr(result, "fee_profile_used", ""),
        "position_sizer": getattr(result, "position_sizer_used", ""),
        "notes": list(getattr(result, "notes", ())),
        "trades": [_trade_row(t) for t in trades],
        "monte_carlo": _mc_payload(mc) if mc else None,
        "walk_forward": _wf_payload(wf) if wf else None,
        "disclaimer": "Backtest is educational. Past performance does not guarantee future results.",
    }


def _mc_payload(mc: object) -> dict[str, Any]:
    return {
        "simulations": getattr(mc, "simulations", 0),
        "percentile_5": getattr(mc, "percentile_5", 0),
        "percentile_50": getattr(mc, "percentile_50", 0),
        "percentile_95": getattr(mc, "percentile_95", 0),
        "mean_return": getattr(mc, "mean_return", 0),
        "worst_case": getattr(mc, "worst_case", 0),
        "best_case": getattr(mc, "best_case", 0),
    }


def _wf_payload(wf: object) -> dict[str, Any]:
    return {
        "overfit_ratio": getattr(wf, "overfit_ratio", 0),
        "in_sample_return": getattr(getattr(wf, "in_sample", None), "total_return_percent", 0),
        "out_of_sample_return": getattr(getattr(wf, "out_of_sample", None), "total_return_percent", 0),
    }


def _trade_row(trade: object) -> dict[str, Any]:
    return {
        "entry_index": getattr(trade, "entry_index", 0),
        "exit_index": getattr(trade, "exit_index", 0),
        "entry_price": getattr(trade, "entry_price", 0),
        "exit_price": getattr(trade, "exit_price", 0),
        "quantity": getattr(trade, "quantity", 0),
        "pnl_percent": getattr(trade, "pnl_percent", 0),
        "pnl_absolute": getattr(trade, "pnl_absolute", 0),
        "fees_paid": getattr(trade, "fees_paid", 0),
        "reason": getattr(trade, "reason", ""),
    }


def _backtest_markdown(result: object) -> str:
    lines = [
        f"# Backtest Report: {getattr(result, 'symbol', '')}",
        "",
        f"- Strategy: {getattr(result, 'strategy', '')}",
        f"- Interval: {getattr(result, 'interval', '')}",
        f"- Candles: {getattr(result, 'candles', 0)}",
        f"- Total Return: {getattr(result, 'total_return_percent', 0):.2f}%",
        f"- Win Rate: {getattr(result, 'win_rate', 0):.1f}%",
        f"- Max Drawdown: {getattr(result, 'max_drawdown_percent', 0):.2f}%",
        f"- Sharpe: {getattr(result, 'sharpe_ratio', 0):.2f}",
        f"- Sortino: {getattr(result, 'sortino_ratio', 0):.2f}",
        f"- Calmar: {getattr(result, 'calmar_ratio', 0):.2f}",
        f"- Profit Factor: {getattr(result, 'profit_factor', 0):.2f}",
        f"- Total Fees: ${getattr(result, 'total_fees', 0):,.2f}",
        f"- Trades: {getattr(result, 'total_trades', 0)} (W:{getattr(result, 'winning_trades', 0)} / L:{getattr(result, 'losing_trades', 0)})",
        "",
        "## Notes",
        "",
    ]
    for note in getattr(result, "notes", ()):
        lines.append(f"- {note}")

    mc = getattr(result, "monte_carlo", None)
    if mc:
        lines.extend([
            "",
            "## Monte Carlo",
            "",
            f"- Simulations: {mc.simulations}",
            f"- 5th Percentile: {mc.percentile_5:.2f}%",
            f"- 50th Percentile: {mc.percentile_50:.2f}%",
            f"- 95th Percentile: {mc.percentile_95:.2f}%",
        ])

    wf = getattr(result, "walk_forward", None)
    if wf:
        lines.extend([
            "",
            "## Walk-Forward",
            "",
            f"- In-Sample Return: {wf.in_sample.total_return_percent:.2f}%",
            f"- Out-of-Sample Return: {wf.out_of_sample.total_return_percent:.2f}%",
            f"- Overfit Ratio: {wf.overfit_ratio:.2f}",
        ])

    lines.extend(["", "## Disclaimer", "", "Backtest is educational. Past performance does not guarantee future results.", ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Portfolio export
# ---------------------------------------------------------------------------


def export_portfolio(positions: list[dict[str, Any]], fmt: str, target: str | Path) -> Path:
    """Export portfolio positions to csv/json."""
    return export_rows(positions, fmt, target)


# ---------------------------------------------------------------------------
# Journal export
# ---------------------------------------------------------------------------


def export_journal(entries: list[dict[str, Any]], fmt: str, target: str | Path) -> Path:
    """Export journal entries to csv/json."""
    return export_rows(entries, fmt, target)


# ---------------------------------------------------------------------------
# Alert history export
# ---------------------------------------------------------------------------


def export_alert_history(entries: list[dict[str, Any]], fmt: str, target: str | Path) -> Path:
    """Export alert history to csv/json."""
    return export_rows(entries, fmt, target)


# ---------------------------------------------------------------------------
# Batch export
# ---------------------------------------------------------------------------


def export_all(
    output_dir: str | Path,
    portfolio: list[dict[str, Any]] | None = None,
    journal: list[dict[str, Any]] | None = None,
    alerts: list[dict[str, Any]] | None = None,
    trades: list[dict[str, Any]] | None = None,
    fmt: str = "json",
) -> list[Path]:
    """Export all data types to a directory."""
    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if portfolio:
        written.append(export_rows(portfolio, fmt, out / f"portfolio.{fmt}"))
    if journal:
        written.append(export_rows(journal, fmt, out / f"journal.{fmt}"))
    if alerts:
        written.append(export_rows(alerts, fmt, out / f"alerts.{fmt}"))
    if trades:
        written.append(export_rows(trades, fmt, out / f"paper_trades.{fmt}"))

    return written


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return []
    return list(dict.fromkeys(key for row in rows for key in row))


def _safe_export_path(target: str | Path, allowed_extensions: set[str]) -> Path:
    path = Path(target).expanduser()
    if any(part == ".." for part in path.parts):
        raise CommandError("Path export tidak boleh mengandung '..'.")
    if path.suffix.lower() not in allowed_extensions:
        raise CommandError(f"Path export harus berakhiran salah satu dari: {', '.join(sorted(allowed_extensions))}.")
    return path
