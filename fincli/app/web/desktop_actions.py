"""Desktop-safe action metadata and command builders.

The command router remains the source of truth. This module only translates
structured form input into the same slash commands used by the CLI.
"""

from __future__ import annotations

import shlex
from dataclasses import asdict, dataclass
from typing import Any

from fincli.app.cli.commands import COMMANDS, CommandSpec
from fincli.app.web.bridge import TERMINAL_ONLY_SECRET_COMMANDS
from fincli.app.web.security import command_requires_confirmation


@dataclass(frozen=True, slots=True)
class DesktopActionSpec:
    action: str
    label: str
    group: str
    description: str
    command: str
    fields: tuple[dict[str, Any], ...] = ()
    confirmation_required: bool = False
    desktop_supported: bool = True
    terminal_only_reason: str | None = None
    history_safe: bool = True

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["fields"] = list(self.fields)
        return row


def _field(
    name: str,
    label: str,
    *,
    required: bool = False,
    kind: str = "text",
    placeholder: str = "",
    sensitive: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "label": label,
        "required": required,
        "type": "password" if sensitive else kind,
        "placeholder": placeholder,
        "sensitive": sensitive,
    }


def _spec(
    action: str,
    label: str,
    group: str,
    description: str,
    command: str,
    *fields: dict[str, Any],
    confirmation: bool = False,
    history_safe: bool = True,
) -> DesktopActionSpec:
    return DesktopActionSpec(
        action,
        label,
        group,
        description,
        command,
        tuple(fields),
        confirmation or command_requires_confirmation(command),
        history_safe=history_safe,
    )


ACTION_SPECS: tuple[DesktopActionSpec, ...] = (
    _spec("ai.model", "Select AI model", "Providers", "Select an AI provider and optional model without the interactive CLI picker.", "/ai_model {provider} {model}", _field("provider", "Provider", required=True, placeholder="openrouter"), _field("model", "Model", placeholder="Default model")),
    _spec("provider.news", "Select news provider", "Providers", "Select a news provider without terminal prompts.", "/news_model use {provider}", _field("provider", "Provider", required=True, placeholder="yfinance")),
    _spec("notification.add", "Add notification", "System", "Configure Discord or Telegram without storing the credential in history.", "/notification add {type} {name} {secret} {chat_id}", _field("type", "Type", required=True, kind="select", placeholder="discord"), _field("name", "Name", required=True, placeholder="alerts"), _field("secret", "Webhook URL or bot token", required=True, sensitive=True), _field("chat_id", "Telegram chat ID", placeholder="Only required for Telegram", sensitive=True), confirmation=True, history_safe=False),
    _spec("market.quote", "Market quote", "Market", "Load a live quote for a symbol.", "/market {symbol} {interval}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("interval", "Interval", placeholder="1d")),
    _spec("market.symbol", "Resolve symbol", "Market", "Search or normalize an instrument symbol.", "/symbol resolve {symbol}", _field("symbol", "Symbol", required=True, placeholder="BBRI")),
    _spec("market.news", "Latest news", "Market", "Load provider-backed news and fundamentals.", "/news {symbol}", _field("symbol", "Symbol", required=True, placeholder="AAPL")),
    _spec("market.calendar", "Economic calendar", "Market", "Show upcoming economic events.", "/calendar {period} {country} {importance}", _field("period", "Period", placeholder="week"), _field("country", "Country", placeholder="US"), _field("importance", "Importance", placeholder="high")),
    _spec("market.scan", "Market scan", "Market", "Scan symbols using an indicator filter.", "/scan {universe} {filter}", _field("universe", "Universe", required=True, placeholder="sp500"), _field("filter", "Filter", required=True, placeholder="rsi<30")),
    _spec("market.compare", "Compare providers", "Providers", "Compare provider data for a symbol.", "/provider compare {symbol}", _field("symbol", "Symbol", required=True, placeholder="TSLA")),
    _spec("research.run", "Deep research", "Research", "Run snapshot, deep, or report research.", "/research {symbol} {mode}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("mode", "Mode", kind="select", placeholder="--deep")),
    _spec("research.macro", "Macro context", "Research", "Load macro context for a region.", "/macro {region}", _field("region", "Region", required=True, placeholder="Indonesia")),
    _spec("research.technical", "Technical analysis", "Research", "Run indicator analysis.", "/technical {symbol} {interval}", _field("symbol", "Symbol", required=True, placeholder="BTC-USD"), _field("interval", "Interval", placeholder="1d")),
    _spec("research.chart", "Price chart", "Research", "Render chart data with optional overlays.", "/chart {symbol} {interval}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("interval", "Interval", placeholder="1d")),
    _spec("research.mtf", "Multi-timeframe", "Research", "Check technical alignment across timeframes.", "/mtf {symbol} {intervals}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("intervals", "Timeframes", placeholder="1d,1h,15m")),
    _spec("research.backtest", "Backtest strategy", "Research", "Run a provider-backed strategy backtest.", "/backtest {symbol} {strategy} {interval}", _field("symbol", "Symbol", required=True, placeholder="BTC-USD"), _field("strategy", "Strategy", placeholder="sma_cross"), _field("interval", "Interval", placeholder="1d")),
    _spec("portfolio.view", "View portfolio", "Portfolio", "Show active portfolio positions.", "/portfolio"),
    _spec("portfolio.performance", "Portfolio performance", "Portfolio", "Review portfolio performance.", "/portfolio performance"),
    _spec("portfolio.risk", "Portfolio risk", "Portfolio", "Review exposure, concentration, and risk.", "/portfolio risk"),
    _spec("portfolio.add", "Add position", "Portfolio", "Add an asset position.", "/portfolio add {symbol} {quantity} {price}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("quantity", "Quantity", required=True, kind="number"), _field("price", "Average price", required=True, kind="number")),
    _spec("portfolio.update", "Update position", "Portfolio", "Add to an existing position using weighted average.", "/portfolio update {symbol} {quantity} {price}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("quantity", "Quantity", required=True, kind="number"), _field("price", "Price", required=True, kind="number")),
    _spec("portfolio.remove", "Remove position", "Portfolio", "Remove an asset from the portfolio.", "/portfolio remove {symbol}", _field("symbol", "Symbol", required=True, placeholder="AAPL")),
    _spec("portfolio.transaction", "Record transaction", "Portfolio", "Add a buy or sell transaction.", "/tx add {side} {symbol} {quantity} {price}", _field("side", "Side", kind="select", placeholder="buy"), _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("quantity", "Quantity", required=True, kind="number"), _field("price", "Price", required=True, kind="number")),
    _spec("watchlist.view", "View watchlist", "Watchlist", "Show saved instruments.", "/watchlist"),
    _spec("watchlist.add", "Add to watchlist", "Watchlist", "Save an instrument for monitoring.", "/watchlist add {symbol} {group} {notes}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("group", "Group", placeholder="default"), _field("notes", "Note", placeholder="Optional note")),
    _spec("watchlist.remove", "Remove from watchlist", "Watchlist", "Remove a saved instrument.", "/watchlist remove {symbol}", _field("symbol", "Symbol", required=True, placeholder="AAPL")),
    _spec("watchlist.note", "Update watchlist note", "Watchlist", "Update a saved instrument note.", "/watchlist note {symbol} {notes}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("notes", "Note", required=True, placeholder="Breakout setup")),
    _spec("watchlist.groups", "Watchlist groups", "Watchlist", "Show watchlist groups.", "/watchlist groups"),
    _spec("alert.view", "View alerts", "Alerts", "Show active price alerts.", "/alert"),
    _spec("alert.add", "Add alert", "Alerts", "Create a price or indicator alert.", "/alert add {symbol} {condition} {target} {note}", _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("condition", "Condition", required=True, placeholder="above"), _field("target", "Target", required=True, kind="number"), _field("note", "Note", placeholder="Optional note")),
    _spec("alert.check", "Check alerts", "Alerts", "Check active alerts against provider data.", "/alert check"),
    _spec("alert.history", "Alert history", "Alerts", "Show triggered alert history.", "/alert history"),
    _spec("alert.daemon", "Alert daemon", "Alerts", "Start, stop, or inspect background alert checks.", "/alert daemon {state}", _field("state", "State", kind="select", placeholder="status")),
    _spec("journal.view", "View journal", "Journal", "Show recent journal entries.", "/journal"),
    _spec("journal.add", "Add journal entry", "Journal", "Record an investment or trading observation.", "/journal add {instrument} {bias} {entry_reason}", _field("instrument", "Instrument", required=True, placeholder="BTC-USD"), _field("bias", "Bias", placeholder="bullish"), _field("entry_reason", "Reason", required=True, placeholder="Breakout failed")),
    _spec("journal.edit", "Edit journal entry", "Journal", "Update a journal entry field.", "/journal edit {id} --{field} {value}", _field("id", "Entry ID", required=True, kind="number"), _field("field", "Field", placeholder="bias"), _field("value", "Value", required=True)),
    _spec("journal.delete", "Delete journal entry", "Journal", "Delete a journal entry.", "/journal delete {id}", _field("id", "Entry ID", required=True, kind="number"), confirmation=True),
    _spec("journal.stats", "Journal statistics", "Journal", "Review journal statistics.", "/journal stats"),
    _spec("journal.review", "Review journal habits", "Journal", "Ask the AI to review journal patterns.", "/journal review"),
    _spec("trading.view", "Trading overview", "Trading", "Show paper trading and broker status.", "/trading"),
    _spec("trading.paper_order", "Paper order", "Trading", "Place a paper order using the risk guard.", "/trading paper {side} {symbol} {quantity} {order_type} {price}", _field("side", "Side", kind="select", placeholder="buy"), _field("symbol", "Symbol", required=True, placeholder="AAPL"), _field("quantity", "Quantity", required=True, kind="number"), _field("order_type", "Order type", placeholder="market"), _field("price", "Price", kind="number")),
    _spec("trading.positions", "Paper positions", "Trading", "Show paper trading positions.", "/trading positions"),
    _spec("trading.risk", "Trading risk", "Trading", "Show risk guard status.", "/trading risk"),
    _spec("trading.audit", "Trading audit", "Trading", "Review immutable order audit records.", "/trading audit"),
    _spec("trading.cancel", "Cancel paper order", "Trading", "Cancel a queued paper order.", "/trading cancel {id}", _field("id", "Order ID", required=True, kind="number"), confirmation=True),
    _spec("trading.kill", "Activate kill switch", "Trading", "Block all paper orders immediately.", "/trading kill", confirmation=True),
    _spec("trading.resume", "Resume paper trading", "Trading", "Re-enable paper orders.", "/trading resume", confirmation=True),
    _spec("provider.status", "Provider status", "Providers", "Show active providers and circuit state.", "/provider status"),
    _spec("provider.trust", "Provider trust", "Providers", "Review trust and fallback policy.", "/provider trust"),
    _spec("provider.metrics", "Provider metrics", "Providers", "Review runtime provider metrics.", "/provider metrics"),
    _spec("provider.capabilities", "Provider capabilities", "Providers", "Show the provider capability matrix.", "/provider capabilities"),
    _spec("provider.list", "Provider catalog", "Providers", "List available market providers.", "/provider list"),
    _spec("provider.test", "Test provider", "Providers", "Test the active provider with a symbol.", "/provider test {symbol}", _field("symbol", "Symbol", required=True, placeholder="AAPL")),
    _spec("system.doctor", "System doctor", "System", "Check configuration, database, and providers.", "/doctor"),
    _spec("system.cache_stats", "Cache statistics", "System", "Show persistent cache statistics.", "/cache stats"),
    _spec("system.cache_clear", "Clear cache", "System", "Clear runtime and persistent cache.", "/cache clear", confirmation=True),
    _spec("profile.view", "View profile", "Profile", "Show risk profile settings.", "/profile"),
    _spec("profile.set", "Set profile", "Profile", "Save risk profile settings.", "/profile set {name} {equity} {currency} {leverage} {years}", _field("name", "Name", required=True), _field("equity", "Equity", required=True, kind="number"), _field("currency", "Currency", placeholder="USD"), _field("leverage", "Leverage", placeholder="1:1"), _field("years", "Experience", kind="number")),
    _spec("export.journal", "Export journal", "System", "Export journal data.", "/export journal {format} {path}", _field("format", "Format", placeholder="csv"), _field("path", "File path", required=True, placeholder="journal.csv")),
    _spec("export.portfolio", "Export portfolio", "System", "Export portfolio data.", "/export portfolio {format} {path}", _field("format", "Format", placeholder="json"), _field("path", "File path", required=True, placeholder="portfolio.json")),
)


ACTION_BY_NAME = {item.action: item for item in ACTION_SPECS}


def _value(params: dict[str, Any], name: str, required: bool = False) -> str:
    value = str(params.get(name, "") or "").strip()
    if required and not value:
        raise ValueError(f"Parameter '{name}' is required.")
    return value


def _quote(value: str) -> str:
    return shlex.quote(value)


def command_for_action(action: str, params: dict[str, Any] | None = None) -> str:
    """Build a shell-like command using the router's shlex-compatible syntax."""
    spec = ACTION_BY_NAME.get(action)
    if spec is None:
        raise KeyError(f"Unknown desktop action: {action}")
    params = params or {}
    values = {item["name"]: _quote(_value(params, item["name"], bool(item.get("required")))) for item in spec.fields}
    if action == "journal.edit":
        values["field"] = _value(params, "field") or "bias"
    command = spec.command.format(**values)
    # Empty optional placeholders should not leave trailing whitespace or args.
    return " ".join(part for part in command.split() if part not in {"''", '""'}).strip()


def _terminal_reason(spec: CommandSpec) -> str | None:
    name = spec.name.lower()
    if name in {"/ai_model", "/news_model"}:
        return "The CLI selector is interactive; use the desktop model selector instead."
    if name in TERMINAL_ONLY_SECRET_COMMANDS:
        return "Use the secure desktop form; credentials are excluded from conversation history."
    return None


DESKTOP_REPLACEMENTS = {
    "/ai_model": "ai.model",
    "/news_model": "provider.news",
    "/notification add": "notification.add",
}


def command_capabilities() -> list[dict[str, Any]]:
    """Return every registered command with desktop policy metadata."""
    rows: list[dict[str, Any]] = []
    for spec in COMMANDS:
        reason = _terminal_reason(spec)
        action = next(
            (item for item in ACTION_SPECS if spec.name == item.command.split("{")[0].strip() or spec.name.startswith(item.command.split("{")[0].strip() + " ")),
            None,
        )
        replacement_action = DESKTOP_REPLACEMENTS.get(spec.name)
        rows.append({
            "name": spec.name,
            "description": spec.description,
            "example": spec.example,
            "group": spec.group,
            "desktop_supported": reason is None,
            "desktop_available": reason is None or replacement_action is not None,
            "input_schema": list(action.fields) if action else [],
            "action": action.action if action else None,
            "replacement_action": replacement_action,
            "confirmation_required": command_requires_confirmation(spec.example),
            "terminal_only_reason": reason,
        })
    return rows


def desktop_capabilities() -> dict[str, Any]:
    return {"commands": command_capabilities(), "actions": [item.to_dict() for item in ACTION_SPECS]}
