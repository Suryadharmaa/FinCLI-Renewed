from __future__ import annotations

from fincli.app.providers.reliability import STATUS_OK, STATUS_PARTIAL_DATA, STATUS_UNAVAILABLE
from fincli.app.research.engine import _research_signal
from fincli.app.services.data_quality import DataQualityReport
from fincli.app.services.data_trust import build_data_trust_gate


def test_data_trust_gate_blocks_directional_signal_when_ohlcv_missing() -> None:
    quality = DataQualityReport(
        score=25,
        quote="ok",
        ohlcv="missing",
        news="missing",
        fundamentals="missing",
        provider="test",
        tier="weak",
        freshness="delayed",
        reliability_status=STATUS_UNAVAILABLE,
        missing_fields=("ohlcv", "news", "fundamentals"),
        label="weak",
    )

    gate = build_data_trust_gate(quality)

    assert gate.level == "blocked"
    assert gate.action == "no_directional_signal"
    assert gate.confidence_cap == 20
    assert "caution only" in gate.max_signal_strength


def test_data_trust_gate_limits_partial_data() -> None:
    quality = DataQualityReport(
        score=60,
        quote="ok",
        ohlcv="usable (30 candles)",
        news="missing",
        fundamentals="missing",
        provider="test",
        tier="partial",
        freshness="delayed",
        reliability_status=STATUS_PARTIAL_DATA,
        missing_fields=("news", "fundamentals"),
        label="partial",
    )

    gate = build_data_trust_gate(quality)

    assert gate.level == "limited"
    assert gate.confidence_cap == 45
    assert "wait-for-confirmation" in gate.max_signal_strength


def test_data_trust_gate_allows_strong_data() -> None:
    quality = DataQualityReport(
        score=95,
        quote="ok",
        ohlcv="strong (180 candles)",
        news="3 item(s)",
        fundamentals="ok",
        provider="test",
        tier="strong",
        freshness="realtime",
        reliability_status=STATUS_OK,
        missing_fields=(),
        label="strong",
    )

    gate = build_data_trust_gate(quality)

    assert gate.level == "strong"
    assert gate.confidence_cap == 80
    assert "candidate buy/sell" in gate.max_signal_strength


def test_research_signal_respects_low_trust_even_if_market_bias_is_directional() -> None:
    class Technical:
        trend_bias = "bullish"
        rsi = 50

    class Structure:
        trend = "bullish"

    class Quality:
        reliability_status = STATUS_OK

    class Overview:
        technical = Technical()
        structure = Structure()
        data_quality = Quality()

    signal = _research_signal(Overview(), trust_level="limited")

    assert signal.startswith("CAUTION")
