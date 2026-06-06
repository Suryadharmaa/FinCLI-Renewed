from datetime import datetime
from pathlib import Path

from fincli.app.analysis.indicators import summarize_technical_indicators
from fincli.app.analysis.market_structure import analyze_market_structure
from fincli.app.analysis.technical_debate import format_debate, run_technical_debate
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
            volume=1_000 + (index * 25),
        )
        for index, close in enumerate(closes)
    ]


def test_technical_debate_has_three_choosers_and_judge() -> None:
    candles = make_candles([100, 101, 102, 103, 104, 106, 108, 110, 112, 114, 116, 118, 119, 121, 123, 125, 127, 130, 132, 135])
    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)

    debate = run_technical_debate(technical, structure, candles)
    output = format_debate(debate)

    assert debate.judge_signal.label == "BEST TO BUY"
    assert "Bull Chooser" in output
    assert "Bear Chooser" in output
    assert "Caution Chooser" in output
    assert "Judge Verdict" in output


def test_technical_debate_judge_prefers_caution_when_evidence_is_conflicted() -> None:
    candles = make_candles([100, 103, 99, 104, 98, 105, 99, 106, 100, 105, 101, 104, 100, 106, 99, 107, 100, 104, 102, 103])
    technical = summarize_technical_indicators(candles)
    structure = analyze_market_structure(candles)

    debate = run_technical_debate(technical, structure, candles)

    assert debate.judge_signal.label == "CAUTION"
    assert debate.caution_case.score >= 3
    assert any("conflict" in reason.lower() or "mixed" in reason.lower() for reason in debate.judge_reasoning)


def test_technical_command_includes_debate_output(tmp_path: Path) -> None:
    class Provider:
        name = "fake"

        async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Candle]:
            return make_candles([100, 101, 102, 103, 104, 106, 108, 110, 112, 114, 116, 118, 119, 121, 123, 125, 127, 130, 132, 135])

    router = CommandRouter(
        config=ConfigManager(tmp_path / "config.json"),
        db=FinCLIDatabase(tmp_path / "fincli.db"),
        market_provider=Provider(),
    )

    result = router.route("/technical AAPL 1d")

    output = str(result.renderable)
    assert "Technical Debate:" in output
    assert "Judge Verdict: BEST TO BUY" in output
