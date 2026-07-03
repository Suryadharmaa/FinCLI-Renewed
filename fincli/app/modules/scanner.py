"""Watchlist and market scanner with technical filters."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.utils.errors import CommandError

if TYPE_CHECKING:
    from fincli.app.providers.market.base import BaseMarketProvider

# ---------------------------------------------------------------------------
# Predefined stock universes
# ---------------------------------------------------------------------------

UNIVERSE_SP500_TOP: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA",
    "UNH", "JPM", "V", "JNJ", "WMT", "PG", "MA", "HD", "ABBV", "MRK",
    "PEP", "COST", "AVGO", "KO", "CVX", "LLY", "TMO", "MCD", "CSCO",
    "ACN", "ABT", "DHR", "WFC", "TXN", "NEE", "LIN", "PM", "UPS", "RTX",
    "LOW", "ORCL", "HON", "AMGN", "INTC", "UNP", "IBM", "GE", "CAT",
    "BA", "GS", "ELV", "SBUX", "MMM",
)

UNIVERSE_NASDAQ_TOP: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
    "COST", "NFLX", "AMD", "PEP", "ADBE", "CSCO", "INTC", "CMCSA",
    "QCOM", "TXN", "AMGN", "HON", "INTU", "BKNG", "ISRG", "MDLZ",
    "ADI", "LRCX", "REGN", "VRTX", "GILD", "FI", "KLAC",
    "MELI", "SNPS", "CDNS", "MRVL", "ORLY", "CSX", "ADP", "NXPI",
    "WDAY", "FTNT", "CHTR", "MNST", "PAYX", "PCAR", "VRSK", "EXC",
    "XEL", "DLTR",
)

UNIVERSE_CRYPTO: tuple[str, ...] = (
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD",
    "ADA-USD", "DOGE-USD", "AVAX-USD", "DOT-USD", "MATIC-USD",
    "LINK-USD", "UNI-USD", "ATOM-USD", "LTC-USD", "ETC-USD",
    "FIL-USD", "APT-USD", "ARB-USD", "OP-USD", "NEAR-USD",
)

UNIVERSE_FOREX: tuple[str, ...] = (
    "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X",
    "USDCHF=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X",
)

UNIVERSE_COMMODITIES: tuple[str, ...] = (
    "GC=F", "SI=F", "CL=F", "BZ=F", "NG=F",
    "HG=F", "PL=F", "PA=F", "ZW=F", "ZC=F",
)

UNIVERSES: dict[str, tuple[str, ...]] = {
    "sp500": UNIVERSE_SP500_TOP,
    "nasdaq": UNIVERSE_NASDAQ_TOP,
    "crypto": UNIVERSE_CRYPTO,
    "forex": UNIVERSE_FOREX,
    "commodities": UNIVERSE_COMMODITIES,
}


# ---------------------------------------------------------------------------
# Scan result
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Scanning engine
# ---------------------------------------------------------------------------


async def scan_symbols(
    symbols: list[str],
    provider: BaseMarketProvider,
    filter_expression: str = "",
    interval: str = "1d",
    batch_size: int = 25,
) -> tuple[list[ScanResult], list[str]]:
    """Scan symbols in bounded async batches.

    Returns:
        Tuple of (matched results, error messages for failed symbols).
    """
    results: list[ScanResult] = []
    errors: list[str] = []
    for index in range(0, len(symbols), batch_size):
        batch = symbols[index : index + batch_size]
        scanned = await asyncio.gather(
            *[_scan_symbol(symbol, provider, filter_expression, interval) for symbol in batch],
            return_exceptions=True,
        )
        for item in scanned:
            if isinstance(item, ScanResult) and item.matched:
                results.append(item)
            elif isinstance(item, Exception):
                errors.append(str(item))
    return results, errors


async def scan_universe(
    universe: str,
    provider: BaseMarketProvider,
    filter_expression: str = "",
    interval: str = "1d",
    batch_size: int = 25,
    limit: int = 50,
) -> tuple[list[ScanResult], list[str]]:
    """Scan a predefined universe with limit.

    Returns:
        Tuple of (matched results, error messages for failed symbols).
    """
    symbols = list(UNIVERSES.get(universe.lower(), ()))
    if not symbols:
        raise CommandError(f"Unknown universe: {universe}. Use: {', '.join(UNIVERSES.keys())}")
    symbols = symbols[:limit]
    return await scan_symbols(symbols, provider, filter_expression, interval, batch_size)


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


# ---------------------------------------------------------------------------
# Filter expression parser
# ---------------------------------------------------------------------------


def _matches_filter(summary: TechnicalSummary, expression: str) -> tuple[bool, str]:
    return matches_filter_expression(summary, expression)


def matches_filter_expression(summary: TechnicalSummary, expression: str) -> tuple[bool, str]:
    """Evaluate a scan expression language.

    Supported terms:
        trend=<bias>       — bullish, bearish, neutral
        rsi<N, rsi>N       — RSI threshold
        sma_cross          — fast SMA > slow SMA (golden cross)
        sma_death          — fast SMA < slow SMA (death cross)
        above_support      — price near support
        below_resistance   — price near resistance

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

    if expr == "sma_cross":
        crossed = (
            summary.sma_fast is not None
            and summary.sma_slow is not None
            and summary.sma_fast > summary.sma_slow
        )
        return crossed, f"sma_fast={_fmt(summary.sma_fast)} {'>' if crossed else '<='} sma_slow={_fmt(summary.sma_slow)}"

    if expr == "sma_death":
        crossed = (
            summary.sma_fast is not None
            and summary.sma_slow is not None
            and summary.sma_fast < summary.sma_slow
        )
        return crossed, f"sma_fast={_fmt(summary.sma_fast)} {'<' if crossed else '>='} sma_slow={_fmt(summary.sma_slow)}"

    if expr in ("above_support", "near_support"):
        if summary.support is None:
            return False, "support=N/A"
        diff_pct = abs(summary.latest_close - summary.support) / summary.support * 100
        return diff_pct < 3.0, f"price={summary.latest_close:.2f} support={summary.support:.2f} ({diff_pct:.1f}%)"

    if expr in ("below_resistance", "near_resistance"):
        if summary.resistance is None:
            return False, "resistance=N/A"
        diff_pct = abs(summary.resistance - summary.latest_close) / summary.resistance * 100
        return diff_pct < 3.0, f"price={summary.latest_close:.2f} resistance={summary.resistance:.2f} ({diff_pct:.1f}%)"

    raise CommandError(
        f"Unknown scan filter: {expr}",
        "Use: trend=bullish, rsi<30, rsi>70, sma_cross, sma_death, above_support, below_resistance. Combine with and/or.",
    )


def _parse_threshold(expression: str, prefix: str) -> float:
    try:
        return float(expression.replace(prefix, "", 1).strip())
    except ValueError:
        raise CommandError(f"Invalid threshold in '{expression}'. Must be a number.") from None


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.2f}"
