"""Command capability matrix for provider/data reliability diagnostics."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandCapability:
    command: str
    needs: tuple[str, ...]
    provider_dependent: bool
    note: str


COMMAND_CAPABILITIES: tuple[CommandCapability, ...] = (
    CommandCapability("/research", ("quote", "history", "news", "fundamentals", "ai_optional"), True, "Research center combines all available data."),
    CommandCapability("/market", ("quote", "history", "news", "fundamentals"), True, "Market overview requires quote and OHLCV; news/fundamentals may be partial."),
    CommandCapability("/news", ("news",), True, "Uses news connector priority and RSS/API fallbacks."),
    CommandCapability("/technical", ("history",), True, "Needs OHLCV candles for indicators and signal scoring."),
    CommandCapability("/structure", ("history",), True, "Needs OHLCV candles for market structure."),
    CommandCapability("/mtf", ("history",), True, "Needs history across requested intervals."),
    CommandCapability("/analyze", ("quote", "history", "news", "fundamentals", "ai"), True, "AI analysis is grounded on provider data quality."),
    CommandCapability("/calendar", ("calendar",), True, "Finnhub/public calendar may degrade to schedule-only fallback."),
    CommandCapability("/quote", ("quote",), True, "Fast quote check."),
    CommandCapability("/funda", ("fundamentals",), True, "Fundamental snapshot coverage varies by symbol/provider."),
    CommandCapability("/yahoo", ("yahoo_table",), True, "Yahoo table sections are provider-specific."),
    CommandCapability("/scan", ("watchlist", "history"), True, "Scanner needs watchlist symbols and candles."),
    CommandCapability("/provider test", ("quote",), True, "Live provider smoke check for one symbol."),
    CommandCapability("/web", ("public_web",), True, "Public web search depends on connectivity/search availability."),
    CommandCapability("/ai", ("ai", "market_context_optional", "web_context_optional"), True, "Free chat can use market/web context when detected."),
    CommandCapability("/portfolio risk", ("portfolio", "quote_optional"), True, "Local positions plus quote when available."),
    CommandCapability("/journal review", ("journal", "ai"), True, "Journal analytics plus AI provider."),
)


def capability_rows() -> list[CommandCapability]:
    return list(COMMAND_CAPABILITIES)


def capability_summary() -> str:
    provider_commands = sum(1 for item in COMMAND_CAPABILITIES if item.provider_dependent)
    unique_needs = sorted({need for item in COMMAND_CAPABILITIES for need in item.needs})
    return f"{len(COMMAND_CAPABILITIES)} command profile(s); provider-dependent={provider_commands}; needs={', '.join(unique_needs)}"
