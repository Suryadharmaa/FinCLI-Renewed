from __future__ import annotations

from fincli.app.analysis.indicators import TechnicalSummary
from fincli.app.utils.errors import CommandError


def summary(rsi: float, trend: str) -> TechnicalSummary:
    return TechnicalSummary(
        latest_close=100,
        sma_fast=99,
        sma_slow=98,
        ema_fast=99,
        rsi=rsi,
        macd=1,
        macd_signal=0.5,
        bollinger_upper=110,
        bollinger_lower=90,
        atr=2,
        support=95,
        resistance=105,
        volume_latest=1_000,
        trend_bias=trend,
    )


def test_scan_expression_supports_and_or_and_commas() -> None:
    from fincli.app.modules.scanner import matches_filter_expression

    bullish = summary(62, "bullish")
    bearish = summary(28, "bearish")

    assert matches_filter_expression(bullish, "trend=bullish and rsi>55")[0]
    assert matches_filter_expression(bearish, "trend=bullish or rsi<30")[0]
    assert matches_filter_expression(bullish, "trend=bullish,rsi>55")[0]
    assert not matches_filter_expression(bearish, "trend=bullish and rsi<30")[0]


def test_scan_expression_rejects_unknown_filter() -> None:
    from fincli.app.modules.scanner import matches_filter_expression

    try:
        matches_filter_expression(summary(50, "neutral"), "magic=1")
    except CommandError as exc:
        assert "Unknown scan filter" in str(exc)
    else:
        raise AssertionError("Expected CommandError for unsupported scan filter")
