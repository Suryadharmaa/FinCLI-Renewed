"""Phase 62: Claude-CLI style working animation helpers."""

from __future__ import annotations

from rich.console import Console

from fincli.app.cli.commands import CommandSpec
from fincli.app.tui.components import (
    GLYPHS,
    CockpitState,
    cockpit_header_text,
    command_palette_table,
    spinner_frame,
    working_verb,
)


def test_working_verb_maps_known_commands() -> None:
    assert working_verb("/research AAPL --deep") == "Researching"
    assert working_verb("/news MSFT") == "Fetching news"
    assert working_verb("/analyze XAUUSD") == "Analyzing risk"
    assert working_verb("/technical AAPL") == "Analyzing risk"
    assert working_verb("/ai what is the trend") == "Streaming AI"


def test_working_verb_defaults_to_working() -> None:
    assert working_verb("/somethingunknown") == "Working"
    assert working_verb("") == "Working"
    assert working_verb("   ") == "Working"


def test_spinner_frame_contains_verb_elapsed_and_interrupt_hint() -> None:
    frame = spinner_frame("Researching", 0, 4)
    assert "Researching" in frame
    assert "(4s" in frame
    assert "esc to interrupt" in frame
    assert "â" not in frame
    assert "Â" not in frame


def test_spinner_frame_cycles_glyphs_across_frames() -> None:
    rendered = [spinner_frame("Working", index, 0) for index in range(len(GLYPHS))]
    # Each frame within one cycle uses a distinct glyph.
    used = {GLYPHS[i] for i in range(len(GLYPHS))}
    assert all(any(glyph in frame for glyph in used) for frame in rendered)
    assert rendered[0] != rendered[1]
    # Index wraps around the glyph set.
    assert spinner_frame("Working", len(GLYPHS), 0) == spinner_frame("Working", 0, 0)


def test_cockpit_header_renders_financial_status_fields() -> None:
    text = cockpit_header_text(
        CockpitState(
            version="1.8.5",
            market_provider="yfinance",
            provider_trust="Limited",
            ai_provider="openrouter",
            ai_model="openai/gpt-4o-mini",
            session_state="live",
        )
    )

    assert "FinCLI v1.8.5" in text
    assert "market" in text
    assert "yfinance" in text
    assert "trust" in text
    assert "Limited" in text
    assert "openrouter/openai/gpt-4o-mini" in text
    assert "F1 keys" in text


def test_command_palette_table_groups_commands_and_highlights_first_match() -> None:
    table = command_palette_table(
        [
            CommandSpec("/research", "Research an instrument.", "/research AAPL", "Research"),
            CommandSpec("/market", "Show market overview.", "/market AAPL", "Market"),
        ]
    )

    console = Console(record=True, width=140, force_terminal=False)
    console.print(table)
    rendered = console.export_text()
    assert "Research" in rendered
    assert "/research" in rendered
    assert "/market" in rendered
    assert "> /research" in rendered
