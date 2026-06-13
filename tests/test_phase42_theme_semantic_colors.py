from __future__ import annotations

from rich.text import Text

from fincli.app.tui.theme import APP_CSS


def test_semantic_style_maps_financial_meaning_to_colors() -> None:
    from fincli.app.utils.formatting import semantic_style

    assert semantic_style("bullish trend breakout") == "bold green"
    assert semantic_style("price up positive gain") == "bold green"
    assert semantic_style("bearish breakdown sell negative") == "bold red"
    assert semantic_style("drawdown loss downside") == "bold red"
    assert semantic_style("CAUTION hold wait neutral") == "bold yellow"


def test_semantic_text_preserves_plain_text_and_applies_style() -> None:
    from fincli.app.utils.formatting import semantic_text

    value = semantic_text("BEST TO BUY")

    assert isinstance(value, Text)
    assert value.plain == "BEST TO BUY"
    assert "green" in str(value.style)


def test_theme_has_distinct_full_terminal_regions_and_semantic_classes() -> None:
    for selector in (
        "#top_strip",
        "#market_ribbon",
        "#output_header",
        "#output_frame",
        "#command_hint",
        "#command_line",
    ):
        assert selector in APP_CSS

    assert "background: #00110b" in APP_CSS
    assert ".semantic-positive" in APP_CSS
    assert ".semantic-negative" in APP_CSS
    assert ".semantic-caution" in APP_CSS
    assert "color: #22c55e" in APP_CSS
    assert "color: #ef4444" in APP_CSS
    assert "color: #facc15" in APP_CSS
