"""Command parsing and routing."""

from __future__ import annotations

import logging
import os
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fincli.app.analysis.analyzer import build_market_analysis_prompt
from fincli.app.analysis.assistant_context import (
    build_fincli_assistant_prompt,
    coding_refusal,
    extract_market_symbols,
    get_conversation_history,
    is_coding_request,
)
from fincli.app.analysis.gameplay_plan import format_gameplay_context
from fincli.app.analysis.indicators import summarize_technical_indicators
from fincli.app.analysis.market_structure import analyze_market_structure
from fincli.app.analysis.technical_debate import run_technical_debate
from fincli.app.cli.handlers.common import (
    _fmt,
    _format_ai_response,
    _format_fundamental_context,
    _format_news_context,
    _interactive_prompt,
    _interactive_select,
)
from fincli.app.cli.result import CommandResult
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.services.data_trust import build_data_trust_gate
from fincli.app.services.market_overview import build_market_overview
from fincli.app.services.web_research import (
    build_web_research_context,
    should_use_web_research,
)
from fincli.app.storage.secrets import save_secret
from fincli.app.utils.errors import CommandError, FinCLIError
from fincli.app.utils.formatting import MarkdownBlock

logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


class IntelligenceCommands:
    """Intelligence command handlers."""

    def _ai_model(self, args: list[str]) -> CommandResult:
        con = Console()
        manager = AIProviderManager()
        current = self.config.settings

        if not args:
            return self._ai_model_interactive(manager, current, con)
        if args[0].lower() == "key":
            con.print("[dim]Hint: /ai_model key is deprecated. Use /ai_model for interactive picker.[/dim]")
            if len(args) < 3:
                raise CommandError("Format: /ai_model key <provider> <api_key>")
            provider = args[1].lower()
            info = manager.get(provider)
            if info is None:
                raise CommandError(f"Unknown AI provider: {provider}")
            save_secret(info.env_key, args[2])
            model = current.ai_model if current.ai_provider == provider else info.default_model
            self.config.set_ai_model(provider, model)
            self.ai_provider = manager.create(provider)
            return CommandResult(
                Panel(
                    (
                        f"AI API key for {provider} saved globally in ~/.fincli/secrets.env.\n"
                        f"Active provider saved: {provider} / {model}.\n"
                        "Key is not displayed in terminal and persists across sessions."
                    ),
                    title="AI API Key Saved",
                    border_style="green",
                )
            )
        # /ai_model <provider> — select provider with default model
        if len(args) == 1:
            provider = args[0].lower()
            info = manager.get(provider)
            if info is None:
                raise CommandError(
                    f"Unknown AI provider: {provider}. Use: {', '.join(p.name for p in manager.list_providers())}"
                )
            if not os.getenv(info.env_key):
                con.print(f"[yellow]API key {info.env_key} not set.[/yellow]")
                key_val = _interactive_prompt(f"Paste {info.env_key}", mask=True)
                if key_val:
                    save_secret(info.env_key, key_val)
                    con.print(f"[green]✓ {info.env_key} saved.[/green]")
                else:
                    raise CommandError("API key required. Try again with /ai_model.")
            self.config.set_ai_model(provider, info.default_model)
            self.ai_provider = manager.create(provider)
            return CommandResult(Panel(f"AI model active: {provider} / {info.default_model}", title="AI Model Updated"))
        # /ai_model <provider> <model> — direct set
        self.config.set_ai_model(args[0], args[1])
        self.ai_provider = manager.create(args[0])
        return CommandResult(Panel(f"AI model active: {args[0]} / {args[1]}", title="AI Model Updated"))

    def _ai_model_interactive(self, manager: AIProviderManager, current: Any, con: Console) -> CommandResult:
        """Interactive AI provider/model picker."""
        from fincli.app.tui.model_selector import MODEL_CATALOG

        providers = manager.list_providers()
        items = []
        for p in providers:
            has_key = "✓" if os.getenv(p.env_key) else "✗"
            label = f"{p.name:<15} [{has_key}] key {'configured' if has_key == '✓' else 'missing'}"
            items.append((p.name, label))

        selected_provider = _interactive_select(items, "Select AI Provider", current=current.ai_provider, console=con)
        if not selected_provider:
            return CommandResult(Panel("Cancelled.", title="AI Model"))

        info = manager.get(selected_provider)
        if info is None:
            raise CommandError(f"Unknown provider: {selected_provider}")

        # Prompt for API key if missing
        if not os.getenv(info.env_key):
            con.print(f"\n[yellow]API key [bold]{info.env_key}[/bold] not set for {selected_provider}.[/yellow]")
            key_val = _interactive_prompt(f"Paste {info.env_key}", mask=True)
            if key_val:
                save_secret(info.env_key, key_val)
                con.print(f"[green]✓ {info.env_key} saved.[/green]")
            else:
                con.print("[dim]Skip API key. Provider may not work without key.[/dim]")

        # Show model picker
        models = MODEL_CATALOG.get(selected_provider, ())
        if models:
            model_items = [(m.model, f"{m.label:<30} {m.context}" if m.context else m.label) for m in models]
            selected_model = _interactive_select(
                model_items, f"Select Model ({selected_provider})", current=current.ai_model, console=con
            )
            if not selected_model:
                selected_model = info.default_model
                con.print(f"[dim]Using default: {selected_model}[/dim]")
        else:
            selected_model = info.default_model
            con.print(f"[dim]No model catalog for {selected_provider}. Using default: {selected_model}[/dim]")

        self.config.set_ai_model(selected_provider, selected_model)
        self.ai_provider = manager.create(selected_provider)
        return CommandResult(
            Panel(
                f"AI model active: [bold]{selected_provider}[/bold] / [cyan]{selected_model}[/cyan]",
                title="AI Model Updated",
                border_style="green",
            )
        )

    def _ai(self, args: list[str]) -> CommandResult:
        if not args:
            # Show AI assistant status (merged from /assistant)
            provider_name = self.config.settings.ai_provider
            model = self.config.settings.ai_model
            ai_mgr = AIProviderManager()
            provider_info = ai_mgr.get(provider_name)
            has_key = bool(os.getenv(provider_info.env_key)) if provider_info else False

            table = Table(title="AI Assistant Status", show_header=False, border_style="cyan")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Provider", provider_name)
            table.add_row("Model", model)
            table.add_row("API Key", "✓ configured" if has_key else "✗ not set")
            if not has_key:
                table.add_row("Setup", f"/ai_model key {provider_name} <api_key>")
            table.add_row("Version", "v1.1.0")
            return CommandResult(table)

        prompt = " ".join(args)
        if is_coding_request(prompt):
            response = AIResponse(provider="fincli", model="local-policy", content=coding_refusal())
            return CommandResult(_format_ai_response(response))

        market_context = self._freechat_market_context(prompt)
        web_context = self._freechat_web_context(prompt)
        if web_context:
            market_context = f"{market_context}\n\n{web_context}".strip()

        # Check AI cache first
        model = self.config.settings.ai_model
        cached_response = self.ai_cache.get(prompt, model, market_context)
        if cached_response:
            response = AIResponse(provider="cache", model=model, content=cached_response)
            return CommandResult(_format_ai_response(response))

        # Use conversation history for context
        history = get_conversation_history()
        assistant_prompt = build_fincli_assistant_prompt(prompt, market_context, history)
        request = AIRequest(prompt=assistant_prompt, model=model)
        response = self._run_async(self.ai_provider.complete(request))
        if not isinstance(response, AIResponse):
            raise CommandError("AI provider returned invalid data.")

        # Cache the response
        if response.content:
            self.ai_cache.set(prompt, model, response.content, market_context)

        # Store in conversation history
        history.add(prompt, response.content[:500] if response.content else "")

        return CommandResult(_format_ai_response(response))

    def _analyze(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /analyze <symbol> [timeframe]")
        symbol = args[0].upper()
        timeframe = args[1] if len(args) >= 2 else "1d"
        candles = self._run_async(self.market_service.history(symbol, period="6mo", interval=timeframe))
        if not candles:
            raise CommandError(f"Market data is empty for {symbol}.")
        technical = summarize_technical_indicators(candles)
        structure = analyze_market_structure(candles)
        news_context = self._analysis_context(symbol)
        gameplay_context = format_gameplay_context(self.user_profiles.get(), symbol)
        grounding_context = self._ai_grounding_context(symbol, timeframe)
        prompt = build_market_analysis_prompt(
            symbol,
            timeframe,
            candles,
            technical,
            structure,
            news_context,
            gameplay_context,
            grounding_context=grounding_context,
        )
        request = AIRequest(prompt=prompt, model=self.config.settings.ai_model)
        response = self._run_async(self.ai_provider.complete(request))
        if not isinstance(response, AIResponse):
            raise CommandError("AI provider returned invalid data.")
        return CommandResult(
            MarkdownBlock(
                f"AI Market Analysis: {symbol}", _format_ai_response(response), "Disclaimer: bukan nasihat keuangan."
            )
        )

    def _analysis_context(self, symbol: str) -> str:
        sections: list[str] = []
        try:
            news_items = self._run_async(self.market_service.news(symbol, limit=3))
            sections.append(_format_news_context(news_items))
        except (FinCLIError, AttributeError) as exc:
            sections.append(f"News unavailable: {exc}")
        try:
            fundamentals = self._run_async(self.market_service.fundamentals(symbol))
            sections.append(_format_fundamental_context(fundamentals))
        except (FinCLIError, AttributeError) as exc:
            sections.append(f"Fundamentals unavailable: {exc}")
        return "\n\n".join(sections)

    def _ai_grounding_context(self, symbol: str, timeframe: str) -> str:
        try:
            overview = self._run_async(build_market_overview(symbol, self.market_service, timeframe))
            quality = overview.data_quality
            missing = ", ".join(quality.missing_fields) if quality.missing_fields else "none"
            quality_text = (
                f"Data Quality: {quality.score}/100 | tier={quality.tier} | freshness={quality.freshness}\n"
                f"Provider Reliability: {quality.reliability_status} | provider={quality.provider}\n"
                f"Missing Data: {missing}"
            )
            gate = build_data_trust_gate(quality, self.market_service.provider_metrics_snapshot())
            gate_text = gate.prompt_context()
        except FinCLIError as exc:
            quality_text = (
                "Data Quality: unavailable\n"
                "Provider Reliability: unavailable\n"
                f"Missing Data: market overview unavailable ({exc})"
            )
            gate_text = (
                "Data Trust Gate:\n"
                "- Trust Level: blocked\n"
                "- AI Action: no_directional_signal\n"
                "- Confidence Cap: 20%\n"
                "- Max Signal Strength: caution only\n"
                "- Reasons: market overview unavailable\n"
                "- Required Verification: provider data availability"
            )

        metric_lines = []
        for provider in self.market_service.providers:
            metric = self.market_service.provider_metrics_snapshot().get(provider.name)
            if metric is None:
                metric_lines.append(f"- {provider.name}: calls=0; success_rate=0.00%; errors=0; fallbacks=0")
            else:
                metric_lines.append(
                    f"- {provider.name}: calls={metric.calls}; success_rate={metric.success_rate:.2f}%; "
                    f"errors={metric.errors}; fallbacks={metric.fallbacks}; avg_latency={metric.avg_latency_ms:.2f}ms"
                )
        return f"{quality_text}\n{gate_text}\nProvider Metrics:\n" + "\n".join(metric_lines)

    def _freechat_market_context(self, prompt: str) -> str:
        symbols = extract_market_symbols(prompt)
        if not symbols:
            return ""

        sections = [
            "FinCLI provider chain: "
            + ", ".join(provider.name for provider in self.market_service.providers)
            + ". Realtime status depends on the active provider and API key."
        ]
        for symbol in symbols:
            sections.append(self._symbol_freechat_context(symbol))
        return "\n\n".join(sections)

    def _freechat_web_context(self, prompt: str) -> str:
        if not should_use_web_research(prompt):
            return ""
        cache_key = f"web:{prompt.lower()[:180]}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, str):
            return cached
        try:
            results = self._run_async(self.web_research.research(prompt, limit=3))
        except FinCLIError as exc:
            return f"Web Research: unavailable ({exc})"
        context = build_web_research_context(results)
        self.cache.set(cache_key, context)
        return context

    def _symbol_freechat_context(self, symbol: str) -> str:
        lines = [f"Symbol: {symbol}"]
        try:
            quote = self._get_quote(symbol)
            lines.append(
                f"Quote: price={_fmt(quote.price)} {quote.currency}; provider={quote.provider}; "
                f"status={quote.status}; timestamp={quote.timestamp.isoformat(timespec='seconds')}"
            )
        except (FinCLIError, AttributeError, ValueError) as exc:
            lines.append(f"Quote: unavailable ({exc})")

        try:
            candles = self._run_async(self.market_service.history(symbol, period="6mo", interval="1d"))
            if candles:
                technical = summarize_technical_indicators(candles)
                structure = analyze_market_structure(candles)
                debate = run_technical_debate(technical, structure, candles)
                signal = debate.judge_signal
                lines.extend(
                    [
                        f"OHLCV: {len(candles)} daily candles available.",
                        (
                            "Technical: "
                            f"close={_fmt(technical.latest_close)}; trend={technical.trend_bias}; "
                            f"RSI={_fmt(technical.rsi)}; MACD={_fmt(technical.macd)}/{_fmt(technical.macd_signal)}; "
                            f"support={_fmt(technical.support)}; resistance={_fmt(technical.resistance)}; "
                            f"ATR={_fmt(technical.atr)}"
                        ),
                        (
                            "Structure: "
                            f"trend={structure.trend}; pattern={structure.latest_pattern}; "
                            f"BOS={structure.break_of_structure}; CHoCH={structure.change_of_character}; "
                            f"liquidity={structure.liquidity_area or 'N/A'}; risk_zone={structure.risk_zone or 'N/A'}"
                        ),
                        (
                            "Debate Signal: "
                            f"{signal.label}; confidence={signal.confidence}; score={signal.score}; "
                            f"judge_reasoning={'; '.join(debate.judge_reasoning[:2])}"
                        ),
                    ]
                )
            else:
                lines.append("OHLCV: unavailable (provider returned no candles).")
        except (FinCLIError, AttributeError, ValueError) as exc:
            lines.append(f"OHLCV/Technical: unavailable ({exc})")

        try:
            fundamentals = self._run_async(self.market_service.fundamentals(symbol))
            lines.append(
                "Fundamentals: "
                f"provider={fundamentals.provider}; market_cap={_fmt(fundamentals.market_cap)}; "
                f"pe={_fmt(fundamentals.pe_ratio)}; eps={_fmt(fundamentals.eps)}; "
                f"revenue={_fmt(fundamentals.revenue)}; sector={fundamentals.sector or 'N/A'}; "
                f"industry={fundamentals.industry or 'N/A'}"
            )
        except (FinCLIError, AttributeError, ValueError) as exc:
            lines.append(f"Fundamentals: unavailable ({exc})")

        try:
            news_items = self._run_async(self.market_service.news(symbol, limit=3))
            if news_items:
                lines.append("News:")
                for item in news_items:
                    published = item.published_at.isoformat(timespec="seconds") if item.published_at else "unknown time"
                    summary = f" - {item.summary}" if item.summary else ""
                    lines.append(f"- {item.title} ({item.source}, {published}){summary}")
            else:
                lines.append("News: no recent items from active provider.")
        except (FinCLIError, AttributeError, ValueError) as exc:
            lines.append(f"News: unavailable ({exc})")

        return "\n".join(lines)
