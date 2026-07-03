"""Interactive market/news provider selector screen."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.storage.secrets import save_secret
from fincli.app.utils.formatting import mask_secret

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult
    from textual.events import Key

    from fincli.app.storage.config import ConfigManager


@dataclass(frozen=True, slots=True)
class MarketProviderChoice:
    provider: str
    label: str
    env_keys: tuple[str, ...]
    description: str


@dataclass(frozen=True, slots=True)
class PriorityChoice:
    label: str
    providers: tuple[str, ...]
    description: str


PROVIDER_LABELS = {
    "yfinance": "Yahoo Finance",
    "custom": "Custom API",
    "finnhub": "Finnhub",
    "twelvedata": "Twelve Data",
    "alphavantage": "Alpha Vantage",
}
PROVIDER_ENV_KEYS = {
    "yfinance": (),
    "custom": ("MARKET_DATA_API_KEY", "MARKET_DATA_BASE_URL"),
    "finnhub": ("FINNHUB_API_KEY",),
    "twelvedata": ("TWELVE_DATA_API_KEY",),
    "alphavantage": ("ALPHA_VANTAGE_API_KEY",),
}
DEFAULT_FALLBACK_ORDER = ("twelvedata", "finnhub", "alphavantage", "custom", "yfinance")


def market_provider_choices() -> tuple[MarketProviderChoice, ...]:
    """Return selector choices from the market provider catalog."""
    choices: list[MarketProviderChoice] = []
    for info in MarketProviderManager().list_providers():
        choices.append(
            MarketProviderChoice(
                provider=info.name,
                label=PROVIDER_LABELS.get(info.name, info.name.title()),
                env_keys=PROVIDER_ENV_KEYS.get(info.name, ()),
                description=f"{info.status}; realtime={info.realtime}; {info.notes}",
            )
        )
    return tuple(choices)


def recommended_provider_priority(primary: str) -> tuple[str, ...]:
    """Build a conservative fallback chain with yfinance as final fallback."""
    normalized = primary.lower().strip()
    if normalized == "yfinance":
        return ("yfinance",)
    priority = [normalized] if normalized else ["yfinance"]
    for provider in DEFAULT_FALLBACK_ORDER:
        if provider != "yfinance" and provider not in priority:
            priority.append(provider)
    if "yfinance" not in priority:
        priority.append("yfinance")
    return tuple(priority)


def priority_presets(primary: str) -> tuple[PriorityChoice, ...]:
    """Return selectable fallback presets for a primary provider."""
    recommended = recommended_provider_priority(primary)
    minimal = tuple(dict.fromkeys((primary.lower(), "yfinance")))
    all_data_first = tuple(provider for provider in DEFAULT_FALLBACK_ORDER if provider in recommended)
    return (
        PriorityChoice("Recommended fallback", recommended, "Primary provider first, then other providers, yfinance last."),
        PriorityChoice("Primary + yfinance", minimal, "Use selected provider and delayed yfinance fallback only."),
        PriorityChoice("Data API priority", all_data_first, "Try realtime-capable providers before yfinance."),
        PriorityChoice("YFinance only", ("yfinance",), "Delayed fallback only, no API key required."),
    )


class MarketProviderSelectorScreen(ModalScreen[tuple[str, ...] | None]):
    """Modal selector for market/news provider and fallback priority."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("tab", "change_provider", "Provider"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, config: ConfigManager, on_selected: Callable[[tuple[str, ...]], None]) -> None:
        super().__init__()
        self.config = config
        self.on_selected = on_selected
        self.mode = "provider"
        self.selected_index = 0
        self.selected_provider = config.settings.market_provider
        self.search = ""
        self.pending_env_keys: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="ai_selector_card"):
            yield Static(id="ai_selector_title")
            yield Static(id="ai_selector_provider")
            yield Input(placeholder="Search providers...", id="ai_selector_search")
            with VerticalScroll(id="ai_selector_scroll"):
                yield Static(id="ai_selector_list")
            yield Static(id="ai_selector_help")

    def on_mount(self) -> None:
        self._sync_search_placeholder()
        self._render_selector()
        self.query_one("#ai_selector_search", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.search = event.value.strip().lower()
        self.selected_index = 0
        self._render_selector()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if self.mode == "key":
            self._save_key(event.value)
            return
        self.action_select()

    def on_key(self, event: Key) -> None:
        if event.key == "up":
            event.stop()
            self.action_cursor_up()
        elif event.key == "down":
            event.stop()
            self.action_cursor_down()
        elif event.key == "tab":
            event.stop()
            self.action_change_provider()
        elif event.key == "escape":
            event.stop()
            self.action_cancel()

    def action_cursor_up(self) -> None:
        total = len(self._visible_items())
        if total:
            self.selected_index = (self.selected_index - 1) % total
            self._render_selector()

    def action_cursor_down(self) -> None:
        total = len(self._visible_items())
        if total:
            self.selected_index = (self.selected_index + 1) % total
            self._render_selector()

    def action_change_provider(self) -> None:
        self._set_mode("provider")

    def action_select(self) -> None:
        items = self._visible_items()
        if not items:
            return
        selected = items[self.selected_index]
        if self.mode == "provider":
            provider = selected.provider  # type: ignore[attr-defined]
            self.selected_provider = provider
            self.pending_env_keys = [key for key in PROVIDER_ENV_KEYS.get(provider, ()) if not os.getenv(key)]
            if self.pending_env_keys:
                self._set_mode("key")
            else:
                self._set_mode("priority")
            return

        providers = selected.providers  # type: ignore[attr-defined]
        self.config.set_market_provider_priority(list(providers))
        self.on_selected(providers)
        self.dismiss(providers)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self.selected_index = 0
        self.search = ""
        self.query_one("#ai_selector_search", Input).value = ""
        self._sync_search_placeholder()
        self._render_selector()

    def _sync_search_placeholder(self) -> None:
        search = self.query_one("#ai_selector_search", Input)
        search.password = self.mode == "key"
        if self.mode == "key":
            env_key = self.pending_env_keys[0] if self.pending_env_keys else "API_KEY"
            search.placeholder = f"Paste {env_key}..."
        else:
            search.placeholder = "Search fallback presets..." if self.mode == "priority" else "Search providers..."

    def _visible_items(self) -> list[MarketProviderChoice] | list[PriorityChoice]:
        if self.mode == "key":
            return []
        if self.mode == "priority":
            presets = list(priority_presets(self.selected_provider))
            if self.search:
                presets = [
                    preset
                    for preset in presets
                    if self.search in preset.label.lower() or self.search in ",".join(preset.providers)
                ]
            return presets

        choices = list(market_provider_choices())
        if self.search:
            choices = [
                choice
                for choice in choices
                if self.search in choice.label.lower() or self.search in choice.provider or self.search in choice.description.lower()
            ]
        return choices

    def _render_selector(self) -> None:
        title = self.query_one("#ai_selector_title", Static)
        provider = self.query_one("#ai_selector_provider", Static)
        body = self.query_one("#ai_selector_list", Static)
        help_text = self.query_one("#ai_selector_help", Static)

        if self.mode == "priority":
            title.update("Select Provider Priority")
            provider.update(f"[cyan]Primary:[/] {self.selected_provider} [dim](tab to change provider)[/]")
        elif self.mode == "key":
            env_key = self.pending_env_keys[0] if self.pending_env_keys else "API_KEY"
            title.update("Configure Market API Key")
            provider.update(f"[cyan]Provider:[/] {self.selected_provider} [dim]{env_key} saved to ~/.fincli/secrets.env[/]")
        else:
            title.update("Select Market/News Provider")
            provider.update("")

        body.update(self._items_text(self._visible_items()))
        help_text.update(self._help_text())

    def _items_text(self, items: list[MarketProviderChoice] | list[PriorityChoice]) -> Text:
        text = Text()
        if self.mode == "key":
            env_key = self.pending_env_keys[0] if self.pending_env_keys else "API_KEY"
            text.append(f"Paste {env_key} above, then press Enter.\n", style="bold")
            text.append("The value is stored locally and will not be printed in output.\n", style="dim")
            return text
        text.append("Providers\n" if self.mode == "provider" else "Fallback presets\n", style="bold dim")
        for index, item in enumerate(items):
            selected = index == self.selected_index
            prefix = "> " if selected else "  "
            style = "black on cyan" if selected else "white"
            if isinstance(item, MarketProviderChoice):
                current = " * (current)" if item.provider == self.config.settings.market_provider else ""
                key_status = _provider_key_status(item)
                line = f"{prefix}{item.label}{current} {key_status}\n"
                detail = f"    {item.description}\n"
            else:
                chain = " -> ".join(item.providers)
                line = f"{prefix}{item.label}: {chain}\n"
                detail = f"    {item.description}\n"
            text.append(line, style=style)
            text.append(detail, style="dim" if not selected else "black on cyan")
        if not items:
            text.append("No matches.\n", style="dim")
        return text

    def _help_text(self) -> str:
        if self.mode == "key":
            return "Paste key/value, Enter to save, Esc to close"
        if self.mode == "priority":
            return "Type to search, up/down navigate, Enter to save priority, Tab to change provider, Esc to close"
        return "Type to search, up/down navigate, Enter to select provider, Esc to close"

    def _save_key(self, value: str) -> None:
        if not self.pending_env_keys or not value.strip():
            return
        env_key = self.pending_env_keys.pop(0)
        save_secret(env_key, value)
        if self.pending_env_keys:
            self._set_mode("key")
        else:
            providers = recommended_provider_priority(self.selected_provider)
            self.config.set_market_provider_priority(list(providers))
            self.on_selected(providers)
            self._set_mode("priority")


def _provider_key_status(choice: MarketProviderChoice) -> str:
    if not choice.env_keys:
        return "(no key required)"
    statuses = []
    for key in choice.env_keys:
        masked = mask_secret(os.getenv(key))
        statuses.append(f"{key}={masked}")
    return f"({', '.join(statuses)})"
