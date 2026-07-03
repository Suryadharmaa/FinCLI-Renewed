"""Interactive AI provider/model selector screen."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.storage.secrets import save_secret
from fincli.app.utils.formatting import mask_secret

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.app import ComposeResult
    from textual.events import Key

    from fincli.app.storage.config import ConfigManager


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    provider: str
    label: str
    env_key: str
    category: str = "Popular"


@dataclass(frozen=True, slots=True)
class ModelChoice:
    provider: str
    model: str
    label: str
    context: str = ""


PROVIDERS: tuple[ProviderChoice, ...] = (
    ProviderChoice("openrouter", "OpenRouter", "OPENROUTER_API_KEY"),
    ProviderChoice("openai", "OpenAI", "OPENAI_API_KEY"),
    ProviderChoice("anthropic", "Anthropic", "ANTHROPIC_API_KEY"),
    ProviderChoice("gemini", "Gemini", "GEMINI_API_KEY"),
    ProviderChoice("groq", "Groq", "GROQ_API_KEY"),
    ProviderChoice("together", "Together AI", "TOGETHER_API_KEY"),
    ProviderChoice("huggingface", "HuggingFace", "HUGGINGFACE_API_KEY"),
)


MODEL_CATALOG: dict[str, tuple[ModelChoice, ...]] = {
    "openrouter": (
        # Routers / dynamic aliases
        ModelChoice("openrouter", "openai/gpt-4o-mini", "GPT-4o Mini", "128K"),
        ModelChoice("openrouter", "openrouter/free", "Free Models Router", "200K"),
        ModelChoice("openrouter", "openrouter/auto", "Auto Router", ""),
        ModelChoice("openrouter", "openrouter/fusion", "Fusion", "128K"),
        ModelChoice("openrouter", "openrouter/pareto-code", "Pareto Code Router", "2M"),
        ModelChoice("openrouter", "openrouter/owl-alpha", "Owl Alpha", "1M"),
        ModelChoice("openrouter", "openrouter/bodybuilder", "Body Builder", "128K"),

        # OpenAI via OpenRouter
        ModelChoice("openrouter", "~openai/gpt-latest", "OpenAI GPT Latest", "1.05M"),
        ModelChoice("openrouter", "~openai/gpt-mini-latest", "OpenAI GPT Mini Latest", "400K"),
        ModelChoice("openrouter", "openai/gpt-chat-latest", "OpenAI GPT Chat Latest", "400K"),
        ModelChoice("openrouter", "openai/gpt-5.5-pro", "OpenAI GPT-5.5 Pro", "1.05M"),
        ModelChoice("openrouter", "openai/gpt-5.5", "OpenAI GPT-5.5", "1.05M"),
        ModelChoice("openrouter", "openai/gpt-5.4-image-2", "OpenAI GPT-5.4 Image 2", "272K"),

        # Anthropic via OpenRouter
        ModelChoice("openrouter", "~anthropic/claude-opus-latest", "Claude Opus Latest", "1M"),
        ModelChoice("openrouter", "~anthropic/claude-sonnet-latest", "Claude Sonnet Latest", "1M"),
        ModelChoice("openrouter", "~anthropic/claude-haiku-latest", "Claude Haiku Latest", "200K"),
        ModelChoice("openrouter", "anthropic/claude-opus-4.8", "Claude Opus 4.8", "1M"),
        ModelChoice("openrouter", "anthropic/claude-opus-4.8-fast", "Claude Opus 4.8 Fast", "1M"),
        ModelChoice("openrouter", "anthropic/claude-opus-4.7", "Claude Opus 4.7", "1M"),
        ModelChoice("openrouter", "anthropic/claude-opus-4.7-fast", "Claude Opus 4.7 Fast", "1M"),
        ModelChoice("openrouter", "anthropic/claude-opus-4.6-fast", "Claude Opus 4.6 Fast", "1M"),

        # Google / Gemini via OpenRouter
        ModelChoice("openrouter", "~google/gemini-pro-latest", "Gemini Pro Latest", "1M"),
        ModelChoice("openrouter", "~google/gemini-flash-latest", "Gemini Flash Latest", "1M"),
        ModelChoice("openrouter", "google/gemini-3.5-flash", "Gemini 3.5 Flash", "1M"),
        ModelChoice("openrouter", "google/gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "1M"),

        # Qwen via OpenRouter
        ModelChoice("openrouter", "qwen/qwen3.7-plus", "Qwen3.7 Plus", "1M"),
        ModelChoice("openrouter", "qwen/qwen3.7-max", "Qwen3.7 Max", "1M"),
        ModelChoice("openrouter", "qwen/qwen3.6-plus", "Qwen3.6 Plus", "1M"),
        ModelChoice("openrouter", "qwen/qwen3.6-flash", "Qwen3.6 Flash", "1M"),
        ModelChoice("openrouter", "qwen/qwen3.6-max-preview", "Qwen3.6 Max Preview", "256K"),
        ModelChoice("openrouter", "qwen/qwen3.6-35b-a3b", "Qwen3.6 35B A3B", "262K"),
        ModelChoice("openrouter", "qwen/qwen3.6-27b", "Qwen3.6 27B", "262K"),
        ModelChoice("openrouter", "qwen/qwen3.5-plus-20260420", "Qwen3.5 Plus 2026-04-20", "1M"),

        # DeepSeek / xAI / Mistral / others via OpenRouter
        ModelChoice("openrouter", "deepseek/deepseek-v4-pro", "DeepSeek V4 Pro", "1M"),
        ModelChoice("openrouter", "deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", "1M"),
        ModelChoice("openrouter", "x-ai/grok-build-0.1", "Grok Build 0.1", "256K"),
        ModelChoice("openrouter", "x-ai/grok-4.3", "Grok 4.3", "1M"),
        ModelChoice("openrouter", "x-ai/grok-4.20", "Grok 4.20", "2M"),
        ModelChoice("openrouter", "x-ai/grok-4.20-multi-agent", "Grok 4.20 Multi-Agent", "2M"),
        ModelChoice("openrouter", "mistralai/mistral-medium-3-5", "Mistral Medium 3.5", "262K"),
        ModelChoice("openrouter", "minimax/minimax-m3", "MiniMax M3", "1M"),
        ModelChoice("openrouter", "moonshotai/kimi-k2.6", "Kimi K2.6", "262K"),
        ModelChoice("openrouter", "~moonshotai/kimi-latest", "Kimi Latest", "262K"),
        ModelChoice("openrouter", "nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra", "1M"),
        ModelChoice("openrouter", "stepfun/step-3.7-flash", "Step 3.7 Flash", "256K"),
        ModelChoice("openrouter", "perceptron/perceptron-mk1", "Perceptron Mk1", "32K"),
        ModelChoice("openrouter", "inclusionai/ring-2.6-1t", "Ring-2.6-1T", "262K"),
        ModelChoice("openrouter", "inclusionai/ling-2.6-1t", "Ling-2.6-1T", "262K"),
        ModelChoice("openrouter", "inclusionai/ling-2.6-flash", "Ling-2.6 Flash", "262K"),
        ModelChoice("openrouter", "tencent/hy3-preview", "Tencent Hy3 Preview", "262K"),
        ModelChoice("openrouter", "xiaomi/mimo-v2.5-pro", "MiMo V2.5 Pro", "1M"),
        ModelChoice("openrouter", "xiaomi/mimo-v2.5", "MiMo V2.5", "1M"),
        ModelChoice("openrouter", "z-ai/glm-5.1", "GLM 5.1", "203K"),
        ModelChoice("openrouter", "z-ai/glm-5v-turbo", "GLM 5V Turbo", "203K"),
        ModelChoice("openrouter", "ibm-granite/granite-4.1-8b", "Granite 4.1 8B", "131K"),
        ModelChoice("openrouter", "arcee-ai/trinity-large-thinking", "Trinity Large Thinking", "262K"),

        # Verified free OpenRouter variants / free-priority
        ModelChoice("openrouter", "nvidia/nemotron-3.5-content-safety:free", "Nemotron 3.5 Content Safety Free", "128K"),
        ModelChoice("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra Free", "1M"),
        ModelChoice("openrouter", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", "Nemotron 3 Nano Omni Free", "256K"),
        ModelChoice("openrouter", "poolside/laguna-xs.2:free", "Laguna XS.2 Free", "262K"),
        ModelChoice("openrouter", "poolside/laguna-m.1:free", "Laguna M.1 Free", "262K"),
        ModelChoice("openrouter", "moonshotai/kimi-k2.6:free", "Kimi K2.6 Free", "262K"),
        ModelChoice("openrouter", "google/gemma-4-26b-a4b-it:free", "Gemma 4 26B A4B Free", "262K"),
        ModelChoice("openrouter", "google/gemma-4-31b-it:free", "Gemma 4 31B Free", "262K"),
        ModelChoice("openrouter", "liquid/lfm-2.5-1.2b-thinking:free", "LFM2.5 1.2B Thinking Free", "32K"),
        ModelChoice("openrouter", "liquid/lfm-2.5-1.2b-instruct:free", "LFM2.5 1.2B Instruct Free", "32K"),
        ModelChoice("openrouter", "nvidia/nemotron-3-nano-30b-a3b:free", "Nemotron 3 Nano 30B A3B Free", "131K"),
        ModelChoice("openrouter", "nvidia/nemotron-nano-12b-v2-vl:free", "Nemotron Nano 12B V2 VL Free", "128K"),
        ModelChoice("openrouter", "openai/gpt-oss-120b:free", "GPT OSS 120B Free", "131K"),
        ModelChoice("openrouter", "openai/gpt-oss-20b:free", "GPT OSS 20B Free", "131K"),
        ModelChoice("openrouter", "z-ai/glm-4.5-air:free", "GLM 4.5 Air Free", "131K"),
        ModelChoice("openrouter", "qwen/qwen3-coder:free", "Qwen3 Coder Free", "1M"),
        ModelChoice("openrouter", "cognitivecomputations/dolphin-mistral-24b-venice-edition:free", "Dolphin Mistral 24B Venice Free", "32K"),
        ModelChoice("openrouter", "meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B Free", "131K"),
        ModelChoice("openrouter", "meta-llama/llama-3.2-3b-instruct:free", "Llama 3.2 3B Free", "131K"),
    ),

    "openai": (
        ModelChoice("openai", "gpt-5.5", "GPT-5.5", "1M"),
        ModelChoice("openai", "gpt-5.4", "GPT-5.4", "1M"),
        ModelChoice("openai", "gpt-5.4-mini", "GPT-5.4 Mini", "400K"),
        ModelChoice("openai", "gpt-5.4-nano", "GPT-5.4 Nano", "400K"),
        ModelChoice("openai", "gpt-4.1", "GPT-4.1", "1M"),
        ModelChoice("openai", "gpt-4.1-mini", "GPT-4.1 Mini", "1M"),
        ModelChoice("openai", "gpt-4.1-nano", "GPT-4.1 Nano", "1M"),
        ModelChoice("openai", "gpt-4o", "GPT-4o", "128K"),
        ModelChoice("openai", "gpt-4o-mini", "GPT-4o Mini", "128K"),
    ),

    "anthropic": (
        ModelChoice("anthropic", "claude-opus-4-8", "Claude Opus 4.8", "1M"),
        ModelChoice("anthropic", "claude-sonnet-4-6", "Claude Sonnet 4.6", "1M"),
        ModelChoice("anthropic", "claude-haiku-4-5", "Claude Haiku 4.5", "200K"),
        ModelChoice("anthropic", "claude-3-5-sonnet-latest", "Claude 3.5 Sonnet Latest", "200K"),
        ModelChoice("anthropic", "claude-3-5-haiku-latest", "Claude 3.5 Haiku Latest", "200K"),
        ModelChoice("anthropic", "claude-3-opus-latest", "Claude 3 Opus Latest", "200K"),
    ),

    "gemini": (
        ModelChoice("gemini", "gemini-3.5-flash", "Gemini 3.5 Flash", "1M"),
        ModelChoice("gemini", "gemini-3.1-pro-preview", "Gemini 3.1 Pro Preview", "1M"),
        ModelChoice("gemini", "gemini-3.1-pro-preview-customtools", "Gemini 3.1 Pro Preview Custom Tools", "1M"),
        ModelChoice("gemini", "gemini-3-flash-preview", "Gemini 3 Flash Preview", "1M"),
        ModelChoice("gemini", "gemini-2.5-pro", "Gemini 2.5 Pro", "1M"),
        ModelChoice("gemini", "gemini-2.5-flash", "Gemini 2.5 Flash", "1M"),
        ModelChoice("gemini", "gemini-2.5-flash-lite", "Gemini 2.5 Flash-Lite", "1M"),
    ),

    "groq": (
        ModelChoice("groq", "llama-3.1-8b-instant", "Llama 3.1 8B Instant", "131K"),
        ModelChoice("groq", "llama-3.3-70b-versatile", "Llama 3.3 70B Versatile", "131K"),
        ModelChoice("groq", "openai/gpt-oss-120b", "GPT OSS 120B", "131K"),
        ModelChoice("groq", "openai/gpt-oss-20b", "GPT OSS 20B", "131K"),
        ModelChoice("groq", "groq/compound", "Groq Compound", "131K"),
        ModelChoice("groq", "groq/compound-mini", "Groq Compound Mini", "131K"),
        ModelChoice("groq", "meta-llama/llama-4-scout-17b-16e-instruct", "Llama 4 Scout 17B 16E", "131K"),
        ModelChoice("groq", "qwen/qwen3-32b", "Qwen3 32B", "131K"),
        ModelChoice("groq", "openai/gpt-oss-safeguard-20b", "GPT OSS Safeguard 20B", "131K"),
    ),

    "together": (
        ModelChoice("together", "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "Llama 3.1 70B Turbo", "128K"),
        ModelChoice("together", "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "Llama 3.1 8B Turbo", "128K"),
        ModelChoice("together", "Qwen/Qwen2.5-72B-Instruct-Turbo", "Qwen 2.5 72B Turbo", "128K"),
        ModelChoice("together", "deepseek-ai/DeepSeek-R1", "DeepSeek R1", ""),
        ModelChoice("together", "deepseek-ai/DeepSeek-V3", "DeepSeek V3", ""),
        ModelChoice("together", "mistralai/Mixtral-8x7B-Instruct-v0.1", "Mixtral 8x7B Instruct", "32K"),
        ModelChoice("together", "mistralai/Mistral-7B-Instruct-v0.3", "Mistral 7B Instruct v0.3", "32K"),
    ),

    "huggingface": (
        ModelChoice("huggingface", "meta-llama/Llama-3.1-8B-Instruct", "Llama 3.1 8B", ""),
        ModelChoice("huggingface", "meta-llama/Llama-3.1-70B-Instruct", "Llama 3.1 70B", ""),
        ModelChoice("huggingface", "meta-llama/Llama-3.3-70B-Instruct", "Llama 3.3 70B", ""),
        ModelChoice("huggingface", "Qwen/Qwen2.5-7B-Instruct", "Qwen 2.5 7B", ""),
        ModelChoice("huggingface", "Qwen/Qwen2.5-72B-Instruct", "Qwen 2.5 72B", ""),
        ModelChoice("huggingface", "Qwen/QwQ-32B", "QwQ 32B", ""),
        ModelChoice("huggingface", "mistralai/Mistral-7B-Instruct-v0.3", "Mistral 7B Instruct", ""),
        ModelChoice("huggingface", "mistralai/Mixtral-8x7B-Instruct-v0.1", "Mixtral 8x7B Instruct", ""),
        ModelChoice("huggingface", "google/gemma-2-9b-it", "Gemma 2 9B IT", ""),
        ModelChoice("huggingface", "google/gemma-2-27b-it", "Gemma 2 27B IT", ""),
        ModelChoice("huggingface", "deepseek-ai/DeepSeek-R1", "DeepSeek R1", ""),
        ModelChoice("huggingface", "deepseek-ai/DeepSeek-V3-0324", "DeepSeek V3 0324", ""),
        ModelChoice("huggingface", "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B", "DeepSeek R1 Distill Qwen 32B", ""),
        ModelChoice("huggingface", "microsoft/Phi-3.5-mini-instruct", "Phi 3.5 Mini Instruct", ""),
    ),
}


class AIModelSelectorScreen(ModalScreen[tuple[str, str] | None]):
    """Modal selector for AI provider and model."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("tab", "change_provider", "Provider"),
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, config: ConfigManager, on_selected: Callable[[str, str], None]) -> None:
        super().__init__()
        self.config = config
        self.on_selected = on_selected
        self.mode = "provider"
        self.selected_index = 0
        self.selected_provider = config.settings.ai_provider
        self.search = ""

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
            if _has_key(provider):
                self._set_mode("configured")
            else:
                self._set_mode("key")
            return
        if self.mode == "configured":
            if selected == "Configure API key":
                self._set_mode("key")
            elif selected == "Change model":
                self._set_mode("model")
            else:
                self._set_mode("model")
            return
        model = selected.model  # type: ignore[attr-defined]
        self.config.set_ai_model(self.selected_provider, model)
        self.on_selected(self.selected_provider, model)
        self.dismiss((self.selected_provider, model))

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
            choice = _provider_choice(self.selected_provider)
            env_key = choice.env_key if choice else "API_KEY"
            search.placeholder = f"Paste {env_key}..."
        else:
            search.placeholder = "Search models..." if self.mode == "model" else "Search providers..."

    def _visible_items(self) -> list[ProviderChoice] | list[ModelChoice] | list[str]:
        if self.mode == "provider":
            items = list(PROVIDERS)
            if self.search:
                items = [item for item in items if self.search in item.label.lower() or self.search in item.provider]
            return items
        if self.mode == "configured":
            return ["Use existing configuration", "Configure API key", "Change model"]
        if self.mode == "key":
            return []
        models = list(MODEL_CATALOG.get(self.selected_provider, ()))
        if self.search:
            models = [item for item in models if self.search in item.label.lower() or self.search in item.model.lower()]
        if not models:
            models = [ModelChoice(self.selected_provider, self.config.settings.ai_model, self.config.settings.ai_model, "current/custom")]
        return models

    def _render_selector(self) -> None:
        title = self.query_one("#ai_selector_title", Static)
        provider = self.query_one("#ai_selector_provider", Static)
        body = self.query_one("#ai_selector_list", Static)
        help_text = self.query_one("#ai_selector_help", Static)

        if self.mode == "provider":
            title.update("Select Provider")
            provider.update("")
        elif self.mode == "configured":
            choice = _provider_choice(self.selected_provider)
            label = choice.label if choice else self.selected_provider
            title.update(f"{label} is already configured")
            provider.update(f"[cyan]Provider:[/] {label} [dim]{_masked_key(self.selected_provider)}[/]")
        elif self.mode == "key":
            choice = _provider_choice(self.selected_provider)
            label = choice.label if choice else self.selected_provider
            title.update("Configure API Key")
            provider.update(f"[cyan]Provider:[/] {label} [dim](saved to ~/.fincli/secrets.env)[/]")
        else:
            choice = _provider_choice(self.selected_provider)
            label = choice.label if choice else self.selected_provider
            title.update("Select Model")
            provider.update(f"[cyan]Provider:[/] {label} [dim](tab to change provider)[/]")

        items = self._visible_items()
        body.update(self._items_text(items))
        help_text.update(self._help_text())

    def _items_text(self, items: list[ProviderChoice] | list[ModelChoice] | list[str]) -> Text:
        text = Text()
        if self.mode == "provider":
            text.append("Popular\n", style="bold dim")
        elif self.mode == "model":
            hidden = max(0, len(MODEL_CATALOG.get(self.selected_provider, ())) - len(items))
            text.append(f"{hidden} filtered\n" if self.search else "Available models\n", style="bold dim")
        elif self.mode == "key":
            choice = _provider_choice(self.selected_provider)
            env_key = choice.env_key if choice else "API_KEY"
            text.append(f"Paste {env_key} above, then press Enter.\n", style="bold")
            text.append("The key is stored locally and will not be printed in output.\n", style="dim")
            return text

        for index, item in enumerate(items):
            selected = index == self.selected_index
            prefix = "> " if selected else "  "
            style = "black on cyan" if selected else "white"
            if isinstance(item, ProviderChoice):
                current = " • (current)" if item.provider == self.config.settings.ai_provider else ""
                configured = " ●" if _has_key(item.provider) else ""
                line = f"{prefix}{item.label}{current}{configured}\n"
            elif isinstance(item, ModelChoice):
                current = " • (current)" if item.model == self.config.settings.ai_model else ""
                context = f" {item.context}" if item.context else ""
                line = f"{prefix}{item.label}{context}{current}\n"
            else:
                line = f"{prefix}{item}\n"
            text.append(line, style=style)
        if not items:
            text.append("No matches.\n", style="dim")
        return text

    def _help_text(self) -> str:
        if self.mode == "key":
            return "Paste API key, Enter to save, Esc to close"
        if self.mode == "configured":
            return "Up/down navigate, Enter to select, Esc to go back"
        if self.mode == "model":
            return "Type to search, up/down navigate, Enter to select, Tab to change provider, Esc to close"
        return "Type to search, up/down navigate, Enter to select, Esc to close"

    def _save_key(self, value: str) -> None:
        choice = _provider_choice(self.selected_provider)
        if choice is None or not value.strip():
            return
        save_secret(choice.env_key, value)
        model = self.config.settings.ai_model if self.config.settings.ai_provider == choice.provider else _default_model(choice.provider)
        self.config.set_ai_model(choice.provider, model)
        self.on_selected(choice.provider, model)
        self._set_mode("model")


def _provider_choice(provider: str) -> ProviderChoice | None:
    normalized = provider.lower()
    return next((choice for choice in PROVIDERS if choice.provider == normalized), None)


def _has_key(provider: str) -> bool:
    choice = _provider_choice(provider)
    return bool(choice and os.getenv(choice.env_key))


def _masked_key(provider: str) -> str:
    choice = _provider_choice(provider)
    if choice is None:
        return "not configured"
    masked = mask_secret(os.getenv(choice.env_key))
    return "not configured" if masked == "not set" else f"configured {masked}"


def _default_model(provider: str) -> str:
    info = AIProviderManager().get(provider)
    return info.default_model if info else provider
