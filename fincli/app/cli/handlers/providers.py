"""Command parsing and routing."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel

from fincli.app.cli.handlers.common import (
    _extract_option_value,
    _format_circuit_status,
    _format_news_connectors,
    _format_provider_capabilities,
    _format_provider_compare,
    _format_provider_entitlements,
    _format_provider_key_status,
    _format_provider_list,
    _format_provider_metrics,
    _format_provider_trust,
    _format_quote,
    _format_symbol_matrix,
    _format_symbol_search,
    _interactive_prompt,
    _interactive_select,
    _market_provider_secret_keys,
)
from fincli.app.cli.result import CommandResult
from fincli.app.connectors.news_connectors import (
    news_connector_secret_key,
)
from fincli.app.providers.market.symbols import search_symbol_catalog
from fincli.app.services.market_data import MarketDataService
from fincli.app.storage.secrets import save_secret
from fincli.app.utils.errors import CommandError, FinCLIError

if TYPE_CHECKING:
    from fincli.app.providers.market.base import (
        BaseMarketProvider,
    )


logger = logging.getLogger(__name__)

# Constants
PROVIDER_TIMEOUT_BUFFER_SECONDS = 15.0


class ProvidersCommands:
    """Providers command handlers."""

    def _news_model(self, args: list[str]) -> CommandResult:
        con = Console()
        current = self.config.settings

        if not args:
            return self._news_model_interactive(current, con)

        action = args[0].lower()
        if action == "list":
            return CommandResult(_format_news_connectors(self.news_connector_catalog.free_first()[:120], "all"))
        if action == "search":
            query = " ".join(args[1:]).strip()
            if not query:
                raise CommandError("Format: /news_model search <query>")
            return CommandResult(_format_news_connectors(self.news_connector_catalog.search(query), query))
        if action == "priority":
            if len(args) < 2:
                raise CommandError("Format: /news_model priority google_news_rss,yfinance,marketaux")
            providers = [provider.strip().lower() for provider in args[1].split(",") if provider.strip()]
            self._validate_news_providers(providers)
            self.config.set_news_provider_priority(providers)
            return CommandResult(
                Panel(
                    f"News fallback priority saved: {', '.join(self.config.settings.news_provider_priority)}",
                    title="News Priority Updated",
                    border_style="green",
                )
            )
        if action == "use":
            if len(args) < 2:
                raise CommandError("Format: /news_model use <provider>")
            provider = args[1].lower()
            self._validate_news_providers([provider])
            current_prio = [item for item in self.config.settings.news_provider_priority if item != provider]
            self.config.set_news_provider_priority([provider, *current_prio])
            return CommandResult(
                Panel(
                    f"News primary provider: {provider}\nFallback: {', '.join(self.config.settings.news_provider_priority)}",
                    title="News Provider Updated",
                    border_style="green",
                )
            )
        if action == "key":
            con.print("[dim]Hint: /news_model key is deprecated. Use /news_model for interactive picker.[/dim]")
            if len(args) < 3:
                raise CommandError("Format: /news_model key <provider> <api_key> [base_url for custom]")
            provider = args[1].lower()
            env_key = news_connector_secret_key(provider)
            env_keys = (env_key,) if env_key else _market_provider_secret_keys(provider)
            if not env_keys:
                raise CommandError(f"Provider {provider} does not require an API key or is unknown.")
            save_secret(env_keys[0], args[2])
            if provider == "custom_news" and len(args) >= 4:
                save_secret("CUSTOM_NEWS_BASE_URL", args[3])
            elif provider == "custom" and len(args) >= 4:
                save_secret("MARKET_DATA_BASE_URL", args[3])
            if self.market_manager.get(provider) is not None:
                self.config.set_market_provider_priority([provider, *self._priority_tail(provider)])
                self.config.set_news_provider(provider)
                self._refresh_market_service()
            else:
                self.config.set_news_provider_priority([provider, *self._news_priority_tail(provider)])
            self.cache.clear()
            extra = "\nCustom base URL also saved." if provider in {"custom", "custom_news"} and len(args) >= 4 else ""
            return CommandResult(
                Panel(
                    (
                        f"Market/news API key for {provider} saved globally in ~/.fincli/secrets.env.{extra}\n"
                        f"Active news provider saved: {provider}.\n"
                        "Key is not displayed in terminal and persists across sessions."
                    ),
                    title="News API Key Saved",
                    border_style="green",
                )
            )
        # /news_model <provider> — select directly
        provider = args[0].lower()
        return self._news_model_select_provider(provider, con)

    def _news_model_interactive(self, current: Any, con: Console) -> CommandResult:
        """Interactive market/news provider picker."""
        # Build provider list: market providers + free RSS connectors
        providers = self.market_manager.list_providers()
        items: list[tuple[str, str]] = []
        for p in providers:
            env_keys = _market_provider_secret_keys(p.name)
            if env_keys:
                has_key = "✓" if any(os.getenv(k) for k in env_keys) else "✗"
                label = f"{p.name:<15} [{has_key}] key {'configured' if has_key == '✓' else 'missing'}  ({p.status})"
            else:
                label = f"{p.name:<15} [free] no key needed  ({p.status})"
            items.append((p.name, label))

        # Add top RSS connectors
        items.append(("", "[dim]── RSS (no key) ──[/dim]"))
        rss_connectors = self.news_connector_catalog.free_first()[:8]
        for spec in rss_connectors:
            if spec.access == "free":
                items.append((spec.slug, f"  {spec.slug:<25} {spec.name}"))

        chain = ", ".join(current.news_provider_priority or [current.news_provider])
        con.print(
            f"\n[dim]Current: market={current.market_provider}, news={current.news_provider}, priority={chain}[/dim]"
        )

        selected = _interactive_select(
            items, "Select Market/News Provider", current=current.market_provider, console=con
        )
        if not selected:
            return CommandResult(Panel("Cancelled.", title="News Model"))

        return self._news_model_select_provider(selected, con)

    def _news_model_select_provider(self, provider: str, con: Console) -> CommandResult:
        """Select a news/market provider, prompting for API key if needed."""
        # Check if it's a market provider
        if self.market_manager.get(provider) is not None:
            env_keys = _market_provider_secret_keys(provider)
            if env_keys and not any(os.getenv(k) for k in env_keys):
                con.print(f"\n[yellow]API key not set for [bold]{provider}[/bold].[/yellow]")
                for key in env_keys:
                    if key.endswith("_BASE_URL"):
                        val = _interactive_prompt(f"Paste {key} (URL)")
                    else:
                        val = _interactive_prompt(f"Paste {key}", mask=True)
                    if val:
                        save_secret(key, val)
                        con.print(f"[green]✓ {key} saved.[/green]")
                    else:
                        con.print(f"[dim]Skipped {key}.[/dim]")
            self.config.set_market_provider(provider)
            self.config.set_news_provider(provider)
            self.config.set_market_provider_priority([provider, *self._priority_tail(provider)])
            self._refresh_market_service()
            self.cache.clear()
            return CommandResult(
                Panel(
                    f"Active market/news provider: [bold]{provider}[/bold]",
                    title="Provider Updated",
                    border_style="green",
                )
            )

        # Check if it's a news connector
        env_key = news_connector_secret_key(provider)
        env_keys = (env_key,) if env_key else ()
        if env_keys and not any(os.getenv(k) for k in env_keys):
            con.print(f"\n[yellow]API key not set for [bold]{provider}[/bold].[/yellow]")
            for key in env_keys:
                val = _interactive_prompt(f"Paste {key}", mask=True)
                if val:
                    save_secret(key, val)
                    con.print(f"[green]✓ {key} saved.[/green]")
                else:
                    con.print(f"[dim]Skipped {key}.[/dim]")

        self._validate_news_providers([provider])
        self.config.set_news_provider_priority([provider, *self._news_priority_tail(provider)])
        self.cache.clear()
        return CommandResult(
            Panel(f"Active news provider: [bold]{provider}[/bold]", title="News Provider Updated", border_style="green")
        )

    def _provider(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "list":
            return CommandResult(_format_provider_list())
        if args and args[0].lower() in {"entitlement", "entitlements"}:
            return CommandResult(_format_provider_entitlements(self.market_manager.entitlements()))
        if args and args[0].lower() == "metrics":
            return CommandResult(_format_provider_metrics(self.market_service))
        if args and args[0].lower() == "trust":
            return CommandResult(_format_provider_trust(self.market_service))
        if args and args[0].lower() in {"capabilities", "capability", "matrix"}:
            return CommandResult(_format_provider_capabilities(self.market_service.providers))
        if args and args[0].lower() == "key" and len(args) >= 2 and args[1].lower() == "status":
            return CommandResult(_format_provider_key_status(self.market_manager))
        if args and args[0].lower() == "key" and len(args) >= 3 and args[1].lower() == "rotate":
            provider = args[2].lower()
            from fincli.app.storage.secrets import read_secrets

            secret_keys = {
                "finnhub": "FINNHUB_API_KEY",
                "twelvedata": "TWELVE_DATA_API_KEY",
                "alphavantage": "ALPHA_VANTAGE_API_KEY",
                "polygon": "POLYGON_API_KEY",
                "iex": "IEX_CLOUD_API_KEY",
                "custom": "MARKET_DATA_API_KEY",
            }
            key_name = secret_keys.get(provider)
            if not key_name:
                raise CommandError(f"Unknown provider: '{provider}'. Use: {', '.join(secret_keys)}")
            old_secrets = read_secrets()
            old_value = old_secrets.get(key_name, "")
            if old_value:
                masked = f"{old_value[:4]}...{old_value[-2:]}" if len(old_value) > 6 else "***"
                return CommandResult(
                    Panel(
                        f"Key for {provider} already exists: {masked}\nUse /secrets clear first, then /news_model key {provider} <new_key>.",
                        title="Key Rotate",
                        border_style="yellow",
                    )
                )
            return CommandResult(
                Panel(
                    f"No key set for {provider}. Use /news_model key {provider} <api_key> to save.",
                    title="Key Rotate",
                    border_style="yellow",
                )
            )
        if args and args[0].lower() == "use":
            if len(args) < 2:
                raise CommandError("Format: /provider use <provider>")
            provider = args[1].lower()
            self.config.set_market_provider_priority([provider, *self._priority_tail(provider)])
            self._refresh_market_service()
            self.cache.clear()
            return CommandResult(Panel(f"Active market provider: {provider}", title="Provider Updated"))
        if args and args[0].lower() == "priority":
            if len(args) < 2:
                raise CommandError("Format: /provider priority finnhub,yfinance")
            providers = [provider.strip() for provider in args[1].split(",") if provider.strip()]
            self.config.set_market_provider_priority(providers)
            self._refresh_market_service()
            self.cache.clear()
            return CommandResult(Panel(f"Provider priority: {', '.join(providers)}", title="Provider Priority"))
        if args and args[0].lower() == "reset":
            if len(args) < 2:
                raise CommandError("Format: /provider reset <provider_name>")
            provider_name = args[1].lower()
            if self.market_service.reset_circuit(provider_name):
                return CommandResult(
                    Panel(f"Circuit breaker for {provider_name} reset.", title="Circuit Reset", border_style="green")
                )
            return CommandResult(
                Panel(f"Provider '{provider_name}' not found in metrics.", title="Circuit Reset", border_style="red")
            )
        if args and args[0].lower() == "status":
            settings = self.config.settings
            provider_status = self._provider_health_text()
            circuit_text = _format_circuit_status(self.market_service)
            text = (
                f"Market provider: {settings.market_provider} (active: {self.market_provider.name})\n"
                f"News provider  : {settings.news_provider} (active: {self.market_provider.name} fallback)\n"
                f"Provider chain : {', '.join(provider.name for provider in self.market_service.providers)}\n"
                f"AI provider    : {settings.ai_provider} (active: {self.ai_provider.name})\n"
                f"{provider_status}\n\n{circuit_text}"
            )
            return CommandResult(Panel(text, title="Provider Status", border_style="yellow"))
        if args and args[0].lower() == "test":
            if len(args) < 2:
                raise CommandError("Format: /provider test [provider] <symbol>")
            if len(args) >= 3:
                provider = self.market_manager.create(args[1])
                quote = self.market_service.run(provider.quote(args[2]))
            else:
                quote = self._get_quote(args[1])
            return CommandResult(_format_quote(quote))
        if args and args[0].lower() == "compare":
            if len(args) < 2:
                raise CommandError("Format: /provider compare <symbol>")
            return self._provider_compare(args[1])
        raise CommandError(
            "Format: /provider status, /provider trust, /provider list, /provider capabilities, /provider entitlement, /provider key status, "
            "/provider use <provider>, /provider priority finnhub,yfinance, /provider reset <provider>, "
            "/provider test [provider] <symbol>, /provider compare <symbol>"
        )

    def _symbol(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError(
                "Format: /symbol search <query>, /symbol resolve <symbol> [--asset <class>], /symbol normalize <symbol>"
            )
        action = args[0].lower()
        if action in {"resolve", "normalize", "norm"}:
            if len(args) < 2:
                raise CommandError("Format: /symbol resolve <symbol> [--asset <class>]")
            asset_class = _extract_option_value(args[2:], "--asset")
            return CommandResult(_format_symbol_matrix(args[1], self.symbol_resolver, asset_class=asset_class))
        if action == "search":
            if len(args) < 2:
                raise CommandError("Format: /symbol search <query>")
            query = " ".join(args[1:])
        else:
            query = " ".join(args)
        results = search_symbol_catalog(query)
        return CommandResult(_format_symbol_search(query, results))

    def _provider_health_text(self) -> str:
        try:
            status = self._run_async(self.market_service.status())
            base = (
                f"Provider health: {status.status}\n"
                f"Provider realtime: {status.realtime}\n"
                f"Provider message: {status.message}"
            )
        except (FinCLIError, AttributeError) as exc:
            base = f"Provider health: unavailable ({exc})"

        results = list(getattr(self.market_service, "provider_results", []))[-6:]
        if not results:
            return f"{base}\nRecent provider results: none"
        lines = ["Recent provider results:"]
        for result in results:
            missing = f"; missing={', '.join(result.missing_fields)}" if result.missing_fields else ""
            message = f"; {result.message}" if result.message and result.message != "ok" else ""
            lines.append(f"- {result.provider}.{result.operation}: {result.status}{missing}{message}")
        return f"{base}\n" + "\n".join(lines)

    def _provider_compare(self, symbol: str) -> CommandResult:
        """Compare quote from all available providers."""
        from time import monotonic

        results: list[dict[str, object]] = []
        for provider in self.market_service.providers:
            start = monotonic()
            try:
                quote = self._run_async(provider.quote(symbol))
                elapsed = (monotonic() - start) * 1000
                results.append(
                    {
                        "provider": provider.name,
                        "price": quote.price,
                        "currency": quote.currency,
                        "status": quote.status,
                        "latency_ms": elapsed,
                        "error": None,
                    }
                )
            except Exception as exc:
                elapsed = (monotonic() - start) * 1000
                results.append(
                    {
                        "provider": provider.name,
                        "price": None,
                        "currency": "-",
                        "status": "error",
                        "latency_ms": elapsed,
                        "error": str(exc)[:50],
                    }
                )
        return CommandResult(_format_provider_compare(symbol, results))

    def _build_market_service(self, injected_provider: BaseMarketProvider | None = None) -> MarketDataService:
        if injected_provider is not None:
            return MarketDataService(
                [injected_provider],
                cache=self.market_cache,
                cache_ttl_seconds=self.config.settings.cache_ttl_seconds,
                provider_timeout_seconds=self.config.settings.provider_timeout_seconds,
                metrics_store=self.provider_metrics_store,
                symbol_resolver=self.symbol_resolver,
                circuit_breaker_failure_threshold=self.config.settings.provider_circuit_breaker_failure_threshold,
                circuit_breaker_cooldown_seconds=self.config.settings.provider_circuit_breaker_cooldown_seconds,
            )
        priority = self.config.settings.market_provider_priority or [self.config.settings.market_provider]
        return MarketDataService(
            self.market_manager.create_many(priority),
            cache=self.market_cache,
            cache_ttl_seconds=self.config.settings.cache_ttl_seconds,
            provider_timeout_seconds=self.config.settings.provider_timeout_seconds,
            metrics_store=self.provider_metrics_store,
            symbol_resolver=self.symbol_resolver,
            circuit_breaker_failure_threshold=self.config.settings.provider_circuit_breaker_failure_threshold,
            circuit_breaker_cooldown_seconds=self.config.settings.provider_circuit_breaker_cooldown_seconds,
        )

    def _refresh_market_service(self) -> None:
        self.market_service = self._build_market_service()
        self.market_provider = self.market_service.primary_provider

    def _priority_tail(self, active_provider: str) -> list[str]:
        active = active_provider.lower()
        existing = self.config.settings.market_provider_priority or ["yfinance"]
        tail = [provider for provider in existing if provider != active]
        if active != "yfinance" and "yfinance" not in tail:
            tail.append("yfinance")
        return tail

    def _news_priority_tail(self, active_provider: str) -> list[str]:
        active = active_provider.lower()
        existing = self.config.settings.news_provider_priority or ["yfinance", "google_news_rss", "yahoo_finance_rss"]
        tail = [provider for provider in existing if provider != active]
        if active != "yfinance" and "yfinance" not in tail:
            tail.append("yfinance")
        if active != "google_news_rss" and "google_news_rss" not in tail:
            tail.append("google_news_rss")
        return tail

    def _validate_news_providers(self, providers: list[str]) -> None:
        market_names = {provider.name for provider in self.market_service.providers}
        known = {"yfinance", *market_names}
        known.update(connector.slug for connector in self.news_connector_catalog.all())
        unknown = [provider for provider in providers if provider not in known]
        if unknown:
            raise CommandError(
                f"Unknown news provider: {', '.join(unknown)}",
                "Use /news_model list or /news_model search <query> to see available providers.",
            )
