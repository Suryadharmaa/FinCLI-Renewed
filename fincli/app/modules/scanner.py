"""Watchlist scanner with simple technical filters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.providers.market.base import BaseMarketProvider


@dataclass(frozen=True, slots=True)
class ScanResult:
    symbol: str
    latest_close: float
    rsi: float | None
    trend_bias: str
    support: float | None
    resistance: float | None
    matched: bool
    reason: str


async def scan_symbols(
    symbols: list[str],
    provider: BaseMarketProvider,
    filter_expression: str = "",
    interval: str = "1d",
    batch_size: int = 25,
) -> list[ScanResult]:
    """Scan symbols in bounded async batches."""
    results: list[ScanResult] = []
    for index in range(0, len(symbols), batch_size):
        batch = symbols[index : index + batch_size]
        scanned = await asyncio.gather(
            *[_scan_symbol(symbol, provider, filter_expression, interval) for symbol in batch],
            return_exceptions=True,
        )
        for item in scanned:
            if isinstance(item, ScanResult) and item.matched:
                results.append(item)
    return results


async def _scan_symbol(
    symbol: str,
    provider: BaseMarketProvider,
    filter_expression: str,
    interval: str,
) -> ScanResult:
    candles = await provider.history(symbol, period="6mo", interval=interval)
    summary = summarize_technical_indicators(candles)
    matched, reason = _matches_filter(summary, filter_expression)
    return ScanResult(
        symbol=symbol.upper(),
        latest_close=summary.latest_close,
        rsi=summary.rsi,
        trend_bias=summary.trend_bias,
        support=summary.support,
        resistance=summary.resistance,
        matched=matched,
        reason=reason,
    )


def _matches_filter(summary: TechnicalSummary, expression: str) -> tuple[bool, str]:
    expr = expression.strip().lower()
    if not expr:
        return True, "all"

    parts = expr.split()
    if len(parts) > 1:
        evaluations = [_matches_single_filter(summary, part) for part in parts]
        return all(item[0] for item in evaluations), "; ".join(item[1] for item in evaluations)

    return _matches_single_filter(summary, expr)


def _matches_single_filter(summary: TechnicalSummary, expr: str) -> tuple[bool, str]:
    if expr.startswith("trend="):
        expected = expr.split("=", 1)[1].strip()
        return summary.trend_bias == expected, f"trend={summary.trend_bias}"

    if expr.startswith("rsi<"):
        threshold = _parse_threshold(expr, "rsi<")
        return summary.rsi is not None and summary.rsi < threshold, f"rsi={_fmt(summary.rsi)} < {threshold:g}"

    if expr.startswith("rsi>"):
        threshold = _parse_threshold(expr, "rsi>")
        return summary.rsi is not None and summary.rsi > threshold, f"rsi={_fmt(summary.rsi)} > {threshold:g}"

    return True, f"unsupported filter treated as all: {expr}"


def _parse_threshold(expression: str, prefix: str) -> float:
    try:
        return float(expression.replace(prefix, "", 1).strip())
    except ValueError:
        return 0.0


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"
