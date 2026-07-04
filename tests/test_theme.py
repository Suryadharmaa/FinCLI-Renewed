"""Tests for theme system."""

from fincli.app.tui.theme import APP_CSS, build_theme_css
from fincli.app.tui.themes import DEFAULT_THEME, THEMES, get_theme, list_themes


def test_themes_has_default() -> None:
    assert DEFAULT_THEME in THEMES


def test_get_theme_valid() -> None:
    t = get_theme("midnight")
    assert t.name == "midnight"
    assert t.bg.startswith("#")
    assert t.accent.startswith("#")


def test_get_theme_fallback() -> None:
    t = get_theme("nonexistent")
    assert t.name == DEFAULT_THEME


def test_list_themes_count() -> None:
    themes = list_themes()
    assert len(themes) >= 7
    names = [t.name for t in themes]
    assert "midnight" in names
    assert "ocean" in names
    assert "gradient" in names


def test_theme_preset_frozen() -> None:
    t = get_theme("midnight")
    try:
        t.bg = "#fff"  # type: ignore[misc]
        raise AssertionError("Should be frozen")
    except AttributeError:
        pass


def test_build_theme_css_returns_string() -> None:
    css = build_theme_css(get_theme("ocean"))
    assert isinstance(css, str)
    assert "#0a1628" in css  # ocean bg
    assert "#2dd4bf" in css  # ocean accent


def test_build_theme_css_gradient() -> None:
    css = build_theme_css(get_theme("gradient"))
    assert "linear-gradient" in css
    assert "#0f0c29" in css


def test_build_theme_css_no_gradient() -> None:
    css = build_theme_css(get_theme("midnight"))
    assert "linear-gradient" not in css


def test_app_css_not_empty() -> None:
    assert len(APP_CSS) > 100
    assert "Screen" in APP_CSS


def test_all_themes_have_required_fields() -> None:
    for name, theme in THEMES.items():
        assert theme.name == name
        assert theme.bg.startswith("#"), f"{name} bg missing"
        assert theme.text.startswith("#"), f"{name} text missing"
        assert theme.accent.startswith("#"), f"{name} accent missing"
        assert theme.positive.startswith("#"), f"{name} positive missing"
        assert theme.negative.startswith("#"), f"{name} negative missing"
