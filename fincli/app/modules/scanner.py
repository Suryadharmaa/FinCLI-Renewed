"""Watchlist scanner with simple technical filters."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re

from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.providers.market.base import BaseMarketProvider
from fincli.app.utils.errors import CommandError


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
    return matches_filter_expression(summary, expression)


def matches_filter_expression(summary: TechnicalSummary, expression: str) -> tuple[bool, str]:
    """Evaluate a small, explicit scan expression language.

    Supported terms: trend=<bias>, rsi<number, rsi>number.
    Supported operators: and, or. Comma is treated as and.
    """
    expr = expression.strip().lower()
    if not expr:
        return True, "all"

    normalized = expr.replace(",", " and ")
    or_groups = [group.strip() for group in re.split(r"\s+or\s+", normalized) if group.strip()]
    group_results: list[tuple[bool, str]] = []
    for group in or_groups:
        terms = [term.strip() for term in re.split(r"\s+and\s+|\s+", group) if term.strip()]
        evaluations = [_matches_single_filter(summary, term) for term in terms]
        group_results.append((all(item[0] for item in evaluations), "; ".join(item[1] for item in evaluations)))

    matched = any(item[0] for item in group_results)
    return matched, " OR ".join(item[1] for item in group_results)


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

    raise CommandError(
        f"Filter scan tidak dikenal: {expr}",
        "Gunakan filter seperti trend=bullish, rsi<30, rsi>70, atau gabungkan dengan and/or.",
    )


def _parse_threshold(expression: str, prefix: str) -> float:
    try:
        return float(expression.replace(prefix, "", 1).strip())
    except ValueError:
        return 0.0


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"
