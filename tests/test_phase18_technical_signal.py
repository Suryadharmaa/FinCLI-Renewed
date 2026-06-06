from datetime import datetime
from pathlib import Path

from fincli.app.analysis.indicators import summarize_technical_indicators
from fincli.app.analysis.market_structure import analyze_market_structure
from fincli.app.analysis.technical_signal import evaluate_technical_signal
from fincli.app.cli.router import CommandRouter
from fincli.app.providers.market.base import Candle
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase


def make_candles(closes: list[float]) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, index + 1),
            open=close - 0.5,
            high=close + 1.5,
            low=close - 1.5,
            close=close,
            volume=1_000 + (index * 20),
        )
        for index, close in enumerate(closes)
    ]


def test_technical_signal_detects_buy_candidate() -> None:
    candles = make_candles([100, 101, 102, 103, 104, 106, 108, 110, 112, 114, 116, 118, 119, 121, 123, 125, 127, 130, 132, 135])
    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)

    signal = evaluate_technical_signal(technical, structure, candles)

    assert signal.label == "BEST TO BUY"
    assert signal.confidence in {"medium", "high"}
    assert signal.score > 0
    assert any("Trend" in reason for reason in signal.reasons)


def test_technical_signal_detects_sell_candidate() -> None:
    candles = make_candles([135, 132, 130, 127, 125, 123, 121, 119, 118, 116, 114, 112, 110, 108, 106, 104, 103, 102, 101, 100])
    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)

    signal = evaluate_technical_signal(technical, structure, candles)

    assert signal.label == "BEST TO SELL"
    assert signal.confidence in {"medium", "high"}
    assert signal.score < 0


def test_technical_signal_prefers_caution_for_conflicting_setup() -> None:
    candles = make_candles([100, 102, 101, 103, 100, 104, 99, 105, 101, 106, 100, 107, 99, 106, 100, 105, 101, 104, 102, 103])
    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)

    signal = evaluate_technical_signal(technical, structure, candles)

    assert signal.label == "CAUTION"
    assert signal.confidence in {"low", "medium"}


def test_technical_command_outputs_signal_and_reasoning(tmp_path: Path) -> None:
    class Provider:
        name = "fake"

        async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
            return make_candles([100, 101, 102, 103, 104, 106, 108, 110, 112, 114, 116, 118, 119, 121, 123, 125, 127, 130, 132, 135])

    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=Provider(),
    )

    result = router.route("/technical XAUUSD 1d")

    output = str(result.renderable)
    assert result.status == "ready"
    assert "Signal: BEST TO BUY" in output
    assert "Signal Reasoning:" in output
    assert "Signal Risk Notes:" in output
