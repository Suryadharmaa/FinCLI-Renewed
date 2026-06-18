"""Phase 62: Claude-CLI style working animation helpers."""

from __future__ import annotations

from fincli.app.tui.components import GLYPHS, spinner_frame, working_verb


def test_working_verb_maps_known_commands() -> None:
    assert working_verb("/research AAPL --deep") == "Researching"
    assert working_verb("/news MSFT") == "Fetching news"
    assert working_verb("/analyze XAUUSD") == "Analyzing"
    assert working_verb("/technical AAPL") == "Analyzing"
    assert working_verb("/ai what is the trend") == "Thinking"


def test_working_verb_defaults_to_working() -> None:
    assert working_verb("/somethingunknown") == "Working"
    assert working_verb("") == "Working"
    assert working_verb("   ") == "Working"


def test_spinner_frame_contains_verb_elapsed_and_interrupt_hint() -> None:
    frame = spinner_frame("Researching", 0, 4)
    assert "Researching" in frame
    assert "(4s" in frame
    assert "esc to interrupt" in frame


def test_spinner_frame_cycles_glyphs_across_frames() -> None:
    rendered = [spinner_frame("Working", index, 0) for index in range(len(GLYPHS))]
    # Each frame within one cycle uses a distinct glyph.
    used = {GLYPHS[i] for i in range(len(GLYPHS))}
    assert all(any(glyph in frame for glyph in used) for frame in rendered)
    assert rendered[0] != rendered[1]
    # Index wraps around the glyph set.
    assert spinner_frame("Working", len(GLYPHS), 0) == spinner_frame("Working", 0, 0)
