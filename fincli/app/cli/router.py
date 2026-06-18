"""Command parsing and routing."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
import io
import os
import shlex
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fincli.app.cli.commands import CommandRegistry
from fincli.app.analysis.analyzer import build_market_analysis_prompt, build_technical_ai_summary
from fincli.app.analysis.backtest import BacktestResult, run_backtest
from fincli.app.analysis.gameplay_plan import format_gameplay_context
from fincli.app.agents.registry import Agent, AgentRegistry
from fincli.app.analysis.assistant_context import (
    build_web_research_answer_prompt,
    build_fincli_assistant_prompt,
    coding_refusal,
    extract_market_symbols,
    is_coding_request,
)
from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.analysis.market_structure import MarketStructureSummary, analyze_market_structure
from fincli.app.analysis.multi_timeframe import MultiTimeframeAnalysis, analyze_multi_timeframe
from fincli.app.analysis.technical_debate import TechnicalDebate, format_debate, run_technical_debate
from fincli.app.analysis.technical_signal import TechnicalSignal, format_signal
from fincli.app.modules.economic_calendar import (
    EconomicCalendarService,
    EconomicEvent,
    PublicEconomicCalendarService,
    calendar_summary,
    default_calendar_window,
    economic_event_rows,
    fallback_events,
    filter_events,
)
from fincli.app.modules.alerts import AlertCheckResult, AlertService, evaluate_alert
from fincli.app.modules.exporter import export_rows
from fincli.app.modules.journal_analytics import JournalStats, build_journal_review_prompt, calculate_journal_stats
from fincli.app.modules.journal import JournalService
from fincli.app.modules.portfolio import PortfolioService
from fincli.app.modules.portfolio_risk import PortfolioRiskReport, build_portfolio_risk
from fincli.app.modules.scanner import ScanResult, scan_symbols
from fincli.app.modules.session_history import SessionHistoryService
from fincli.app.modules.transactions import TransactionService
from fincli.app.modules.trading import (
    BrokerCatalog,
    BrokerIntegration,
    PaperTradingEngine,
    RealtimeConnector,
    RealtimeConnectorCatalog,
)
from fincli.app.modules.algo_engine import StrategyInfo
from fincli.app.modules.user_profile import UserProfile, UserProfileService
from fincli.app.modules.watchlist import WatchlistService
from fincli.app.connectors.catalog import Connector, ConnectorCatalog
from fincli.app.connectors.news_connectors import (
    NewsConnectorCatalog,
    NewsConnectorManager,
    NewsConnectorSpec,
    news_connector_secret_key,
)
from fincli.app.diagnostics.capabilities import capability_rows, capability_summary
from fincli.app.diagnostics.runtime import check_runtime_environment
from fincli.app.modules.reports import write_market_report
from fincli.app.providers.ai.base import AIRequest, AIResponse, BaseAIProvider
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.providers.market.base import (
    BaseMarketProvider,
    FundamentalSnapshot,
    NewsItem,
    ProviderEntitlement,
    Quote,
    SymbolSearchResult,
)
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.providers.market.symbols import SymbolResolver, search_symbol_catalog
from fincli.app.providers.market.yfinance_provider import YahooTable, YFinanceProvider
from fincli.app.providers.reliability import (
    STATUS_OK,
    STATUS_PARTIAL_DATA,
    STATUS_SCHEDULE_ONLY,
    STATUS_UNAVAILABLE,
)
from fincli.app.plugins.loader import PluginLoader, PluginManifest
from fincli.app.services.market_data import MarketDataService
from fincli.app.services.market_overview import MarketOverview, build_market_overview
from fincli.app.services.data_quality import DataQualityReport
from fincli.app.services.data_trust import build_data_trust_gate
from fincli.app.services.macro_data import MacroDataService, MacroIndicator
from fincli.app.services.news_aggregator import NewsAggregator, NewsDesk
from fincli.app.services.web_research import (
    WebResearchService,
    WebSearchResult,
    build_web_research_context,
    should_use_web_research,
)
from fincli.app.research import ResearchEngine, format_research_brief, write_research_report
from fincli.app.storage.cache import TTLCache
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.market_cache import MarketCache
from fincli.app.storage.provider_metrics import ProviderMetricsStore
from fincli.app.storage.secrets import clear_secrets, read_secrets, save_secret
from fincli.app.storage.audit_log import SecurityAuditLog, EVENT_SECRET_SAVE, EVENT_SECRET_CLEAR, EVENT_PRIVACY_PURGE, EVENT_EXPORT_DATA, EVENT_SECURITY_VIOLATION
from fincli.app.utils.security import SecurityValidator, SecretRedactor, RateLimiter
from fincli.app.utils.errors import CommandError, FinCLIError, SecurityError
from fincli.app.utils.formatting import AIResponseView, MarkdownBlock, semantic_text


@dataclass(slots=True)
class CommandResult:
    renderable: Any
    status: str = "ready"
    clear: bool = False
    should_exit: bool = False


class CommandRouter:
    """Route slash commands to services."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        db: FinCLIDatabase | None = None,
        registry: CommandRegistry | None = None,
        market_provider: BaseMarketProvider | None = None,
        ai_provider: BaseAIProvider | None = None,
    ) -> None:
        self.config = config or ConfigManager()
        self.db = db or FinCLIDatabase()
        self.registry = registry or CommandRegistry()
        self.cache: TTLCache[object] = TTLCache(self.config.settings.cache_ttl_seconds)
        self.market_cache = MarketCache(self.db)
        self.provider_metrics_store = ProviderMetricsStore(self.db)
        self.market_manager = MarketProviderManager()
        self.symbol_resolver = SymbolResolver()
        self.market_service = self._build_market_service(market_provider)
        self.market_provider = self.market_service.primary_provider
        self.ai_provider = ai_provider or AIProviderManager().create(self.config.settings.ai_provider)
        self.watchlist = WatchlistService(self.db)
        self.portfolio = PortfolioService(self.db)
        self.alerts = AlertService(self.db)
        self.transactions = TransactionService(self.db, self.portfolio)
        self.paper_trading = PaperTradingEngine(self.db)
        self.broker_catalog = BrokerCatalog()
        self.realtime_connector_catalog = RealtimeConnectorCatalog()
        self.journal = JournalService(self.db)
        self.user_profiles = UserProfileService(self.db)
        self.history = SessionHistoryService(self.db)
        self.session_id = self.history.start_session()
        self.web_research = WebResearchService()
        self.macro_data = MacroDataService()
        self.agent_registry = AgentRegistry()
        self.connector_catalog = ConnectorCatalog()
        self.news_connector_catalog = NewsConnectorCatalog()
        self.news_connectors = NewsConnectorManager(self.news_connector_catalog)
        self.security_validator = SecurityValidator()
        self.secret_redactor = SecretRedactor()
        self.rate_limiter = RateLimiter()
        self.audit_log = SecurityAuditLog(self.db)

    def route(self, raw: str) -> CommandResult:
        if not isinstance(raw, str):
            return CommandResult(
                Panel("Command harus berupa teks. Contoh: /help", title="Error", border_style="red"),
                status="error",
            )
        result = self._route(raw)
        self._record_history(raw, result)
        return result

    def _route(self, raw: str) -> CommandResult:
        raw = raw.strip()
        if not raw:
            return CommandResult(Panel("Ketik /help untuk melihat command.", title="FinCLI"))
        if not raw.startswith("/"):
            return CommandResult(
                Panel("Command harus diawali slash. Contoh: /help", title="Invalid Input", border_style="red"),
                status="error",
            )

        try:
            if raw.lower().startswith("/export "):
                export_parts = raw.split(maxsplit=3)
                if len(export_parts) == 4:
                    return self._export(export_parts[1:])

            parts = _split_command(raw)
            if not parts:
                raise CommandError("Command kosong.")

            root = parts[0].lower()
            args = parts[1:]

            if root == "/help":
                return CommandResult(self._help_table())
            if root == "/dashboard":
                return CommandResult(self._dashboard())
            if root == "/clear":
                return CommandResult("", clear=True)
            if root == "/exit":
                return CommandResult("Keluar dari FinCLI.", should_exit=True)
            if root == "/config":
                return CommandResult(self._config_panel())
            if root == "/history":
                return self._history(args)
            if root == "/ai_model":
                return self._ai_model(args)
            if root == "/news_model":
                return self._news_model(args)
            if root == "/provider":
                return self._provider(args)
            if root == "/symbol":
                return self._symbol(args)
            if root == "/research":
                return self._research(args)
            if root == "/macro":
                return self._macro(args)
            if root in {"/cpi", "/nfp", "/gdp", "/inflation", "/unemployment"}:
                return self._macro_indicator(root[1:], args)
            if root == "/fed" and args and args[0].lower() == "funds":
                return self._macro_indicator("fed_funds", args[1:])
            if root == "/profile":
                return self._profile(args)
            if root == "/doctor":
                return self._doctor(args)
            if root == "/setup":
                return self._setup(args)
            if root == "/tutorial":
                return self._tutorial(args)
            if root == "/secrets":
                return self._secrets(args)
            if root == "/security":
                return self._security(args)
            if root == "/privacy":
                return self._privacy(args)
            if root == "/agent":
                return self._agent(args)
            if root == "/connector":
                return self._connector(args)
            if root == "/plugin":
                return self._plugin(args)
            if root == "/cache":
                return self._cache(args)
            if root == "/watchlist":
                return self._watchlist(args)
            if root == "/portfolio":
                return self._portfolio(args)
            if root == "/tx":
                return self._tx(args)
            if root == "/journal":
                return self._journal(args)
            if root == "/alert":
                return self._alert(args)
            if root == "/quote":
                return self._quote(args)
            if root == "/market":
                return self._market(args)
            if root == "/technical":
                return self._technical(args)
            if root == "/mtf":
                return self._mtf(args)
            if root == "/backtest":
                return self._backtest(args)
            if root == "/trading":
                return self._trading(args)
            if root == "/structure":
                return self._structure(args)
            if root == "/news":
                return self._news(args)
            if root == "/web":
                return self._web(args)
            if root == "/funda":
                return self._fundamentals(args)
            if root == "/yahoo":
                return self._yahoo(args)
            if root == "/ai":
                return self._ai(args)
            if root == "/analyze":
                return self._analyze(args)
            if root == "/scan":
                return self._scan(args)
            if root == "/report":
                return self._report(args)
            if root == "/calendar":
                return self._calendar(args)
            if root == "/export":
                return self._export(args)

            raise CommandError(f"Command tidak dikenal: {root}", "Gunakan /help untuk melihat daftar command.")
        except FinCLIError as exc:
            message = str(exc)
            if exc.help_text:
                message = f"{message}\n\n{exc.help_text}"
            return CommandResult(Panel(message, title="Error", border_style="red"), status="error")
        except ValueError as exc:
            return CommandResult(
                Panel(f"Format command tidak valid: {exc}\nGunakan quote untuk teks panjang.", title="Error"),
                status="error",
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                Panel(
                    (
                        f"Unexpected command error: {type(exc).__name__}: {exc}\n\n"
                        "Command tidak dieksekusi penuh. Gunakan /doctor untuk cek konfigurasi atau coba ulang command."
                    ),
                    title="Error",
                    border_style="red",
                ),
                status="error",
            )

    def _help_table(self) -> Table:
        table = Table(title="FinCLI v1.0.0 Commands", expand=True)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Group", style="magenta")
        table.add_column("Fungsi", style="white")
        table.add_column("Contoh", style="green")
        for command in self.registry.all():
            table.add_row(command.name, command.group, command.description, command.example)
        return table

    def _record_history(self, raw: str, result: CommandResult) -> None:
        normalized = raw.strip().lower()
        if (
            not normalized
            or normalized.startswith("/history")
            or normalized.startswith("/privacy purge")
            or normalized.startswith("/secrets clear")
        ):
            return
        try:
            preview = _render_history_preview(result.renderable)
            self.history.record_event(self.session_id, raw, result.status, preview)
        except Exception:
            return

    def _history(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "current"
        if action in {"current", "show"}:
            session_id = self.session_id if action == "current" or len(args) == 1 else args[1]
            if action == "show" and len(args) < 2:
                raise CommandError("Format: /history show <session_id>")
            session = self.history.get_session(session_id)
            if not session:
                raise CommandError(f"Session tidak ditemukan: {session_id}")
            events = self.history.get_events(session_id)
            return CommandResult(_format_session_events(session, events, current=session_id == self.session_id))
        if action in {"sessions", "list"}:
            sessions = self.history.list_sessions()
            return CommandResult(_format_sessions(sessions, self.session_id))
        if action == "save":
            title = " ".join(args[1:]).strip()
            if not title:
                raise CommandError("Format: /history save <session_title>")
            self.history.save_session(self.session_id, title)
            return CommandResult(Panel(f"Current session disimpan sebagai: {title}", title="History", border_style="green"))
        if action == "delete":
            if len(args) < 2:
                raise CommandError("Format: /history delete <session_id>")
            if args[1] == self.session_id:
                self.history.clear_events(self.session_id)
                self.history.save_session(self.session_id, "FinCLI session")
                return CommandResult(Panel("Current session dikosongkan.", title="History", border_style="yellow"))
            self.history.delete_session(args[1])
            return CommandResult(Panel(f"Session dihapus: {args[1]}", title="History", border_style="green"))
        if action == "clear":
            target = args[1].lower() if len(args) >= 2 else "current"
            if target == "all":
                self.history.clear_all()
                self.session_id = self.history.start_session()
                return CommandResult(Panel("Semua history session dihapus. Session baru dibuat.", title="History"))
            self.history.clear_events(self.session_id)
            return CommandResult(Panel("Current session history dikosongkan.", title="History"))
        raise CommandError(
            "Format: /history [current|sessions|show <id>|save <title>|delete <id>|clear current|clear all]"
        )

    def _dashboard(self) -> Table:
        return _format_dashboard(
            provider_chain=[provider.name for provider in self.market_service.providers],
            watchlist_rows=self.watchlist.list(),
            portfolio_rows=self.portfolio.list(),
            journal_stats=calculate_journal_stats(self.journal.list(limit=10_000)),
            realized_pnl=self.transactions.realized_pnl_total(),
            quote_getter=self._safe_quote,
            portfolio_value_getter=self._portfolio_market_values,
        )

    def _config_panel(self) -> Panel:
        safe = self.config.settings.safe_dict()
        lines = [
            f"AI provider       : {safe['ai_provider']}",
            f"AI model          : {safe['ai_model']}",
            f"Market provider   : {safe['market_provider']}",
            f"News provider     : {safe['news_provider']}",
            f"News priority     : {', '.join(safe.get('news_provider_priority', []))}",
            f"Timezone          : {safe['timezone']}",
            f"Default currency  : {safe['default_currency']}",
            f"Cache TTL         : {safe['cache_ttl_seconds']}s",
            f"Provider timeout  : {safe['provider_timeout_seconds']}s",
            f"Circuit breaker   : {safe['provider_circuit_breaker_failure_threshold']} failures / {safe['provider_circuit_breaker_cooldown_seconds']}s cooldown",
            f"Theme             : {safe['theme']}",
            "",
            "API key status:",
        ]
        lines.extend(f"- {key}: {value}" for key, value in safe["api_keys"].items())
        return Panel("\n".join(lines), title="Active Config", border_style="cyan")

    def _ai_model(self, args: list[str]) -> CommandResult:
        if len(args) == 0:
            current = self.config.settings
            return CommandResult(Panel(f"{current.ai_provider} / {current.ai_model}", title="Active AI Model"))
        if args[0].lower() == "key":
            if len(args) < 3:
                raise CommandError("Format: /ai_model key <provider> <api_key>")
            provider = args[1].lower()
            info = AIProviderManager().get(provider)
            if info is None:
                raise CommandError(f"AI provider tidak dikenal: {provider}")
            save_secret(info.env_key, args[2])
            model = self.config.settings.ai_model if self.config.settings.ai_provider == provider else info.default_model
            self.config.set_ai_model(provider, model)
            self.ai_provider = AIProviderManager().create(provider)
            return CommandResult(
                Panel(
                    (
                        f"API key AI untuk {provider} disimpan global di ~/.fincli/secrets.env.\n"
                        f"Provider aktif disimpan: {provider} / {model}.\n"
                        "Key tidak ditampilkan di terminal dan dipakai lintas session."
                    ),
                    title="AI API Key Saved",
                    border_style="green",
                )
            )
        if len(args) < 2:
            raise CommandError("Format: /ai_model <provider> <model>")
        self.config.set_ai_model(args[0], args[1])
        self.ai_provider = AIProviderManager().create(args[0])
        return CommandResult(Panel(f"AI model aktif: {args[0]} / {args[1]}", title="AI Model Updated"))

    def _news_model(self, args: list[str]) -> CommandResult:
        if len(args) == 0:
            current = self.config.settings
            chain = ", ".join(current.news_provider_priority or [current.news_provider])
            return CommandResult(
                Panel(
                    (
                        f"Market: {current.market_provider}\n"
                        f"News: {current.news_provider}\n"
                        f"Fallback priority: {chain}\n\n"
                        "Commands:\n"
                        "- /news_model list\n"
                        "- /news_model search <query>\n"
                        "- /news_model use <provider>\n"
                        "- /news_model priority google_news_rss,yfinance,marketaux\n"
                        "- /news_model key <provider> <api_key> [base_url]"
                    ),
                    title="Active Data Provider",
                )
            )
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
                    f"News fallback priority disimpan: {', '.join(self.config.settings.news_provider_priority)}",
                    title="News Priority Updated",
                    border_style="green",
                )
            )
        if action == "use":
            if len(args) < 2:
                raise CommandError("Format: /news_model use <provider>")
            provider = args[1].lower()
            self._validate_news_providers([provider])
            current = [item for item in self.config.settings.news_provider_priority if item != provider]
            self.config.set_news_provider_priority([provider, *current])
            return CommandResult(
                Panel(
                    f"News primary provider: {provider}\nFallback: {', '.join(self.config.settings.news_provider_priority)}",
                    title="News Provider Updated",
                    border_style="green",
                )
            )
        if action == "key":
            if len(args) < 3:
                raise CommandError("Format: /news_model key <provider> <api_key> [base_url untuk custom]")
            provider = args[1].lower()
            env_key = news_connector_secret_key(provider)
            env_keys = (env_key,) if env_key else _market_provider_secret_keys(provider)
            if not env_keys:
                raise CommandError(f"Provider {provider} tidak membutuhkan API key atau tidak dikenal.")
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
            extra = "\nBase URL custom juga disimpan." if provider in {"custom", "custom_news"} and len(args) >= 4 else ""
            return CommandResult(
                Panel(
                    (
                        f"API key market/news untuk {provider} disimpan global di ~/.fincli/secrets.env.{extra}\n"
                        f"Provider news aktif disimpan: {provider}.\n"
                        "Key tidak ditampilkan di terminal dan dipakai lintas session."
                    ),
                    title="News API Key Saved",
                    border_style="green",
                )
            )
        provider = args[0].lower()
        if self.market_manager.get(provider) is not None:
            self.config.set_market_provider(provider)
            self.config.set_news_provider(provider)
            self.config.set_market_provider_priority([provider, *self._priority_tail(provider)])
            self._refresh_market_service()
            self.cache.clear()
            return CommandResult(Panel(f"Provider market/news aktif: {provider}", title="Provider Updated"))
        self._validate_news_providers([provider])
        self.config.set_news_provider_priority([provider, *self._news_priority_tail(provider)])
        self.cache.clear()
        return CommandResult(Panel(f"Provider news aktif: {provider}", title="News Provider Updated"))

    def _provider(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "list":
            return CommandResult(_format_provider_list())
        if args and args[0].lower() in {"entitlement", "entitlements"}:
            return CommandResult(_format_provider_entitlements(self.market_manager.entitlements()))
        if args and args[0].lower() == "metrics":
            return CommandResult(_format_provider_metrics(self.market_service))
        if args and args[0].lower() in {"capabilities", "capability", "matrix"}:
            return CommandResult(_format_provider_capabilities())
        if args and args[0].lower() == "key" and len(args) >= 2 and args[1].lower() == "status":
            return CommandResult(_format_provider_key_status(self.market_manager))
        if args and args[0].lower() in {"insider", "insiders"}:
            if len(args) < 2:
                raise CommandError("Format: /provider insider <symbol>")
            provider = self.market_manager.create("finnhub")
            rows = self._run_async(provider.insider_transactions(args[1].upper()))
            return CommandResult(_format_insider_transactions(args[1].upper(), rows))
        if args and args[0].lower() == "ipo":
            start, end, _, _ = _parse_calendar_args(args[1:] or ["week"])
            provider = self.market_manager.create("finnhub")
            rows = self._run_async(provider.ipo_calendar(start, end))
            return CommandResult(_format_ipo_calendar(rows, start, end))
        if args and args[0].lower() == "use":
            if len(args) < 2:
                raise CommandError("Format: /provider use <provider>")
            provider = args[1].lower()
            self.config.set_market_provider_priority([provider, *self._priority_tail(provider)])
            self._refresh_market_service()
            self.cache.clear()
            return CommandResult(Panel(f"Provider market aktif: {provider}", title="Provider Updated"))
        if args and args[0].lower() == "priority":
            if len(args) < 2:
                raise CommandError("Format: /provider priority finnhub,yfinance")
            providers = [provider.strip() for provider in args[1].split(",") if provider.strip()]
            self.config.set_market_provider_priority(providers)
            self._refresh_market_service()
            self.cache.clear()
            return CommandResult(Panel(f"Provider priority: {', '.join(providers)}", title="Provider Priority"))
        if args and args[0].lower() == "status":
            settings = self.config.settings
            provider_status = self._provider_health_text()
            text = (
                f"Market provider: {settings.market_provider} (active: {self.market_provider.name})\n"
                f"News provider  : {settings.news_provider} (active: {self.market_provider.name} fallback)\n"
                f"Provider chain : {', '.join(provider.name for provider in self.market_service.providers)}\n"
                f"AI provider    : {settings.ai_provider} (active: {self.ai_provider.name})\n"
                f"{provider_status}"
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
        raise CommandError(
            "Format: /provider status, /provider list, /provider capabilities, /provider entitlement, /provider key status, "
            "/provider use <provider>, /provider priority finnhub,yfinance, /provider insider <symbol>, "
            "/provider ipo [week|from to], atau /provider test [provider] <symbol>"
        )

    def _symbol(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /symbol search <query>, /symbol resolve <symbol> [--asset <class>], atau /symbol normalize <symbol>")
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

    def _research(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /research <symbol> [--deep|--report] [timeframe] [--export <md|json> <path>]")
        symbol = args[0].upper()
        export_format: str | None = None
        export_target: str | None = None
        if "--export" in args:
            export_index = args.index("--export")
            if len(args) <= export_index + 2:
                raise CommandError("Format export: /research <symbol> --report --export <md|json> <path>")
            export_format = args[export_index + 1]
            export_target = args[export_index + 2]
        flags = {arg.lower() for arg in args[1:] if arg.startswith("--")}
        if "--report" in flags:
            mode = "report"
        elif "--deep" in flags:
            mode = "deep"
        else:
            # --snapshot/--quick and no flag all resolve to the compact snapshot mode.
            mode = "snapshot"
        ignored: set[int] = set()
        if "--export" in args:
            export_index = args.index("--export")
            ignored.update({export_index, export_index + 1, export_index + 2})
        timeframe = next((arg for index, arg in enumerate(args[1:], start=1) if index not in ignored and not arg.startswith("--")), "1d")
        engine = ResearchEngine(
            self.market_service,
            self.ai_provider,
            self.config.settings.ai_model,
            macro_service=self.macro_data,
            web_research=self.web_research,
        )
        brief = self._run_async(engine.build(symbol, timeframe=timeframe, mode=mode))
        if export_format and export_target:
            written = write_research_report(brief, export_format, export_target)
            return CommandResult(Panel(f"Research export selesai: {written}", title="Research Export", border_style="green"))
        return CommandResult(format_research_brief(brief))

    def _macro(self, args: list[str]) -> CommandResult:
        query = " ".join(args).strip()
        rows = self.macro_data.indicators(query)
        return CommandResult(_format_macro_dashboard(query or "global", rows))

    def _macro_indicator(self, indicator: str, args: list[str]) -> CommandResult:
        if indicator == "gdp" and args[:2] and " ".join(args[:2]).lower() == "per capita":
            indicator = "gdp_per_capita"
            args = args[2:]
        region = args[0] if args else "us"
        try:
            rows = self.macro_data.alpha_vantage_indicator(indicator, region)
        except FinCLIError as exc:
            rows = [_macro_error_row(indicator, region, exc)]
        return CommandResult(_format_macro_indicator(indicator, region, rows))

    def _profile(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_user_profile(self.user_profiles.get()))
        action = args[0].lower()
        if action == "set":
            if len(args) < 6:
                raise CommandError('Format: /profile set "Nama" <equity> <currency> <leverage> <years>')
            profile = self.user_profiles.save(args[1], float(args[2]), args[3], args[4], float(args[5]))
            return CommandResult(_format_user_profile(profile))
        if action in {"clear", "delete", "reset"}:
            self.user_profiles.clear()
            return CommandResult(Panel("Profile lokal dihapus.", title="Profile", border_style="yellow"))
        raise CommandError('Format: /profile, /profile set "Nama" <equity> <currency> <leverage> <years>, /profile clear')

    def _doctor(self, args: list[str]) -> CommandResult:
        full = bool(args and args[0].lower() in {"full", "deep"})
        live = "--live" in {arg.lower() for arg in args}
        live_symbol = _doctor_live_symbol(args)
        table = Table(title="FinCLI Doctor Full" if full else "FinCLI Doctor", expand=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status")
        table.add_column("Detail", overflow="fold")
        table.add_row("Version", "ok", "FinCLI v1.0.0 command surface loaded.")
        for check in check_runtime_environment():
            style = "green" if check.status == "ok" else "yellow" if check.status in {"warning", "info"} else "red"
            table.add_row(check.name, f"[{style}]{check.status}[/]", check.detail)
        table.add_row("Database", "ok", str(self.db.db_file))
        table.add_row("Market Provider", "ok", ", ".join(provider.name for provider in self.market_service.providers))
        table.add_row("Provider Timeout", "ok", f"{self.config.settings.provider_timeout_seconds}s per provider call")
        table.add_row(
            "Circuit Breaker",
            "ok",
            (
                f"{self.config.settings.provider_circuit_breaker_failure_threshold} failures -> "
                f"{self.config.settings.provider_circuit_breaker_cooldown_seconds}s cooldown"
            ),
        )
        profile = self.user_profiles.get()
        table.add_row("Profile", "ok" if profile else "missing", profile.gameplay if profile else "Run /profile set ...")
        table.add_row("AI Provider", "configured", f"{self.config.settings.ai_provider} / {self.config.settings.ai_model}")
        if full:
            for name, status, detail in self._doctor_full_checks():
                style = "green" if status == "ok" else "yellow" if status in {"warning", "info"} else "red"
                table.add_row(name, f"[{style}]{status}[/]", detail)
            if live:
                for name, status, detail in self._doctor_live_checks(live_symbol):
                    style = "green" if status == "ok" else "yellow" if status in {"warning", "info"} else "red"
                    table.add_row(name, f"[{style}]{status}[/]", detail)
        table.caption = (
            "Doctor full checks local wiring, command coverage, database/cache, and provider configuration. "
            "Use /doctor full --live [SYMBOL] for optional live quote verification. "
            "Provider entitlement still depends on API key/account plan."
        )
        return CommandResult(table)

    def _doctor_full_checks(self) -> list[tuple[str, str, str]]:
        checks: list[tuple[str, str, str]] = []
        try:
            tables = self.db.query("SELECT name FROM sqlite_master WHERE type = 'table'")
            checks.append(("Database Schema", "ok", f"{len(tables)} table(s) available"))
        except FinCLIError as exc:
            checks.append(("Database Schema", "error", str(exc)))

        try:
            stats = self.market_cache.stats()
            checks.append(("Market Cache", "ok", ", ".join(f"{key}={value}" for key, value in stats.items())))
        except FinCLIError as exc:
            checks.append(("Market Cache", "error", str(exc)))

        key_rows = self.market_manager.key_status()
        missing_keys = [row["provider"] for row in key_rows if row["status"] == "not set"]
        configured_keys = [row["provider"] for row in key_rows if row["status"] not in {"not set", "not required"}]
        checks.append(
            (
                "Market API Keys",
                "warning" if missing_keys else "ok",
                f"configured={len(configured_keys)}; missing={', '.join(missing_keys) if missing_keys else 'none'}",
            )
        )

        for provider in self.market_service.providers:
            provider_name = getattr(provider, "name", "unknown")
            try:
                status = self._run_async(provider.status())
                checks.append((f"Provider:{provider_name}", "ok" if status.status in {"ok", "configured", "fallback"} else "warning", status.message))
            except Exception as exc:  # noqa: BLE001
                checks.append((f"Provider:{provider_name}", "error", str(exc)))

        registry_roots = {command.name.split()[0] for command in self.registry.all()}
        router_roots = _router_roots()
        hidden = sorted(router_roots - registry_roots)
        stale = sorted(registry_roots - router_roots)
        if hidden or stale:
            checks.append(
                (
                    "Command Coverage",
                    "warning",
                    f"hidden={', '.join(hidden) if hidden else 'none'}; stale={', '.join(stale) if stale else 'none'}",
                )
            )
        else:
            checks.append(("Command Coverage", "ok", f"{len(registry_roots)} registry root command(s) covered by router"))

        metric_snapshot = self.market_service.provider_metrics_snapshot()
        checks.append(("Provider Metrics", "ok", f"session_providers={len(metric_snapshot)}; persistent_store=enabled"))
        checks.append(("Capability Matrix", "ok", capability_summary()))
        for capability in capability_rows():
            checks.append(
                (
                    f"Capability:{capability.command}",
                    "ok",
                    f"needs={', '.join(capability.needs)}; {capability.note}",
                )
            )
        return checks

    def _doctor_live_checks(self, symbol: str) -> list[tuple[str, str, str]]:
        try:
            quote = self._run_async(asyncio.wait_for(self.market_service.quote(symbol), self.config.settings.provider_timeout_seconds))
        except Exception as exc:  # noqa: BLE001
            return [("Live Quote Test", "error", f"{symbol}: {type(exc).__name__}: {exc}")]
        return [
            (
                "Live Quote Test",
                "ok" if quote.price is not None else "warning",
                f"{quote.symbol} {quote.price if quote.price is not None else 'N/A'} {quote.currency}; provider={quote.provider}; status={quote.status}",
            )
        ]

    def _setup(self, args: list[str]) -> CommandResult:
        return CommandResult(
            Panel(
                "\n".join(
                    [
                        "Recommended setup:",
                        '1. /profile set "Nama" <equity> <currency> <leverage> <years>',
                        "2. /ai_model key <provider> <api_key>",
                        "3. /news_model key <provider> <api_key>",
                        "4. /provider priority yfinance,alphavantage,twelvedata,finnhub",
                        "5. /research AAPL --quick",
                        "6. /analyze XAUUSD 1d",
                    ]
                ),
                title="FinCLI Setup",
                border_style="cyan",
            )
        )

    def _tutorial(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_tutorial_menu())
        action = args[0].lower()
        if action == "next":
            return CommandResult(_tutorial_next(self))
        if action == "reset":
            if not hasattr(self, "_tutorial_progress"):
                self._tutorial_progress = 0
            self._tutorial_progress = 0
            return CommandResult(Panel("Tutorial progress reset. Type /tutorial to start over.", title="Tutorial", border_style="yellow"))
        if action in {"1", "setup", "welcome"}:
            return CommandResult(_tutorial_lesson(1))
        if action in {"2", "market", "data"}:
            return CommandResult(_tutorial_lesson(2))
        if action in {"3", "technical", "analysis"}:
            return CommandResult(_tutorial_lesson(3))
        if action in {"4", "portfolio"}:
            return CommandResult(_tutorial_lesson(4))
        if action in {"5", "trading"}:
            return CommandResult(_tutorial_lesson(5))
        if action in {"6", "alerts", "monitoring"}:
            return CommandResult(_tutorial_lesson(6))
        if action in {"7", "export", "reports"}:
            return CommandResult(_tutorial_lesson(7))
        raise CommandError("Format: /tutorial, /tutorial <1-7>, /tutorial next, /tutorial reset")

    def _secrets(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "status"
        if action == "status":
            return CommandResult(_format_secrets_status(read_secrets()))
        if action == "clear":
            cleared = clear_secrets()
            return CommandResult(
                Panel(
                    f"{cleared} local secret(s) cleared from ~/.fincli/secrets.env. Current process keys from that store were removed.",
                    title="Secrets Cleared",
                    border_style="yellow",
                )
            )
        raise CommandError("Format: /secrets status atau /secrets clear")

    def _security(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_security_status(self))
        action = args[0].lower()
        if action == "status":
            return CommandResult(_format_security_status(self))
        if action == "audit":
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 50
            events = self.audit_log.list_events(limit=limit)
            return CommandResult(_format_audit_events(events))
        if action == "scan":
            return CommandResult(_format_security_scan(read_secrets()))
        if action == "lockdown":
            # Emergency: clear all secrets
            cleared = clear_secrets()
            self.audit_log.record(EVENT_SECURITY_VIOLATION, f"Emergency lockdown: {cleared} secrets cleared")
            return CommandResult(Panel(
                f"LOCKDOWN: {cleared} secrets cleared. All API keys removed. Use /ai_model key and /news_model key to reconfigure.",
                title="Security Lockdown",
                border_style="red",
            ))
        raise CommandError("Format: /security status, /security audit, /security scan, /security lockdown")

    def _privacy(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "status"
        if action == "status":
            stats = self.market_cache.stats()
            return CommandResult(
                Panel(
                    "\n".join(
                        [
                            f"Secrets stored       : {len(read_secrets())}",
                            f"Session events       : {len(self.history.get_events(self.session_id))}",
                            f"Persistent cache rows: {stats['total']}",
                            "Purge scope          : secrets + current session history + runtime/persistent cache",
                            "Portfolio, journal, alerts, and profile are not deleted by /privacy purge.",
                        ]
                    ),
                    title="Privacy Status",
                    border_style="cyan",
                )
            )
        if action == "purge":
            secrets_cleared = clear_secrets()
            self.history.clear_events(self.session_id)
            self.cache.clear()
            cache_cleared = self.market_cache.clear()
            return CommandResult(
                Panel(
                    (
                        f"Privacy state purged.\n"
                        f"- secrets cleared: {secrets_cleared}\n"
                        f"- current session history cleared\n"
                        f"- runtime cache cleared\n"
                        f"- persistent market cache rows cleared: {cache_cleared}\n\n"
                        "Portfolio, journal, alerts, and profile were kept."
                    ),
                    title="Privacy Purge",
                    border_style="yellow",
                )
            )
        raise CommandError("Format: /privacy status atau /privacy purge")

    def _agent(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls"}:
            category = args[1].lower() if len(args) >= 2 else ""
            agents = self.agent_registry.by_category(category) if category else list(self.agent_registry.all())
            return CommandResult(_format_agents(agents, category or "all"))
        if action == "show":
            if len(args) < 2:
                raise CommandError("Format: /agent show <slug>")
            agent = self.agent_registry.get(args[1])
            if agent is None:
                raise CommandError(f"Agent tidak ditemukan: {args[1]}")
            return CommandResult(_format_agent(agent))
        raise CommandError("Format: /agent list [category] atau /agent show <slug>")

    def _connector(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls"}:
            category = args[1].lower() if len(args) >= 2 else ""
            connectors = self.connector_catalog.by_category(category) if category else list(self.connector_catalog.all())
            return CommandResult(_format_connectors(connectors, category or "all"))
        if action in {"search", "find"}:
            if len(args) < 2:
                raise CommandError("Format: /connector search <query>")
            query = " ".join(args[1:])
            return CommandResult(_format_connectors(self.connector_catalog.find(query), query))
        raise CommandError("Format: /connector list [category] atau /connector search <query>")

    def _plugin(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls", "status"}:
            plugins = PluginLoader().discover()
            return CommandResult(_format_plugins(plugins, status_only=action == "status"))
        raise CommandError("Format: /plugin list atau /plugin status")

    def _cache(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "stats":
            stats = self.market_cache.stats()
            lines = [
                f"Runtime cache TTL  : {self.config.settings.cache_ttl_seconds}s",
                f"Persistent entries: {stats['total']}",
                f"- quote          : {stats['quote']}",
                f"- history        : {stats['history']}",
                f"- news           : {stats['news']}",
                f"- fundamentals   : {stats['fundamentals']}",
            ]
            return CommandResult(Panel("\n".join(lines), title="Cache Stats", border_style="cyan"))
        if args and args[0].lower() == "clear":
            self.cache.clear()
            cleared = self.market_cache.clear()
            return CommandResult(Panel(f"Runtime cache dan persistent cache dibersihkan ({cleared} entry).", title="Cache"))
        raise CommandError("Format: /cache clear atau /cache stats")

    def _watchlist(self, args: list[str]) -> CommandResult:
        if not args:
            rows = self.watchlist.list()
            table = Table(title="Watchlist", expand=True)
            table.add_column("Symbol", style="cyan")
            table.add_column("Price", justify="right")
            table.add_column("Currency")
            table.add_column("Status")
            table.add_column("Group")
            table.add_column("Created")
            for row in rows:
                quote = self._safe_quote(str(row["symbol"]))
                table.add_row(
                    str(row["symbol"]),
                    _fmt(quote.price) if quote else "N/A",
                    quote.currency if quote else "-",
                    quote.status if quote else "unavailable",
                    str(row["group_name"]),
                    str(row["created_at"]),
                )
            if not rows:
                table.add_row("-", "-", "-", "-", "Belum ada data. Gunakan /watchlist add AAPL", "-")
            return CommandResult(table)

        action = args[0].lower()
        if action == "add" and len(args) >= 2:
            self.watchlist.add(args[1], args[2] if len(args) >= 3 else "default")
            return CommandResult(Panel(f"{args[1].upper()} ditambahkan ke watchlist.", title="Watchlist"))
        if action == "remove" and len(args) >= 2:
            self.watchlist.remove(args[1])
            return CommandResult(Panel(f"{args[1].upper()} dihapus dari watchlist.", title="Watchlist"))
        raise CommandError("Format: /watchlist, /watchlist add <symbol>, /watchlist remove <symbol>")

    def _portfolio(self, args: list[str]) -> CommandResult:
        if not args:
            rows = self.portfolio.list()
            table = Table(title="Portfolio", expand=True)
            table.add_column("Symbol", style="cyan")
            table.add_column("Qty", justify="right")
            table.add_column("Avg Price", justify="right")
            table.add_column("Current", justify="right")
            table.add_column("PnL", justify="right")
            table.add_column("PnL %", justify="right")
            table.add_column("Currency")
            table.add_column("Updated")
            for row in rows:
                current_price, pnl, pnl_percent = self._portfolio_market_values(row)
                table.add_row(
                    str(row["symbol"]),
                    f"{float(row['quantity']):,.8g}",
                    f"{float(row['average_price']):,.4f}",
                    _fmt(current_price),
                    _fmt(pnl),
                    _fmt(pnl_percent),
                    str(row["currency"]),
                    str(row["updated_at"]),
                )
            if not rows:
                table.add_row(
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    "-",
                    "Belum ada posisi. Gunakan /portfolio add BTC-USD 0.05 65000",
                )
            return CommandResult(table)

        action = args[0].lower()
        if action == "risk":
            return CommandResult(_format_portfolio_risk(self._portfolio_risk_report()))
        if action == "performance":
            return CommandResult(self._portfolio_performance_table())
        if action == "chart":
            return self._portfolio_chart()
        if action == "whatif":
            return self._portfolio_whatif(args[1:])
        if action == "benchmark":
            return self._portfolio_benchmark(args[1:])
        if action == "snapshot":
            return self._portfolio_snapshot()
        if action == "add" and len(args) >= 4:
            try:
                quantity = float(args[2])
                average_price = float(args[3])
            except ValueError as exc:
                raise CommandError("Quantity dan average price harus angka.") from exc
            self.portfolio.add(args[1], quantity, average_price, args[4] if len(args) >= 5 else "USD")
            return CommandResult(Panel(f"Posisi {args[1].upper()} disimpan.", title="Portfolio"))
        if action == "remove" and len(args) >= 2:
            self.portfolio.remove(args[1])
            return CommandResult(Panel(f"Posisi {args[1].upper()} dihapus.", title="Portfolio"))
        raise CommandError(
            "Format: /portfolio, /portfolio risk, /portfolio performance, /portfolio add <symbol> <qty> <avg_price>, "
            "/portfolio remove <symbol>"
        )

    def _tx(self, args: list[str]) -> CommandResult:
        if not args or args[0].lower() == "list":
            return CommandResult(_format_transactions(self.transactions.list()))

        if args[0].lower() == "add":
            if len(args) < 5:
                raise CommandError("Format: /tx add <buy|sell> <symbol> <qty> <price> [currency]")
            try:
                quantity = float(args[3])
                price = float(args[4])
            except ValueError as exc:
                raise CommandError("Quantity dan price harus angka.") from exc
            tx = self.transactions.add(
                action=args[1],
                symbol=args[2],
                quantity=quantity,
                price=price,
                currency=args[5] if len(args) >= 6 else "USD",
            )
            return CommandResult(
                Panel(
                    (
                        f"Transaction saved: {tx['action']} {tx['symbol']} "
                        f"{_fmt(float(tx['quantity']))} @ {_fmt(float(tx['price']))} "
                        f"| Realized PnL {_fmt(float(tx['realized_pnl']))}"
                    ),
                    title="Transaction",
                    border_style="green",
                )
            )

        raise CommandError("Format: /tx add <buy|sell> <symbol> <qty> <price> [currency] atau /tx list")

    def _journal(self, args: list[str]) -> CommandResult:
        if not args:
            rows = self.journal.list()
            return CommandResult(self._journal_table(rows, "Journal"))

        if args[0].lower() == "stats":
            rows = self.journal.list(limit=10_000)
            stats = calculate_journal_stats(rows)
            return CommandResult(_format_journal_stats(stats))

        if args[0].lower() == "review":
            rows = self.journal.list(limit=10_000)
            stats = calculate_journal_stats(rows)
            prompt = build_journal_review_prompt(rows, stats)
            response = self._run_async(self.ai_provider.complete(AIRequest(prompt=prompt, model=self.config.settings.ai_model)))
            if not isinstance(response, AIResponse):
                raise CommandError("AI provider mengembalikan data tidak valid.")
            return CommandResult(
                MarkdownBlock("Journal Review", _format_ai_response(response), "Disclaimer: bukan nasihat keuangan.")
            )

        if args[0].lower() == "add":
            if len(args) < 3:
                raise CommandError('Format: /journal add <instrument> <bias> "entry reason"')
            self.journal.add(args[1], bias=args[2], entry_reason=args[3] if len(args) >= 4 else "")
            return CommandResult(Panel(f"Journal untuk {args[1].upper()} ditambahkan.", title="Journal"))

        rows = self.journal.list(args[0])
        return CommandResult(self._journal_table(rows, f"Journal {args[0].upper()}"))

    def _journal_table(self, rows: list[dict[str, object]], title: str) -> Table:
        table = Table(title=title, expand=True)
        table.add_column("ID", justify="right")
        table.add_column("Instrument", style="cyan")
        table.add_column("Bias")
        table.add_column("Entry Reason")
        table.add_column("Created")
        for row in rows:
            table.add_row(
                str(row["id"]),
                str(row["instrument"]),
                str(row["bias"]),
                str(row["entry_reason"]),
                str(row["created_at"]),
            )
        if not rows:
            table.add_row("-", "-", "-", 'Belum ada journal. Gunakan /journal add BTC-USD bullish "Alasan entry"', "-")
        return table

    def _alert(self, args: list[str]) -> CommandResult:
        action = args[0].lower() if args else "list"
        if action in {"list", "ls"}:
            return CommandResult(_format_alerts(self.alerts.list()))
        if action == "add":
            if len(args) < 4:
                raise CommandError("Format: /alert add <symbol> <above|below|rsi_below|rsi_above|volume_above|macd_cross_up|macd_cross_down> <target> [note]")
            symbol = args[1]
            condition = args[2]
            try:
                target = float(args[3])
            except ValueError as exc:
                raise CommandError("Target alert harus angka.") from exc
            note = " ".join(args[4:]).strip()
            self.alerts.add(symbol, condition, target, note)
            return CommandResult(Panel(f"Alert ditambahkan: {symbol.upper()} {condition} {target:g}", title="Alert"))
        if action in {"remove", "delete", "rm"}:
            if len(args) < 2:
                raise CommandError("Format: /alert remove <id>")
            self.alerts.remove(int(args[1]))
            return CommandResult(Panel(f"Alert dihapus: {args[1]}", title="Alert"))
        if action == "check":
            checked: list[AlertCheckResult] = []
            for alert in self.alerts.list(active_only=True):
                quote = self._safe_quote(str(alert["symbol"]))
                result = evaluate_alert(alert, quote.price if quote else None)
                checked.append(result)
                if result.triggered:
                    self.alerts.mark_triggered(result.id)
                    self.alerts.record_history(result.id, result.symbol, result.condition, result.target, result.current_price, True, result.note)
            return CommandResult(_format_alert_checks(checked))
        if action == "history":
            return CommandResult(_format_alert_history(self.alerts.get_history()))
        if action == "daemon":
            return self._alert_daemon(args[1:])
        raise CommandError(
            "Format: /alert, /alert add <symbol> <condition> <target>, /alert remove <id>, /alert check, "
            "/alert history, /alert daemon start|stop|status"
        )

    def _alert_daemon(self, args: list[str]) -> CommandResult:
        if not hasattr(self, "_alert_daemon_instance"):
            from fincli.app.modules.alerts import AlertDaemon
            self._alert_daemon_instance = AlertDaemon(self.alerts, self.market_service, check_interval=60.0)

        daemon = self._alert_daemon_instance
        action = args[0].lower() if args else "status"

        if action == "start":
            if daemon.is_running:
                return CommandResult(Panel("Alert daemon sudah berjalan.", title="Alert Daemon"))
            self._run_async(daemon.start())
            return CommandResult(Panel("Alert daemon started. Checking every 60s. Use /alert daemon stop to halt.", title="Alert Daemon", border_style="green"))
        if action == "stop":
            if not daemon.is_running:
                return CommandResult(Panel("Alert daemon tidak berjalan.", title="Alert Daemon"))
            self._run_async(daemon.stop())
            return CommandResult(Panel("Alert daemon stopped.", title="Alert Daemon", border_style="yellow"))
        if action == "status":
            status = "running" if daemon.is_running else "stopped"
            last = daemon.last_check.isoformat() if daemon.last_check else "never"
            return CommandResult(Panel(
                f"Status: {status}\nLast check: {last}\nTriggered this session: {daemon.triggered_count}\nInterval: {daemon.check_interval}s",
                title="Alert Daemon",
            ))
        raise CommandError("Format: /alert daemon start|stop|status")

    def _quote(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /quote <symbol>")
        symbol = args[0].upper()
        cache_key = f"quote:{symbol}"
        cached = self.cache.get(cache_key)
        quote = cached if isinstance(cached, Quote) else self._run_async(self.market_service.quote(symbol))
        if not isinstance(quote, Quote):
            raise CommandError("Provider quote mengembalikan data tidak valid.")
        self.cache.set(cache_key, quote)
        return CommandResult(_format_quote(quote))

    def _technical(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /technical <symbol> [interval]")
        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 else "1d"
        candles = self._run_async(self.market_service.history(symbol, period="6mo", interval=interval))
        if not candles:
            raise CommandError(f"Data teknikal kosong untuk {symbol}.")
        summary = summarize_technical_indicators(candles)
        structure = analyze_market_structure(candles)
        debate = run_technical_debate(summary, structure, candles)
        signal = debate.judge_signal
        ai_summary = build_technical_ai_summary(symbol, interval, candles)
        return CommandResult(_format_technical(symbol, interval, summary, signal, ai_summary, debate))

    def _mtf(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /mtf <symbol> [timeframes comma-separated]")
        symbol = args[0].upper()
        timeframes = _parse_timeframes(args[1] if len(args) >= 2 else "1d,1h,15m")
        analysis = self._run_async(analyze_multi_timeframe(symbol, self.market_service, timeframes=timeframes))
        return CommandResult(_format_multi_timeframe(analysis))

    def _backtest(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError(
                "Format: /backtest <symbol> [strategy] [interval] [--asset <class>] [--equity <amount>] "
                "[--sizing fixed_fractional|kelly] [--fraction <pct>] [--monte-carlo] [--walk-forward] [--export <md|json|csv> <path>]"
            )
        symbol = args[0].upper()
        strategy = args[1].lower() if len(args) >= 2 and not args[1].startswith("--") else "sma_cross"
        interval = args[2].lower() if len(args) >= 3 and not args[2].startswith("--") else "1d"

        # Parse options
        asset_class = _extract_option_value(args, "--asset") or "equity"
        initial_equity = float(_extract_option_value(args, "--equity") or "10000")
        position_method = _extract_option_value(args, "--sizing") or "fixed_fractional"
        position_fraction = float(_extract_option_value(args, "--fraction") or "0.02")
        include_mc = "--monte-carlo" in args or "--mc" in args
        walk_forward = "--walk-forward" in args or "--wf" in args
        export_format = None
        export_target = None
        if "--export" in args:
            export_index = args.index("--export")
            if len(args) > export_index + 2:
                export_format = args[export_index + 1]
                export_target = args[export_index + 2]

        candles = self._run_async(self.market_service.history(symbol, period="2y", interval=interval))
        result = run_backtest(
            symbol, candles, strategy=strategy, interval=interval,
            asset_class=asset_class, initial_equity=initial_equity,
            position_method=position_method, position_fraction=position_fraction,
            include_monte_carlo=include_mc, walk_forward=walk_forward,
        )

        if export_format and export_target:
            from fincli.app.modules.exporter import export_backtest
            written = export_backtest(result, export_format, export_target)
            return CommandResult(Panel(f"Backtest export selesai: {written}", title="Backtest Export", border_style="green"))

        return CommandResult(_format_backtest(result))

    def _trading(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_trading_overview(self.realtime_connector_catalog, self.broker_catalog, self.paper_trading))
        action = args[0].lower()
        if action in {"realtime", "feeds", "feed"}:
            return CommandResult(_format_realtime_connectors(self.realtime_connector_catalog.all()))
        if action in {"brokers", "broker"}:
            return self._trading_broker(args[1:])
        if action == "paper":
            return self._trading_paper(args[1:])
        if action == "kill":
            self.paper_trading.set_kill_switch(True, "Manual kill switch via /trading kill")
            return CommandResult(Panel("Kill switch ACTIVATED. All paper orders blocked. Use /trading resume to re-enable.", title="Trading", border_style="red"))
        if action == "resume":
            self.paper_trading.set_kill_switch(False)
            return CommandResult(Panel("Kill switch deactivated. Paper orders re-enabled.", title="Trading", border_style="green"))
        if action == "risk":
            return CommandResult(_format_risk_status(self.paper_trading))
        if action == "audit":
            limit = int(args[1]) if len(args) >= 2 and args[1].isdigit() else 50
            return CommandResult(_format_audit_log(self.paper_trading.audit.list_entries(limit)))
        if action == "cancel":
            if len(args) < 2:
                raise CommandError("Format: /trading cancel <order_id>")
            order = self.paper_trading.cancel_order(int(args[1]))
            return CommandResult(_format_paper_order(order))
        if action == "positions":
            return CommandResult(_format_positions(self.paper_trading.get_positions()))
        if action == "stream":
            return self._trading_stream(args[1:])
        if action == "algo":
            return self._trading_algo(args[1:])
        raise CommandError(
            "Format: /trading, /trading realtime, /trading brokers, /trading broker use|status, "
            "/trading paper buy|sell|orders|positions|cancel, /trading kill, /trading resume, "
            "/trading risk, /trading audit, /trading stream, /trading algo list|run"
        )

    def _trading_broker(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_brokers(self.broker_catalog.all()))
        action = args[0].lower()
        if action == "use":
            if len(args) < 2:
                raise CommandError("Format: /trading broker use <name>")
            return CommandResult(Panel(
                f"Broker adapter '{args[1]}' activation is catalog-level in v0.8.0. "
                f"Configure API keys via /news_model key or environment variables, then use /trading paper --live to route through the adapter.",
                title="Broker Adapter",
                border_style="yellow",
            ))
        if action == "status":
            return CommandResult(_format_broker_status(self.broker_catalog))
        raise CommandError("Format: /trading brokers, /trading broker use <name>, /trading broker status")

    def _trading_paper(self, args: list[str]) -> CommandResult:
        if not args or args[0].lower() in {"orders", "list"}:
            return CommandResult(_format_paper_orders(self.paper_trading.list_orders()))
        if args[0].lower() == "positions":
            return CommandResult(_format_positions(self.paper_trading.get_positions()))
        if len(args) < 4:
            raise CommandError("Format: /trading paper <buy|sell> <symbol> <qty> <market|limit|stop_limit> [price]")
        side = args[0].lower()
        symbol = args[1].upper()
        try:
            quantity = float(args[2])
            price = float(args[4]) if len(args) >= 5 else None
        except ValueError as exc:
            raise CommandError("Quantity dan price paper order harus angka.") from exc
        order_type = args[3].lower()
        order = self.paper_trading.place_order(side, symbol, quantity, order_type, price=price)
        return CommandResult(_format_paper_order(order))

    def _trading_stream(self, args: list[str]) -> CommandResult:
        if not args:
            connectors = self.realtime_connector_catalog.all()
            return CommandResult(_format_stream_status(connectors))
        connector = args[0].lower()
        return CommandResult(Panel(
            f"Stream '{connector}' is configurable in v0.8.0. "
            f"Connect via the realtime_stream module adapters (KrakenWebSocketAdapter, HyperLiquidWebSocketAdapter, EquityStreamingAdapter). "
            f"See /trading realtime for available connectors.",
            title="Stream",
            border_style="cyan",
        ))

    def _trading_algo(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /trading algo list, /trading algo run <strategy> <symbol> [timeframe] [qty]")
        action = args[0].lower()
        if action in {"list", "ls"}:
            from fincli.app.modules.algo_engine import BUILTIN_STRATEGIES
            return CommandResult(_format_algo_strategies(BUILTIN_STRATEGIES))
        if action == "run":
            if len(args) < 3:
                raise CommandError("Format: /trading algo run <strategy> <symbol> [timeframe] [qty]")
            return self._trading_algo_run(args[1:])
        raise CommandError("Format: /trading algo list, /trading algo run <strategy> <symbol> [timeframe] [qty]")

    def _trading_algo_run(self, args: list[str]) -> CommandResult:
        from fincli.app.modules.algo_engine import StrategyEngine
        strategy = args[0].lower()
        symbol = args[1].upper()
        timeframe = args[2] if len(args) >= 3 else "1d"
        quantity = float(args[3]) if len(args) >= 4 else 1.0
        engine = StrategyEngine(self.market_service)
        result = self._run_async(engine.run(strategy, symbol, timeframe, quantity))
        # If signal is buy/sell, place paper order
        order_result = None
        if result.signal in {"buy", "sell"} and result.suggested_qty > 0:
            try:
                order_result = self.paper_trading.place_order(
                    result.signal, symbol, result.suggested_qty, "market", strategy=strategy,
                )
            except Exception:  # noqa: BLE001 - risk guard may block
                pass
        return CommandResult(_format_algo_result(result, order_result))

    def _market(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /market <symbol> [interval]")
        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 else "1d"
        overview = self._run_async(build_market_overview(symbol, self.market_service, interval))
        return CommandResult(_format_market_overview(overview))

    def _structure(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /structure <symbol> [interval]")
        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 else "1d"
        candles = self._run_async(self.market_service.history(symbol, period="6mo", interval=interval))
        if not candles:
            raise CommandError(f"Data struktur market kosong untuk {symbol}.")
        structure = analyze_market_structure(candles)
        return CommandResult(_format_structure(symbol, interval, structure))

    def _news(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /news <symbol> [1d-30d]")
        symbol = args[0].upper()
        lookback_days = _parse_news_lookback(args[1:]) if len(args) > 1 else None
        desk = self._run_async(
            NewsAggregator(
                self.market_service,
                self.news_connectors,
                self.config.settings.news_provider_priority,
            ).latest(symbol, limit=12, lookback_days=lookback_days)
        )
        return CommandResult(_format_news_desk(desk))

    def _fundamentals(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /funda <symbol>")
        symbol = args[0].upper()
        snapshot = self._run_async(self.market_service.fundamentals(symbol))
        return CommandResult(_format_fundamentals(snapshot))

    def _yahoo(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError(
                "Format: /yahoo <symbol> [history|statistics|profile|financials|balance|cashflow|analysis|holders|news] [period] [interval]"
            )
        symbol = args[0].upper()
        section = args[1].lower() if len(args) >= 2 else "statistics"
        period = args[2] if len(args) >= 3 else "6mo"
        interval = args[3] if len(args) >= 4 else "1d"
        provider = YFinanceProvider()
        table = self._run_async(provider.yahoo_table(symbol, section, period=period, interval=interval))
        if not isinstance(table, YahooTable):
            raise CommandError("YFinance provider mengembalikan data tabel tidak valid.")
        return CommandResult(_format_yahoo_table(table))

    def _ai(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /ai <pertanyaan>")
        prompt = " ".join(args)
        if is_coding_request(prompt):
            response = AIResponse(provider="fincli", model="local-policy", content=coding_refusal())
            return CommandResult(_format_ai_response(response))

        market_context = self._freechat_market_context(prompt)
        web_context = self._freechat_web_context(prompt)
        if web_context:
            market_context = f"{market_context}\n\n{web_context}".strip()
        assistant_prompt = build_fincli_assistant_prompt(prompt, market_context)
        request = AIRequest(prompt=assistant_prompt, model=self.config.settings.ai_model)
        response = self._run_async(self.ai_provider.complete(request))
        if not isinstance(response, AIResponse):
            raise CommandError("AI provider mengembalikan data tidak valid.")
        return CommandResult(_format_ai_response(response))

    def _web(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /web <query>")
        if args[0].lower() in {"sources", "source", "raw"}:
            source_query = " ".join(args[1:]).strip()
            if not source_query:
                raise CommandError("Format: /web sources <query>")
            results = self._run_async(self.web_research.research(source_query, limit=5))
            return CommandResult(_format_web_results(source_query, results))

        query = " ".join(args)
        results = self._run_async(self.web_research.research(query, limit=5))
        context = build_web_research_context(results)
        assistant_prompt = build_web_research_answer_prompt(query, context)
        request = AIRequest(prompt=assistant_prompt, model=self.config.settings.ai_model)
        response = self._run_async(self.ai_provider.complete(request))
        if not isinstance(response, AIResponse):
            raise CommandError("AI provider mengembalikan data tidak valid.")
        return CommandResult(_format_ai_response(response))

    def _analyze(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /analyze <symbol> [timeframe]")
        symbol = args[0].upper()
        timeframe = args[1] if len(args) >= 2 else "1d"
        candles = self._run_async(self.market_service.history(symbol, period="6mo", interval=timeframe))
        if not candles:
            raise CommandError(f"Data market kosong untuk {symbol}.")
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
            raise CommandError("AI provider mengembalikan data tidak valid.")
        return CommandResult(
            MarkdownBlock(f"AI Market Analysis: {symbol}", _format_ai_response(response), "Disclaimer: bukan nasihat keuangan.")
        )

    def _scan(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "export":
            return self._scan_export(args[1:])
        if not args or args[0].lower() != "watchlist":
            raise CommandError("Format: /scan watchlist [filter] [interval]")
        rows = self.watchlist.list()
        symbols = [str(row["symbol"]) for row in rows]
        if not symbols:
            return CommandResult(Panel("Watchlist kosong. Gunakan /watchlist add AAPL.", title="Scan"))
        filter_expression = args[1] if len(args) >= 2 else ""
        interval = args[2] if len(args) >= 3 else "1d"
        results = self._run_async(scan_symbols(symbols, self.market_service, filter_expression, interval=interval))
        return CommandResult(_format_scan_results(results, filter_expression or "all", interval))

    def _scan_export(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError("Format: /scan export <csv|json> <path> [filter] [interval]")
        export_format = args[0].lower()
        target = args[1]
        filter_expression = args[2] if len(args) >= 3 else ""
        interval = args[3] if len(args) >= 4 else "1d"
        rows = self.watchlist.list()
        symbols = [str(row["symbol"]) for row in rows]
        if not symbols:
            raise CommandError("Watchlist kosong. Gunakan /watchlist add AAPL.")
        results = self._run_async(scan_symbols(symbols, self.market_service, filter_expression, interval=interval))
        written = export_rows(_scan_result_rows(results), export_format, target)
        return CommandResult(Panel(f"Scan export selesai: {written}", title="Scan Export", border_style="green"))

    def _report(self, args: list[str]) -> CommandResult:
        if len(args) < 4 or args[0].lower() != "market":
            raise CommandError("Format: /report market <symbol> <md|json> <path> [interval]")
        symbol = args[1].upper()
        report_format = args[2].lower()
        target = args[3]
        interval = args[4] if len(args) >= 5 else "1d"
        overview = self._run_async(build_market_overview(symbol, self.market_service, interval))
        written = write_market_report(overview, report_format, target)
        return CommandResult(Panel(f"Market report selesai: {written}", title="Market Report", border_style="green"))

    def _calendar(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "export":
            return self._calendar_export(args[1:])
        start, end, country, impact = _parse_calendar_args(args)
        service = EconomicCalendarService(api_key=os.getenv("FINNHUB_API_KEY"))
        source = "finnhub"
        note = "Aktual dari provider Finnhub."
        try:
            events = self._run_async(service.events(start, end))
        except FinCLIError as exc:
            events, source, note = self._calendar_public_or_static_fallback(start, end, exc)
        events = filter_events(events, country=country, impact=impact)
        return CommandResult(_format_calendar(events, start, end, source, note))

    def _calendar_export(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError("Format: /calendar export <csv|json> <path> [today|week|from to] [country=US] [impact=high]")
        export_format = args[0].lower()
        target = args[1]
        start, end, country, impact = _parse_calendar_args(args[2:])
        service = EconomicCalendarService(api_key=os.getenv("FINNHUB_API_KEY"))
        try:
            events = self._run_async(service.events(start, end))
        except FinCLIError as exc:
            events, _, _ = self._calendar_public_or_static_fallback(start, end, exc)
        events = filter_events(events, country=country, impact=impact)
        written = export_rows(economic_event_rows(events), export_format, target)
        return CommandResult(Panel(f"Calendar export selesai: {written}", title="Calendar Export", border_style="green"))

    def _calendar_public_or_static_fallback(
        self, start: date, end: date, provider_error: FinCLIError
    ) -> tuple[list[EconomicEvent], str, str]:
        if not os.getenv("FINNHUB_API_KEY"):
            return fallback_events(start, end), "fallback", _calendar_fallback_note(provider_error, False)
        try:
            events = self._run_async(PublicEconomicCalendarService().events(start, end))
            if events:
                return (
                    events,
                    "public",
                    (
                        "Finnhub calendar unavailable for the current key, plan, or rate limit. "
                        "Using public economic calendar fallback; verify critical events with official sources."
                    ),
                )
        except FinCLIError as public_error:
            note = _calendar_static_fallback_note(provider_error, public_error)
            return fallback_events(start, end), "fallback", note
        return fallback_events(start, end), "fallback", _calendar_static_fallback_note(provider_error, None)

    def _run_async(self, awaitable: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, awaitable)
            return future.result()

    def _portfolio_market_values(self, row: dict[str, object]) -> tuple[float | None, float | None, float | None]:
        try:
            symbol = str(row["symbol"])
            quantity = float(row["quantity"])
            average_price = float(row["average_price"])
            quote = self._get_quote(symbol)
            current_price = quote.price
            if current_price is None:
                return None, None, None
            pnl = (current_price - average_price) * quantity
            invested = average_price * quantity
            pnl_percent = (pnl / invested * 100) if invested else None
            return current_price, pnl, pnl_percent
        except FinCLIError:
            return None, None, None
        except (TypeError, ValueError, KeyError):
            return None, None, None

    def _portfolio_performance_table(self) -> Table:
        risk = self._portfolio_risk_report()

        table = Table(title="Portfolio Performance", expand=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Cost Basis", _fmt(risk.total_cost_basis))
        table.add_row("Market Value", _fmt(risk.total_market_value))
        table.add_row("Unrealized PnL", _fmt(risk.unrealized_pnl))
        table.add_row("Realized PnL", _fmt(risk.realized_pnl))
        table.add_row("Total PnL", _fmt(risk.total_pnl))
        table.add_row("Health Score", f"{risk.health.score}/100 ({risk.health.label})")
        return table

    def _portfolio_risk_report(self) -> PortfolioRiskReport:
        positions = self.portfolio.list()
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        for row in positions:
            values[str(row["symbol"]).upper()] = self._portfolio_market_values(row)
        return build_portfolio_risk(positions, values, self.transactions.realized_pnl_total(), profile=self.user_profiles.get())

    def _portfolio_chart(self) -> CommandResult:
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics
        analytics = PortfolioAnalytics(self.db)
        snapshots = analytics.get_snapshots(limit=90)
        if not snapshots:
            return CommandResult(Panel("No portfolio snapshots yet. Use /portfolio snapshot to save current state.", title="Portfolio Chart"))
        ratios = analytics.calculate_risk_ratios()
        return CommandResult(_format_portfolio_chart(snapshots, ratios))

    def _portfolio_snapshot(self) -> CommandResult:
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics
        analytics = PortfolioAnalytics(self.db)
        positions = self.portfolio.list()
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        total_value = 0.0
        cost_basis = 0.0
        for row in positions:
            sym = str(row["symbol"]).upper()
            values[sym] = self._portfolio_market_values(row)
            qty = float(row["quantity"])
            avg = float(row["average_price"])
            cost_basis += qty * avg
            current, pnl, _ = values[sym]
            total_value += qty * float(current) if current is not None else qty * avg
        realized = self.transactions.realized_pnl_total()
        unrealized = total_value - cost_basis
        analytics.save_snapshot(total_value, cost_basis, unrealized, realized, {sym: {"value": v[0]} for sym, v in values.items()})
        return CommandResult(Panel(
            f"Portfolio snapshot saved.\nTotal value: ${total_value:,.2f}\nCost basis: ${cost_basis:,.2f}\nPnL: ${unrealized + realized:,.2f}",
            title="Portfolio Snapshot",
            border_style="green",
        ))

    def _portfolio_whatif(self, args: list[str]) -> CommandResult:
        if len(args) < 4:
            raise CommandError("Format: /portfolio whatif <add|sell> <symbol> <qty> <price>")
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics
        action = args[0].lower()
        symbol = args[1].upper()
        quantity = float(args[2])
        price = float(args[3])
        analytics = PortfolioAnalytics(self.db)
        positions = self.portfolio.list()
        values: dict[str, tuple[float | None, float | None, float | None]] = {}
        for row in positions:
            values[str(row["symbol"]).upper()] = self._portfolio_market_values(row)
        result = analytics.what_if(action, symbol, quantity, price, positions, values)
        return CommandResult(_format_whatif(result))

    def _portfolio_benchmark(self, args: list[str]) -> CommandResult:
        benchmark_symbol = args[0].upper() if args else "SPY"
        from fincli.app.modules.portfolio_analytics import PortfolioAnalytics
        analytics = PortfolioAnalytics(self.db)
        snapshots = analytics.get_snapshots(limit=90)
        if len(snapshots) < 2:
            return CommandResult(Panel("Need at least 2 portfolio snapshots. Use /portfolio snapshot to save daily.", title="Benchmark"))

        # Get benchmark price history
        bench_candles = self._run_async(self.market_service.history(benchmark_symbol, period="3mo", interval="1d"))
        if not bench_candles:
            return CommandResult(Panel(f"No benchmark data for {benchmark_symbol}.", title="Benchmark"))

        portfolio_values = [s.total_value for s in reversed(snapshots)]
        benchmark_values = [c.close for c in bench_candles]
        comparison = analytics.compare_benchmark(benchmark_values, portfolio_values, benchmark_symbol)
        return CommandResult(_format_benchmark(comparison))

    def _get_quote(self, symbol: str) -> Quote:
        normalized = symbol.upper()
        cache_key = f"quote:{normalized}"
        cached = self.cache.get(cache_key)
        if isinstance(cached, Quote):
            return cached
        quote = self._run_async(self.market_service.quote(normalized))
        if not isinstance(quote, Quote):
            raise CommandError("Provider quote mengembalikan data tidak valid.")
        self.cache.set(cache_key, quote)
        return quote

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

        results = getattr(self.market_service, "provider_results", [])[-6:]
        if not results:
            return f"{base}\nRecent provider results: none"
        lines = ["Recent provider results:"]
        for result in results:
            missing = f"; missing={', '.join(result.missing_fields)}" if result.missing_fields else ""
            message = f"; {result.message}" if result.message and result.message != "ok" else ""
            lines.append(f"- {result.provider}.{result.operation}: {result.status}{missing}{message}")
        return f"{base}\n" + "\n".join(lines)

    def _safe_quote(self, symbol: str) -> Quote | None:
        try:
            return self._get_quote(symbol)
        except FinCLIError:
            return None

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

    def _export(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /export <journal|portfolio|alerts|all> <csv|json> <path>")
        dataset = args[0].lower()

        if dataset == "all":
            if len(args) < 3:
                raise CommandError("Format: /export all <csv|json> <directory>")
            export_format = args[1].lower()
            target = args[2]
            from fincli.app.modules.exporter import export_all
            written = export_all(
                target,
                portfolio=self.portfolio.list(),
                journal=self.journal.list(limit=10_000),
                alerts=[dict(h.__dict__) if hasattr(h, '__dict__') else h for h in self.alerts.get_history()],
                trades=self.paper_trading.list_orders(limit=10_000),
                fmt=export_format,
            )
            return CommandResult(Panel(f"Batch export selesai: {len(written)} file(s) di {target}", title="Export", border_style="green"))

        if len(args) < 3:
            raise CommandError("Format: /export <journal|portfolio|alerts> <csv|json> <path>")
        export_format = args[1].lower()
        target = args[2]
        if dataset == "journal":
            rows = self.journal.list(limit=10_000)
        elif dataset == "portfolio":
            rows = self.portfolio.list()
        elif dataset == "alerts":
            rows = [dict(h.__dict__) if hasattr(h, '__dict__') else h for h in self.alerts.get_history()]
        else:
            raise CommandError("Format: /export <journal|portfolio|alerts|all> <csv|json> <path>")
        written = export_rows(rows, export_format, target)
        return CommandResult(Panel(f"Export {dataset} selesai: {written}", title="Export", border_style="green"))

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
                f"News provider tidak dikenal: {', '.join(unknown)}",
                "Gunakan /news_model list atau /news_model search <query> untuk melihat provider yang tersedia.",
            )


def _format_quote(quote: Quote) -> str:
    price = "N/A" if quote.price is None else f"{quote.price:,.4f}"
    return (
        f"Quote: {quote.symbol}\n"
        f"Price: {price} {quote.currency}\n"
        f"Provider: {quote.provider}\n"
        f"Status: {quote.status}\n"
        f"Timestamp: {quote.timestamp.isoformat(timespec='seconds')}\n"
        "Catatan: yfinance fallback biasanya delayed, bukan realtime."
    )


def _format_sessions(sessions: list[dict[str, object]], current_session_id: str) -> Table:
    table = Table(title="FinCLI Sessions", expand=True)
    table.add_column("Current", justify="center", width=7)
    table.add_column("Session ID", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    table.add_column("Events", justify="right")
    table.add_column("Updated", style="dim")
    for session in sessions:
        session_id = str(session["id"])
        table.add_row(
            "*" if session_id == current_session_id else "",
            session_id,
            str(session["title"]),
            str(session["event_count"]),
            str(session["updated_at"]),
        )
    if not sessions:
        table.add_row("-", "-", "Belum ada session.", "0", "-")
    table.caption = "/history current | /history show <session_id> | /history delete <session_id>"
    return table


def _format_session_events(session: dict[str, object], events: list[dict[str, object]], current: bool = False) -> Table:
    marker = "current" if current else "saved"
    table = Table(title=f"Session {session['id']} ({marker}) - {session['title']}", expand=True)
    table.add_column("#", justify="right", width=4)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Status", style="cyan", no_wrap=True)
    table.add_column("Command", style="white")
    table.add_column("Output Preview", style="dim")
    for event in events:
        table.add_row(
            str(event["id"]),
            str(event["created_at"]),
            str(event["status"]),
            str(event["command"]),
            str(event["output_preview"] or "")[:180],
        )
    if not events:
        table.add_row("-", "-", "-", "Belum ada command di session ini.", "")
    table.caption = "/history sessions | /history save <title> | /history clear current"
    return table


def _render_history_preview(renderable: Any) -> str:
    if renderable is None:
        return ""
    if isinstance(renderable, str):
        return renderable[:1200]
    console = Console(width=100, record=True, force_terminal=False, file=io.StringIO())
    try:
        console.print(renderable)
        return console.export_text(clear=False).strip()[:1200]
    except Exception:
        return str(renderable)[:1200]


def _format_dashboard(
    provider_chain: list[str],
    watchlist_rows: list[dict[str, object]],
    portfolio_rows: list[dict[str, object]],
    journal_stats: JournalStats,
    realized_pnl: float,
    quote_getter: Any,
    portfolio_value_getter: Any,
) -> Table:
    table = Table(title="FinCLI Dashboard", expand=True)
    table.add_column("Area", style="cyan", no_wrap=True)
    table.add_column("Summary", style="white")
    table.add_column("Next Action", style="dim")

    table.add_row(
        "Provider Chain",
        ", ".join(provider_chain) if provider_chain else "N/A",
        "/provider status | /provider priority finnhub,yfinance",
    )

    watchlist_symbols = [str(row["symbol"]) for row in watchlist_rows]
    quote_bits: list[str] = []
    for symbol in watchlist_symbols[:4]:
        quote = quote_getter(symbol)
        quote_bits.append(f"{symbol} {_fmt(quote.price) if quote else 'N/A'}")
    table.add_row(
        "Watchlist",
        f"{len(watchlist_rows)} symbol(s)" + (f" | {', '.join(quote_bits)}" if quote_bits else ""),
        "/watchlist add AAPL | /scan watchlist trend=bullish",
    )

    market_value = 0.0
    unrealized = 0.0
    for row in portfolio_rows:
        current_price, pnl, _ = portfolio_value_getter(row)
        if current_price is not None:
            market_value += float(row["quantity"]) * current_price
        if pnl is not None:
            unrealized += pnl
    portfolio_summary = (
        f"{len(portfolio_rows)} position(s) | Market Value {_fmt(market_value)} | "
        f"Unrealized PnL {_fmt(unrealized)} | Realized PnL {_fmt(realized_pnl)}"
        if portfolio_rows
        else "No local portfolio positions"
    )
    table.add_row("Portfolio", portfolio_summary, "/tx add buy AAPL 10 185 | /portfolio performance")

    table.add_row(
        "Journal",
        (
            f"{journal_stats.total_entries} entries | Win Rate {_fmt(journal_stats.win_rate)} | "
            f"Top {journal_stats.top_instrument}"
        ),
        "/journal stats | /journal review",
    )

    table.add_row(
        "Market",
        "Use /market for compact quote + technical + structure + news + fundamentals.",
        "/market AAPL 1d | /analyze AAPL 1d",
    )
    if unrealized != 0 or realized_pnl != 0:
        table.add_row(
            "Risk Color",
            semantic_text(f"Total PnL {_fmt(realized_pnl + unrealized)} {'gain' if realized_pnl + unrealized >= 0 else 'loss'}"),
            "green=positive | red=negative | yellow=caution",
        )
    return table


def _format_market_overview(overview: MarketOverview) -> Table:
    table = Table(title=f"Market Overview: {overview.symbol} | {overview.timeframe}", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")
    table.add_column("Context", style="dim")

    quality = overview.data_quality
    table.add_row(
        "Data Quality",
        semantic_text(quality.compact()),
        (
            f"quote={quality.quote}; ohlcv={quality.ohlcv}; news={quality.news}; "
            f"fundamentals={quality.fundamentals}; provider={quality.provider}; "
            f"Reliability={quality.reliability_status}; "
            f"Missing={', '.join(quality.missing_fields) if quality.missing_fields else 'none'}"
        ),
    )
    source_quality = overview.source_quality
    table.add_row(
        "Source Quality",
        semantic_text(source_quality.compact()),
        source_quality.detail,
    )
    table.add_row(
        "Quote",
        f"{_fmt(overview.quote.price)} {overview.quote.currency}",
        semantic_text(f"{overview.quote.provider} | {overview.quote.status} | {overview.quote.timestamp.isoformat(timespec='seconds')}"),
    )
    table.add_row(
        "Technical",
        semantic_text(f"RSI {_fmt(overview.technical.rsi)} | Trend {overview.technical.trend_bias}"),
        f"MACD {_fmt(overview.technical.macd)} / Signal {_fmt(overview.technical.macd_signal)} | ATR {_fmt(overview.technical.atr)}",
    )
    table.add_row(
        "Key Levels",
        f"Support {_fmt(overview.technical.support)} | Resistance {_fmt(overview.technical.resistance)}",
        f"Bollinger {_fmt(overview.technical.bollinger_lower)} - {_fmt(overview.technical.bollinger_upper)}",
    )
    table.add_row(
        "Market Structure",
        semantic_text(f"{overview.structure.trend} | {overview.structure.latest_pattern}"),
        f"BOS={overview.structure.break_of_structure}; CHoCH={overview.structure.change_of_character}; Liquidity={overview.structure.liquidity_area}",
    )

    if overview.fundamentals is not None:
        table.add_row(
            "Fundamentals",
            f"P/E {_fmt(overview.fundamentals.pe_ratio)} | EPS {_fmt(overview.fundamentals.eps)}",
            f"Sector={overview.fundamentals.sector or 'N/A'}; Industry={overview.fundamentals.industry or 'N/A'}; Market Cap={_fmt(overview.fundamentals.market_cap)}",
        )
    else:
        table.add_row("Fundamentals", "N/A", "Provider did not return fundamentals.")

    if overview.news:
        latest_news = overview.news[0]
        table.add_row(
            "Latest News",
            latest_news.title,
            f"{latest_news.source} | {latest_news.published_at.isoformat(timespec='seconds') if latest_news.published_at else 'unknown time'}",
        )
    else:
        table.add_row("Latest News", "N/A", "Provider did not return recent news.")

    table.add_row("Disclaimer", "Informational only", "Bukan nasihat keuangan.")
    return table


def _format_portfolio_risk(report: PortfolioRiskReport) -> Table:
    table = Table(title="Portfolio Risk v3 | Portfolio Risk v2 compatible", expand=True)
    table.add_column("Section", style="cyan", no_wrap=True)
    table.add_column("Metric", style="white", overflow="fold")
    table.add_column("Value", justify="right", overflow="fold")

    table.add_row("Health Score", report.health.label, f"{report.health.score}/100")
    table.add_row("Health Notes", ", ".join(report.health.notes), "")
    table.add_row("PnL Detail", "Cost Basis", _fmt(report.total_cost_basis))
    table.add_row("PnL Detail", "Market Value", _fmt(report.total_market_value))
    table.add_row("PnL Detail", "Realized PnL", semantic_text(_fmt(report.realized_pnl)))
    table.add_row("PnL Detail", "Unrealized PnL", semantic_text(_fmt(report.unrealized_pnl)))
    table.add_row("PnL Detail", "Total PnL", semantic_text(_fmt(report.total_pnl)))
    table.add_row("Drawdown Estimate", "Unrealized drawdown vs cost basis", f"{report.drawdown_estimate:.2f}%")
    table.add_row(
        "Risk Budget",
        f"{report.risk_budget.profile_gameplay} | {report.risk_budget.note}",
        f"{_fmt(report.risk_budget.risk_per_trade)} / {_fmt(report.risk_budget.max_portfolio_risk)} {report.risk_budget.currency}",
    )
    table.add_row(
        "Concentration Risk",
        f"{report.concentration.level}: {report.concentration.top_symbol}",
        f"{report.concentration.top_weight:.2f}%",
    )
    table.add_row("Concentration Risk", report.concentration.note, "")

    if report.exposure_by_asset_class:
        for exposure in report.exposure_by_asset_class.values():
            table.add_row(
                "Exposure by Asset Class",
                f"{exposure.asset_class} ({exposure.count} position(s))",
                f"{_fmt(exposure.market_value)} | {exposure.weight:.2f}%",
            )
    else:
        table.add_row("Exposure by Asset Class", "No positions", "-")
    if report.currency_exposure:
        for exposure in report.currency_exposure.values():
            table.add_row(
                "Currency Exposure",
                f"{exposure.currency} ({exposure.count} position(s))",
                f"{_fmt(exposure.market_value)} | {exposure.weight:.2f}%",
            )
    else:
        table.add_row("Currency Exposure", "No positions", "-")
    if report.asset_class_warnings:
        for warning in report.asset_class_warnings:
            table.add_row("Asset-Class Cap Warning", f"{warning.level}: {warning.note}", f"cap {warning.cap:.2f}%")
    else:
        table.add_row("Asset-Class Cap Warning", "none", "-")
    table.caption = "Portfolio Risk v3 is local analytics only. It is not financial advice."
    return table


def _format_technical(
    symbol: str,
    interval: str,
    summary: TechnicalSummary,
    signal: TechnicalSignal | None = None,
    ai_summary: str = "",
    debate: TechnicalDebate | None = None,
) -> str:
    signal_text = format_signal(signal) if signal is not None else "Signal: CAUTION\nSignal Reasoning:\n- Signal unavailable."
    debate_text = format_debate(debate) if debate is not None else "Technical Debate:\n- Debate unavailable."
    return (
        f"Technical Analysis: {symbol}\n"
        f"Timeframe: {interval}\n"
        f"Latest Close: {_fmt(summary.latest_close)}\n"
        f"Trend Bias: {summary.trend_bias}\n"
        f"SMA 5: {_fmt(summary.sma_fast)}\n"
        f"SMA 20: {_fmt(summary.sma_slow)}\n"
        f"EMA 12: {_fmt(summary.ema_fast)}\n"
        f"RSI 14: {_fmt(summary.rsi)}\n"
        f"MACD: {_fmt(summary.macd)} | Signal: {_fmt(summary.macd_signal)}\n"
        f"Bollinger: upper {_fmt(summary.bollinger_upper)} | lower {_fmt(summary.bollinger_lower)}\n"
        f"ATR 14: {_fmt(summary.atr)}\n"
        f"Support: {_fmt(summary.support)} | Resistance: {_fmt(summary.resistance)}\n"
        f"Volume Latest: {_fmt(summary.volume_latest)}\n"
        f"\n{signal_text}\n"
        f"\n{debate_text}\n"
        f"\n{ai_summary}\n"
        "Disclaimer: analisis ini bersifat informasional, bukan nasihat keuangan."
    )


def _format_structure(symbol: str, interval: str, structure: MarketStructureSummary) -> str:
    return (
        f"Market Structure: {symbol}\n"
        f"Timeframe: {interval}\n"
        f"Trend: {structure.trend}\n"
        f"Latest Pattern: {structure.latest_pattern}\n"
        f"Break of Structure: {structure.break_of_structure}\n"
        f"Change of Character: {structure.change_of_character}\n"
        f"Support: {_fmt(structure.support)}\n"
        f"Resistance: {_fmt(structure.resistance)}\n"
        f"Liquidity Area: {structure.liquidity_area or 'N/A'}\n"
        f"Risk Zone: {structure.risk_zone or 'N/A'}\n"
        "Disclaimer: struktur pasar ini bersifat skenario, bukan nasihat keuangan."
    )


def _format_multi_timeframe(analysis: MultiTimeframeAnalysis) -> Table:
    table = Table(title=f"Multi-Timeframe Analysis: {analysis.symbol}", expand=True)
    table.add_column("Timeframe", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Candles", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Trend")
    table.add_column("Structure")
    table.add_column("RSI", justify="right")
    table.add_column("MACD", justify="right")
    table.add_column("Support / Resistance", overflow="fold")
    table.add_column("Note", overflow="fold")
    for frame in analysis.frames:
        table.add_row(
            frame.timeframe,
            frame.status,
            str(frame.candles),
            _fmt(frame.latest_close),
            semantic_text(frame.trend_bias),
            semantic_text(frame.structure_trend),
            _fmt(frame.rsi),
            _fmt(frame.macd),
            f"{_fmt(frame.support)} / {_fmt(frame.resistance)}",
            frame.note or "-",
        )
    table.caption = (
        f"Alignment: {analysis.alignment} | Bias: {analysis.bias} | Score: {analysis.score} | "
        f"Risk: {analysis.risk_note}"
    )
    return table


def _format_backtest(result: BacktestResult) -> Table:
    table = Table(title=f"Backtest: {result.symbol} | {result.strategy} | {result.interval}", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    # Performance
    table.add_row("Total Return", semantic_text(f"{result.total_return_percent:+.2f}% (${result.total_return_absolute:+,.2f})"))
    table.add_row("Win Rate", f"{result.win_rate:.1f}%")
    table.add_row("Max Drawdown", semantic_text(f"{result.max_drawdown_percent:.2f}%"))
    table.add_row("Exposure", f"{result.exposure_percent:.1f}%")

    # Risk ratios
    table.add_row("Sharpe Ratio", f"{result.sharpe_ratio:.2f}")
    table.add_row("Sortino Ratio", f"{result.sortino_ratio:.2f}")
    table.add_row("Calmar Ratio", f"{result.calmar_ratio:.2f}")

    # Trade stats
    table.add_row("Trades", f"{result.total_trades} (W:{result.winning_trades} / L:{result.losing_trades})")
    table.add_row("Profit Factor", f"{result.profit_factor:.2f}")
    table.add_row("Expectancy", f"{result.expectancy:.2f}%")
    table.add_row("Avg Win / Loss", f"{result.avg_win:+.2f}% / {result.avg_loss:+.2f}%")
    table.add_row("Largest Win / Loss", f"{result.largest_win:+.2f}% / {result.largest_loss:+.2f}%")
    table.add_row("Streaks", f"W:{result.consecutive_wins} / L:{result.consecutive_losses}")

    # Costs
    table.add_row("Total Fees", f"${result.total_fees:,.2f}")
    table.add_row("Fee Profile", result.fee_profile_used)
    table.add_row("Position Sizing", result.position_sizer_used)

    # Monte Carlo
    if result.monte_carlo:
        mc = result.monte_carlo
        table.add_row("Monte Carlo", f"5th={mc.percentile_5:+.1f}% | 50th={mc.percentile_50:+.1f}% | 95th={mc.percentile_95:+.1f}%")

    # Walk-forward
    if result.walk_forward:
        wf = result.walk_forward
        table.add_row("Walk-Forward", f"IS={wf.in_sample.total_return_percent:+.1f}% | OOS={wf.out_of_sample.total_return_percent:+.1f}% | Overfit={wf.overfit_ratio:.2f}")

    table.add_row("Notes", " ".join(result.notes))
    table.caption = "Backtest includes fees/slippage/spread. Educational only — past performance does not guarantee future results."
    return table


def _format_alerts(rows: list[dict[str, object]]) -> Table:
    table = Table(title="Price Alerts", expand=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Condition")
    table.add_column("Target", justify="right")
    table.add_column("Status")
    table.add_column("Note", overflow="fold")
    table.add_column("Created")
    for row in rows:
        table.add_row(
            str(row["id"]),
            str(row["symbol"]),
            str(row["condition"]),
            _fmt(float(row["target"])),
            semantic_text("active hold" if int(row["active"]) else f"triggered {row['triggered_at']}"),
            str(row["note"] or "-"),
            str(row["created_at"]),
        )
    if not rows:
        table.add_row("-", "-", "-", "-", "-", "No alerts. Use /alert add AAPL above 200.", "-")
    return table


def _format_alert_checks(results: list[AlertCheckResult]) -> Table:
    table = Table(title="Alert Check", expand=True)
    table.add_column("ID", justify="right", no_wrap=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Condition")
    table.add_column("Target", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Triggered", justify="center")
    table.add_column("Note", overflow="fold")
    for result in results:
        table.add_row(
            str(result.id),
            result.symbol,
            result.condition,
            _fmt(result.target),
            _fmt(result.current_price),
            semantic_text("YES breakout confirmed" if result.triggered else "no hold"),
            result.note or "-",
        )
    if not results:
        table.add_row("-", "-", "-", "-", "-", "-", "No active alerts.")
    return table


def _format_alert_history(entries: list[object]) -> Table:
    table = Table(title="Alert History", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Symbol", style="cyan")
    table.add_column("Condition")
    table.add_column("Target", justify="right")
    table.add_column("Actual", justify="right")
    table.add_column("Time")
    for entry in entries:
        table.add_row(
            str(getattr(entry, "id", "-")),
            str(getattr(entry, "symbol", "-")),
            str(getattr(entry, "condition", "-")),
            _fmt(getattr(entry, "target", 0)),
            _fmt(getattr(entry, "actual_value", None)),
            str(getattr(entry, "created_at", "-")),
        )
    if not entries:
        table.add_row("-", "-", "-", "-", "-", "No alert history.")
    return table


def _format_portfolio_chart(snapshots: list[object], ratios: object) -> Table:
    table = Table(title="Portfolio Performance", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")

    if snapshots:
        latest = snapshots[0]
        oldest = snapshots[-1]
        total_return = ((latest.total_value - oldest.total_value) / oldest.total_value * 100) if oldest.total_value > 0 else 0
        table.add_row("Period", f"{len(snapshots)} snapshots")
        table.add_row("Latest Value", f"${latest.total_value:,.2f}")
        table.add_row("Period Return", f"{total_return:+.2f}%")

    table.add_row("Sharpe Ratio", f"{ratios.sharpe:.2f}")
    table.add_row("Sortino Ratio", f"{ratios.sortino:.2f}")
    table.add_row("Calmar Ratio", f"{ratios.calmar:.2f}")
    table.add_row("Annualized Return", f"{ratios.annualized_return:+.2f}%")
    table.add_row("Annualized Volatility", f"{ratios.annualized_volatility:.2f}%")
    table.add_row("Max Drawdown", f"{ratios.max_drawdown:.2f}%")
    table.caption = "Use /portfolio snapshot to save daily values for chart tracking."
    return table


def _format_whatif(result: object) -> Table:
    table = Table(title="What-If Analysis", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Action", str(getattr(result, "action", "-")))
    table.add_row("Symbol", str(getattr(result, "symbol", "-")))
    table.add_row("Current Weight", f"{getattr(result, 'current_weight', 0):.1f}%")
    table.add_row("New Weight", f"{getattr(result, 'new_weight', 0):.1f}%")
    table.add_row("Current Concentration", str(getattr(result, "current_concentration", "-")))
    table.add_row("New Concentration", str(getattr(result, "new_concentration", "-")))
    table.add_row("Note", str(getattr(result, "note", "-")))
    table.caption = "What-if analysis is informational, not financial advice."
    return table


def _format_benchmark(comparison: object) -> Table:
    table = Table(title=f"Benchmark: {getattr(comparison, 'benchmark_symbol', '?')}", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Portfolio Return", f"{getattr(comparison, 'portfolio_return', 0):+.2f}%")
    table.add_row("Benchmark Return", f"{getattr(comparison, 'benchmark_return', 0):+.2f}%")
    table.add_row("Alpha", f"{getattr(comparison, 'alpha', 0):+.2f}%")
    table.add_row("Beta", f"{getattr(comparison, 'beta', 0):.2f}")
    table.add_row("Correlation", f"{getattr(comparison, 'correlation', 0):.2f}")
    table.add_row("Period", f"{getattr(comparison, 'period_days', 0)} days")
    table.add_row("Note", str(getattr(comparison, "note", "-")))
    table.caption = "Benchmark comparison requires daily portfolio snapshots. Use /portfolio snapshot."
    return table


def _format_scan_results(results: list[ScanResult], filter_expression: str, interval: str) -> Table:
    table = Table(title=f"Scan Watchlist | {filter_expression} | {interval}", expand=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Close", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("Trend")
    table.add_column("Support", justify="right")
    table.add_column("Resistance", justify="right")
    table.add_column("Reason")
    for result in results:
        table.add_row(
            result.symbol,
            _fmt(result.latest_close),
            _fmt(result.rsi),
            semantic_text(result.trend_bias),
            _fmt(result.support),
            _fmt(result.resistance),
            semantic_text(result.reason),
        )
    if not results:
        table.add_row("-", "-", "-", "-", "-", "-", "Tidak ada symbol yang match.")
    return table


def _scan_result_rows(results: list[ScanResult]) -> list[dict[str, object]]:
    return [
        {
            "symbol": item.symbol,
            "latest_close": item.latest_close,
            "rsi": item.rsi,
            "trend_bias": item.trend_bias,
            "support": item.support,
            "resistance": item.resistance,
            "matched": item.matched,
            "reason": item.reason,
        }
        for item in results
    ]


def _parse_timeframes(value: str) -> tuple[str, ...]:
    frames = tuple(frame.strip().lower() for frame in value.split(",") if frame.strip())
    if not frames:
        raise CommandError("Timeframe tidak valid. Contoh: /mtf AAPL 1d,1h,15m")
    if len(frames) > 6:
        raise CommandError("Maksimal 6 timeframe dalam satu /mtf.")
    return frames


def _parse_news_lookback(args: list[str]) -> int | None:
    if not args:
        return None
    raw = args[0].strip().lower()
    if len(args) > 1 or not raw.endswith("d") or not raw[:-1].isdigit():
        raise CommandError("Format: /news <symbol> [1d-30d]")
    days = int(raw[:-1])
    if days < 1 or days > 30:
        raise CommandError("Lookback /news maksimal 30d. Contoh: /news TSLA 7d")
    return days


def _extract_option_value(args: list[str], option: str) -> str | None:
    if option not in args:
        return None
    index = args.index(option)
    if len(args) <= index + 1:
        raise CommandError(f"Format opsi: {option} <value>")
    return args[index + 1]


def _parse_calendar_args(args: list[str]) -> tuple[date, date, str | None, str | None]:
    country: str | None = None
    impact: str | None = None
    positional: list[str] = []

    for arg in args:
        normalized = arg.lower()
        if normalized.startswith("country="):
            country = arg.split("=", 1)[1].upper()
        elif normalized.startswith("impact="):
            impact = arg.split("=", 1)[1].lower()
        elif normalized in {"high", "medium", "low"}:
            impact = normalized
        elif len(arg) in {2, 3} and arg.isalpha():
            country = arg.upper()
        else:
            positional.append(arg)

    if not positional:
        start, end = default_calendar_window("week")
    elif positional[0].lower() in {"today", "week"}:
        start, end = default_calendar_window(positional[0].lower())
    elif len(positional) >= 2:
        start = _parse_date_arg(positional[0])
        end = _parse_date_arg(positional[1])
    else:
        raise CommandError("Format: /calendar [today|week|<from YYYY-MM-DD> <to YYYY-MM-DD>] [country=US] [impact=high]")

    if end < start:
        raise CommandError("Tanggal akhir calendar tidak boleh lebih kecil dari tanggal awal.")
    return start, end, country, impact


def _parse_date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError("Tanggal calendar harus format YYYY-MM-DD.") from exc


def _calendar_fallback_note(exc: FinCLIError, has_key: bool) -> str:
    if has_key:
        return (
            "FinCLI memakai fallback kategori event. "
            "Periksa API key, entitlement/plan Finnhub, atau rate-limit untuk data aktual."
        )
    return "FinCLI memakai fallback kategori event. Isi FINNHUB_API_KEY untuk data aktual."


def _calendar_static_fallback_note(provider_error: FinCLIError, public_error: FinCLIError | None) -> str:
    _ = provider_error, public_error
    return (
        "Using static macro fallback. Finnhub calendar endpoint is unavailable for the current key/plan "
        "or provider rate limit, and public calendar fallback is temporarily unavailable. "
        "Check /provider key status, Finnhub calendar entitlement, and try again later."
    )


def _format_calendar(events: list[EconomicEvent], start: date, end: date, source: str, note: str) -> Table:
    reliability = _calendar_reliability_status(events, source, note)
    quality = _calendar_data_quality(events, source, reliability)
    table = Table(
        title=f"Economic Calendar | {start.isoformat()} to {end.isoformat()} | {source} | {reliability}",
        expand=True,
    )
    table.add_column("Time", style="cyan", no_wrap=True, width=16, max_width=16)
    table.add_column("Country", no_wrap=True, width=7, max_width=7)
    table.add_column("Impact", no_wrap=True, width=6, max_width=6)
    table.add_column("Event", style="white", overflow="fold")
    table.add_column("Actual", justify="right", no_wrap=True, width=10, max_width=14)
    table.add_column("Forecast", justify="right", no_wrap=True, width=10, max_width=14)
    table.add_column("Prev", justify="right", no_wrap=True, width=10, max_width=14)

    for event in events:
        event_time = event.time.isoformat(timespec="minutes") if event.time else "TBA"
        table.add_row(
            event_time,
            event.country,
            event.impact,
            event.event,
            event.actual or "-",
            event.estimate or "-",
            event.previous or "-",
        )

    if not events:
        table.add_row("-", "-", "-", "Tidak ada event yang cocok dengan filter.", "-", "-", "-")
    summary = calendar_summary(events)
    table.add_row(
        "Summary",
        source,
        "-",
        f"total={summary['total']}; high={summary.get('high', 0)}; medium={summary.get('medium', 0)}; "
        f"low={summary.get('low', 0)}; reliability={reliability}",
        "-",
        "-",
        "-",
    )
    table.add_row("Note", source, "-", note, "-", "-", "-")
    table.caption = f"Data Quality: {quality.compact()}"
    return table


def _calendar_reliability_status(events: list[EconomicEvent], source: str, note: str) -> str:
    normalized_source = source.lower()
    normalized_note = note.lower()
    if normalized_source == "finnhub" and events:
        return STATUS_OK
    if normalized_source == "fallback":
        return STATUS_SCHEDULE_ONLY
    if "static macro fallback" in normalized_note or "fallback kategori" in normalized_note:
        return STATUS_SCHEDULE_ONLY
    if events:
        return STATUS_PARTIAL_DATA
    return STATUS_UNAVAILABLE


def _calendar_data_quality(events: list[EconomicEvent], source: str, reliability: str) -> DataQualityReport:
    score = 70 if events else 20
    if reliability == STATUS_OK:
        score = 90
    elif reliability == STATUS_SCHEDULE_ONLY:
        score = 45 if events else 25
    missing = () if reliability == STATUS_OK else ("actual", "estimate", "previous")
    tier = "strong" if score >= 85 else "usable" if score >= 65 else "partial" if score >= 40 else "weak"
    return DataQualityReport(
        score=score,
        quote="not_applicable",
        ohlcv="not_applicable",
        news="not_applicable",
        fundamentals=f"{len(events)} calendar event(s)",
        provider=source,
        tier=tier,
        freshness="calendar_window",
        reliability_status=reliability,
        missing_fields=missing,
        label=f"{tier} | {reliability}",
    )


def _format_provider_list() -> Table:
    table = Table(title="Market Providers", expand=True)
    table.add_column("Name", style="cyan")
    table.add_column("Realtime")
    table.add_column("Status")
    table.add_column("Notes")
    for provider in MarketProviderManager().list_providers():
        table.add_row(provider.name, str(provider.realtime), provider.status, provider.notes)
    return table


def _format_provider_entitlements(items: list[ProviderEntitlement]) -> Table:
    table = Table(title="Provider Entitlements and Data Labels", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Realtime Label", style="yellow", no_wrap=True)
    table.add_column("Asset Classes", overflow="fold")
    table.add_column("Capabilities", overflow="fold")
    table.add_column("Limitations", overflow="fold")
    for item in items:
        table.add_row(
            item.provider,
            item.status,
            item.realtime_label,
            ", ".join(item.asset_classes),
            ", ".join(item.capabilities),
            "; ".join(item.limitations),
        )
    return table


def _format_provider_capabilities() -> Table:
    table = Table(title="Command Capability Matrix", expand=True)
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Provider-Dependent", no_wrap=True)
    table.add_column("Needs", overflow="fold")
    table.add_column("Note", overflow="fold")
    for capability in capability_rows():
        table.add_row(
            capability.command,
            "yes" if capability.provider_dependent else "no",
            ", ".join(capability.needs),
            capability.note,
        )
    table.caption = capability_summary()
    return table


def _format_provider_key_status(manager: MarketProviderManager) -> Table:
    table = Table(title="Market Provider API Key Status", expand=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Source")
    for row in manager.key_status():
        table.add_row(row["provider"], row["key"], row["status"], row["source"])
    return table


def _format_secrets_status(secrets: dict[str, str]) -> Table:
    table = Table(title="Local Secrets Status", expand=True)
    table.add_column("Key", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Source")
    for key in sorted(secrets):
        table.add_row(key, "set", "~/.fincli/secrets.env")
    if not secrets:
        table.add_row("-", "empty", "No local secrets stored.")
    table.caption = "Values are never printed. Use /secrets clear before publishing screenshots or sharing a machine."
    return table


def _format_security_status(router: object) -> Table:
    table = Table(title="🔒 Security Status", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail")

    secrets = read_secrets()
    table.add_row("Secrets Stored", str(len(secrets)), "API keys in ~/.fincli/secrets.env")
    table.add_row("Secret Redaction", "active", "All error messages are redacted before display")
    table.add_row("Input Validation", "active", "Symbols, paths, and numbers are validated")
    table.add_row("Rate Limiting", "active", "Per-command rate limits enforced")
    table.add_row("Audit Log", "active", f"{router.audit_log.count_events()} events recorded")
    table.add_row("Path Traversal Protection", "active", "File operations validate paths")
    table.add_row("File Permissions", "0o600", "Secrets file is owner-read-write only")

    table.caption = "Use /security audit to view audit log. Use /security lockdown for emergency secret wipe."
    return table


def _format_audit_events(events: list[object]) -> Table:
    table = Table(title="🔐 Security Audit Log", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Event", style="cyan", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    table.add_column("Time", no_wrap=True)
    for event in events:
        table.add_row(
            str(getattr(event, "id", "-")),
            str(getattr(event, "event_type", "-")),
            str(getattr(event, "detail", ""))[:100],
            str(getattr(event, "created_at", "-")),
        )
    if not events:
        table.add_row("-", "-", "No audit events recorded.", "-")
    table.caption = "Audit log is immutable. Events are never modified or deleted."
    return table


def _format_security_scan(secrets: dict[str, str]) -> Table:
    table = Table(title="🔍 Security Scan", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Result")

    # Check secrets
    if secrets:
        table.add_row("Secrets Found", f"{len(secrets)} API key(s) stored locally")
        table.add_row("Secret File", "~/.fincli/secrets.env exists")
    else:
        table.add_row("Secrets Found", "None (clean)")

    # Check for common issues
    table.add_row("Prepublish Check", "Run: python scripts/prepublish_check.py")
    table.add_row("Git Status", "Run: git status --short --ignored")

    table.caption = "Use /secrets clear to remove all stored secrets. Use /privacy purge for full cleanup."
    return table


def _format_provider_metrics(service: MarketDataService) -> Table:
    table = Table(title="Provider Metrics Dashboard", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Session Calls", justify="right")
    table.add_column("All-Time Calls", justify="right")
    table.add_column("Success Rate", justify="right")
    table.add_column("Avg Latency", justify="right")
    table.add_column("Fallback Count", justify="right")
    table.add_column("Error Count", justify="right")
    table.add_column("Circuit", no_wrap=True)
    table.add_column("Failure Streak", justify="right")
    table.add_column("Last Status", no_wrap=True)

    metrics = service.provider_metrics_snapshot()
    persisted = service.metrics_store.snapshot() if getattr(service, "metrics_store", None) is not None else {}
    for provider in service.providers:
        name = provider.name
        metric = metrics.get(name)
        persisted_metric = persisted.get(name)
        if metric is None:
            table.add_row(name, "0", str(persisted_metric.calls if persisted_metric else 0), "0.00%", "0.00ms", "0", "0", "closed", "0", "not_called")
            continue
        table.add_row(
            name,
            str(metric.calls),
            str(persisted_metric.calls if persisted_metric else metric.calls),
            f"{metric.success_rate:.2f}%",
            f"{metric.avg_latency_ms:.2f}ms",
            str(metric.fallbacks),
            str(metric.errors),
            "open" if metric.circuit_open else "closed",
            str(metric.consecutive_failures),
            metric.last_status,
        )
    table.caption = (
        f"Active provider: {service.primary_provider.name}. "
        "Session metrics reset per run; all-time calls persist in local SQLite."
    )
    return table


def _format_symbol_search(query: str, results: list[SymbolSearchResult]) -> Table:
    table = Table(title=f"Symbol Search: {query}", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Class", no_wrap=True)
    table.add_column("Exchange", no_wrap=True)
    table.add_column("Currency", no_wrap=True)
    table.add_column("Provider Symbols", overflow="fold")
    table.add_column("Notes", overflow="fold")
    for result in results:
        table.add_row(
            result.symbol,
            result.name,
            result.asset_class,
            result.exchange or "-",
            result.currency or "-",
            _provider_symbol_text(result.provider_symbols or {}),
            result.notes or "-",
        )
    if not results:
        table.add_row("-", "No local symbol match.", "-", "-", "-", "-", "Try /symbol resolve <symbol>.")
    table.caption = "Use /symbol resolve <symbol> to inspect provider-specific normalization for any symbol."
    return table


def _format_symbol_matrix(
    symbol: str,
    resolver: SymbolResolver | None = None,
    asset_class: str | None = None,
) -> Table:
    matrix = (resolver or SymbolResolver()).matrix(symbol)
    table = Table(title=f"Provider Symbol Normalization: {symbol}", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Normalized Symbol", style="white")
    table.add_column("Asset Class", no_wrap=True)
    table.add_column("Confidence", no_wrap=True)
    table.add_column("Original", style="dim")
    for provider, resolved in matrix.items():
        asset = asset_class or resolved.asset_class
        table.add_row(provider, resolved.symbol, asset, resolved.confidence, resolved.original)
    table.caption = "Normalization does not guarantee provider entitlement. Check /provider entitlement and provider plan."
    return table


def _provider_symbol_text(provider_symbols: dict[str, str]) -> str:
    return " | ".join(f"{provider}:{symbol}" for provider, symbol in provider_symbols.items())


def _market_provider_secret_keys(provider: str) -> tuple[str, ...]:
    return {
        "custom": ("MARKET_DATA_API_KEY", "MARKET_DATA_BASE_URL"),
        "finnhub": ("FINNHUB_API_KEY",),
        "twelvedata": ("TWELVE_DATA_API_KEY",),
        "alphavantage": ("ALPHA_VANTAGE_API_KEY",),
    }.get(provider.lower(), ())


def _format_macro_dashboard(query: str, rows: list[MacroIndicator]) -> Table:
    table = Table(title=f"Macro Dashboard: {query.title()}", expand=True)
    table.add_column("Indicator", style="cyan", no_wrap=True)
    table.add_column("Region", no_wrap=True)
    table.add_column("Value", justify="right")
    table.add_column("Period", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for row in rows:
        table.add_row(row.name, row.region, row.value, row.period, row.source, row.note)
    if not rows:
        table.add_row("-", "-", "-", "-", "Fallback", "No macro rows matched the query.")
    table.caption = "Fallback rows are connector-ready placeholders. Use provider keys later for exact values."
    return table


def _format_macro_indicator(indicator: str, region: str, rows: list[MacroIndicator]) -> Table:
    table = Table(title=f"Macro Indicator: {indicator.replace('_', ' ').title()} | {region.upper()}", expand=True)
    table.add_column("Period", style="cyan", no_wrap=True)
    table.add_column("Indicator", no_wrap=True)
    table.add_column("Region", no_wrap=True)
    table.add_column("Value", justify="right")
    table.add_column("Source", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for row in rows:
        table.add_row(row.period, row.name, row.region, row.value, row.source, row.note)
    if not rows:
        table.add_row("-", indicator, region.upper(), "-", "Alpha Vantage", "No data returned.")
    table.caption = "Hidden macro alias. Verify releases with official sources."
    return table


def _format_trading_overview(realtime: RealtimeConnectorCatalog, brokers: BrokerCatalog, paper: PaperTradingEngine | None = None) -> Table:
    kill_active = paper.is_kill_switch_active() if paper else False
    daily_pnl = paper.daily_pnl() if paper else 0.0
    table = Table(title="Trading Layer v1.0.0 | Safe Execution Workspace", expand=True)
    table.add_column("Area", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    risk_status = "KILL SWITCH ACTIVE" if kill_active else "active"
    risk_style = "red" if kill_active else "green"
    table.add_row("Risk Guard", f"[{risk_style}]{risk_status}[/]", f"Daily PnL: ${daily_pnl:,.2f}. Use /trading risk for details.")
    table.add_row("Real-Time Trading", "configurable", f"{len(realtime.all())} realtime connector(s). Use /trading realtime or /trading stream.")
    table.add_row("Broker Integrations", "catalog", f"{len(brokers.all())} broker integration(s). Use /trading brokers.")
    table.add_row("Paper Trading", "active", "Local paper orders with risk guard. Use /trading paper buy AAPL 1 market 100.")
    table.add_row("Algo Trading", "paper-only", "3 built-in strategies. Use /trading algo list or /trading algo run sma_cross AAPL 1d.")
    table.add_row("Audit Log", "active", "All orders logged. Use /trading audit.")
    table.add_row("Live Orders", "disabled", "No live broker orders are sent by FinCLI v1.0.0.")
    table.caption = "Trading features are simulation/catalog first. Configure broker adapters only after explicit live-trading safety work."
    return table


def _format_realtime_connectors(connectors: tuple[RealtimeConnector, ...]) -> Table:
    table = Table(title="Real-Time Connector Catalog", expand=True)
    table.add_column("Connector", style="cyan", no_wrap=True)
    table.add_column("Transport", no_wrap=True)
    table.add_column("Assets", overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for connector in connectors:
        table.add_row(
            connector.name,
            connector.transport,
            ", ".join(connector.asset_classes),
            connector.status,
            connector.note,
        )
    return table


def _format_brokers(brokers: tuple[BrokerIntegration, ...]) -> Table:
    table = Table(title="Broker Integration Catalog", expand=True)
    table.add_column("Broker", style="cyan", no_wrap=True)
    table.add_column("Region", no_wrap=True)
    table.add_column("Assets", overflow="fold")
    table.add_column("Mode", no_wrap=True)
    table.add_column("Note", overflow="fold")
    for broker in brokers:
        table.add_row(
            broker.name,
            broker.region,
            ", ".join(broker.asset_classes),
            broker.mode,
            broker.note,
        )
    table.caption = "Catalog entries are not live execution adapters yet unless explicitly marked and configured."
    return table


def _format_paper_order(order: dict[str, object]) -> Table:
    table = Table(title="Paper Trading Order", expand=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")
    for key in ("side", "symbol", "quantity", "order_type", "price", "notional", "status", "strategy"):
        table.add_row(key, str(order.get(key, "-")))
    table.caption = "Paper trading only. No broker/live order was sent."
    return table


def _format_paper_orders(orders: list[dict[str, object]]) -> Table:
    table = Table(title="Paper Trading Orders", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Side", no_wrap=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Type", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Notional", justify="right")
    table.add_column("Status", no_wrap=True)
    table.add_column("Created", no_wrap=True)
    for order in orders:
        table.add_row(
            str(order.get("id", "-")),
            str(order.get("side", "-")),
            str(order.get("symbol", "-")),
            _format_optional_number(order.get("quantity")),
            str(order.get("order_type", "-")),
            _format_optional_number(order.get("price")),
            _format_optional_number(order.get("notional")),
            str(order.get("status", "-")),
            str(order.get("created_at", "-")),
        )
    if not orders:
        table.add_row("-", "-", "-", "-", "-", "-", "-", "empty", "-")
    table.caption = "Paper trading orders are stored locally in SQLite."
    return table


def _format_risk_status(paper: PaperTradingEngine) -> Table:
    table = Table(title="Trading Risk Guard", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Value")
    kill_active = paper.is_kill_switch_active()
    table.add_row("Kill Switch", "[red]ACTIVE[/]" if kill_active else "[green]inactive[/]")
    table.add_row("Daily PnL", f"${paper.daily_pnl():,.2f}")
    table.add_row("Max Position Size", f"{paper.risk_guard.max_position_pct:.0%} of equity")
    table.add_row("Daily Loss Limit", f"{paper.risk_guard.daily_loss_limit_pct:.0%} of equity")
    profile = paper.risk_guard._get_profile()
    if profile:
        table.add_row("Portfolio Equity", f"${float(profile['equity']):,.2f} {profile['currency']}")
    else:
        table.add_row("Portfolio Equity", "No profile set. Use /profile set ...")
    table.caption = "Risk guard checks run before every paper order."
    return table


def _format_audit_log(entries: list[dict[str, object]]) -> Table:
    table = Table(title="Order Audit Log", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Order ID", justify="right")
    table.add_column("Action", style="cyan", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    table.add_column("Time", no_wrap=True)
    for entry in entries:
        table.add_row(
            str(entry.get("id", "-")),
            str(entry.get("order_id", "-")),
            str(entry.get("action", "-")),
            str(entry.get("detail", "")),
            str(entry.get("created_at", "-")),
        )
    if not entries:
        table.add_row("-", "-", "-", "No audit entries.", "-")
    table.caption = "Audit log is immutable. Entries are never updated or deleted."
    return table


def _format_positions(positions: list[dict[str, object]]) -> Table:
    table = Table(title="Paper Trading Positions", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Net Qty", justify="right")
    table.add_column("Avg Price", justify="right")
    table.add_column("Buy Notional", justify="right")
    table.add_column("Sell Notional", justify="right")
    table.add_column("Realized PnL", justify="right")
    table.add_column("Orders", justify="right")
    for pos in positions:
        table.add_row(
            str(pos.get("symbol", "-")),
            _format_optional_number(pos.get("net_quantity")),
            _format_optional_number(pos.get("avg_price")),
            _format_optional_number(pos.get("buy_notional")),
            _format_optional_number(pos.get("sell_notional")),
            _format_optional_number(pos.get("realized_pnl")),
            str(pos.get("order_count", "-")),
        )
    if not positions:
        table.add_row("-", "-", "-", "-", "-", "-", "No positions. Use /trading paper buy ...")
    return table


def _format_broker_status(catalog: BrokerCatalog) -> Table:
    table = Table(title="Broker Adapter Status", expand=True)
    table.add_column("Broker", style="cyan", no_wrap=True)
    table.add_column("Mode", no_wrap=True)
    table.add_column("Status")
    for broker in catalog.all():
        status = "ready" if broker.mode in {"paper_ready", "sandbox_ready"} else "stub" if broker.mode == "adapter_stub" else "requires gateway"
        table.add_row(broker.name, broker.mode, status)
    table.caption = "Use /trading broker use <name> to activate a broker adapter."
    return table


def _format_stream_status(connectors: tuple[RealtimeConnector, ...]) -> Table:
    table = Table(title="Realtime Stream Status", expand=True)
    table.add_column("Connector", style="cyan", no_wrap=True)
    table.add_column("Transport", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Assets", overflow="fold")
    for connector in connectors:
        table.add_row(connector.name, connector.transport, connector.status, ", ".join(connector.asset_classes))
    table.caption = "Use /trading stream <connector> to view connection config."
    return table


def _format_algo_strategies(strategies: tuple[StrategyInfo, ...]) -> Table:
    table = Table(title="Algo Trading Strategies", expand=True)
    table.add_column("Strategy", style="cyan", no_wrap=True)
    table.add_column("Description", overflow="fold")
    table.add_column("Asset Classes", overflow="fold")
    for strategy in strategies:
        table.add_row(strategy.name, strategy.description, ", ".join(strategy.asset_classes))
    table.caption = "Use /trading algo run <strategy> <symbol> [timeframe] [qty] to execute."
    return table


def _format_algo_result(result: object, order: dict[str, object] | None = None) -> Table:
    table = Table(title="Algo Strategy Result", expand=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value")
    table.add_row("Strategy", str(getattr(result, "strategy", "-")))
    table.add_row("Symbol", str(getattr(result, "symbol", "-")))
    table.add_row("Signal", str(getattr(result, "signal", "-")))
    table.add_row("Confidence", str(getattr(result, "confidence", "-")))
    table.add_row("Reason", str(getattr(result, "reason", "-")))
    if order:
        table.add_row("Order Status", str(order.get("status", "-")))
        table.add_row("Order ID", str(order.get("id", "-")))
    elif getattr(result, "signal", "") in {"buy", "sell"}:
        table.add_row("Order", "Not placed (risk guard blocked or error)")
    table.caption = "Algo signals are informational. Paper orders respect the risk guard."
    return table


def _macro_error_row(indicator: str, region: str, exc: FinCLIError) -> MacroIndicator:
    label = indicator.replace("_", " ").title()
    help_text = f" {exc.help_text}" if getattr(exc, "help_text", None) else ""
    return MacroIndicator(
        name=label,
        region=region.upper(),
        value="unavailable",
        period=date.today().isoformat(),
        source="Alpha Vantage",
        note=f"{exc}{help_text}",
    )


def _format_insider_transactions(symbol: str, rows: list[dict[str, object]]) -> Table:
    table = Table(title=f"Finnhub Insider Transactions: {symbol}", expand=True)
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Code", no_wrap=True)
    table.add_column("Change", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Price", justify="right")
    for row in rows:
        table.add_row(
            str(row.get("date") or "-"),
            str(row.get("name") or "-"),
            str(row.get("transaction_code") or "-"),
            _format_optional_number(row.get("change")),
            _format_optional_number(row.get("shares")),
            _format_optional_number(row.get("transaction_price")),
        )
    if not rows:
        table.add_row("-", "No insider transactions returned.", "-", "-", "-", "-")
    table.caption = "Finnhub endpoint availability depends on API key, plan, and symbol coverage."
    return table


def _format_ipo_calendar(rows: list[dict[str, object]], start: date, end: date) -> Table:
    table = Table(title=f"Finnhub IPO Calendar | {start.isoformat()} to {end.isoformat()}", expand=True)
    table.add_column("Date", style="cyan", no_wrap=True)
    table.add_column("Symbol", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Exchange", no_wrap=True)
    table.add_column("Price", justify="right")
    table.add_column("Shares", justify="right")
    table.add_column("Status", no_wrap=True)
    for row in rows:
        table.add_row(
            str(row.get("date") or "-"),
            str(row.get("symbol") or "-"),
            str(row.get("name") or "-"),
            str(row.get("exchange") or "-"),
            str(row.get("price") or "-"),
            _format_optional_number(row.get("shares")),
            str(row.get("status") or "-"),
        )
    if not rows:
        table.add_row("-", "-", "No IPOs returned for the selected window.", "-", "-", "-", "-")
    table.caption = "Finnhub endpoint availability depends on API key, plan, and date coverage."
    return table


def _format_optional_number(value: object) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{number:,.0f}"
    return f"{number:,.2f}"


def _format_user_profile(profile: UserProfile | None) -> Table:
    table = Table(title="User Gameplay Profile", expand=True)
    table.add_column("Field", style="cyan", no_wrap=True)
    table.add_column("Value", overflow="fold")
    if profile is None:
        table.add_row("Status", "Not configured")
        table.add_row("Setup", '/profile set "Nama" <equity> <currency> <leverage> <years>')
        table.add_row("Use", "Profile is used by /analyze for SL/TP and risk-context wording.")
        return table
    table.add_row("Name", profile.name)
    table.add_row("Equity", f"{profile.equity:g} {profile.currency}")
    table.add_row("Leverage", profile.leverage)
    table.add_row("Investment Years", f"{profile.years_in_investment:g}")
    table.add_row("Gameplay", profile.gameplay)
    table.add_row("Analyze Usage", "Used by /analyze to constrain Signal, SL, TP1, TP2, TP3, and Reason.")
    return table


def _format_agents(agents: list[Agent], label: str) -> Table:
    table = Table(title=f"FinCLI Agents: {label}", expand=True)
    table.add_column("Slug", style="cyan", no_wrap=True)
    table.add_column("Name", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("Framework", overflow="fold")
    table.add_column("Role", overflow="fold")
    for agent in agents:
        table.add_row(agent.slug, agent.name, agent.category, agent.framework, agent.role)
    if not agents:
        table.add_row("-", "-", "-", "-", "No agents matched.")
    return table


def _format_agent(agent: Agent) -> Panel:
    return Panel(
        "\n".join(
            [
                f"Name      : {agent.name}",
                f"Slug      : {agent.slug}",
                f"Category  : {agent.category}",
                f"Framework : {agent.framework}",
                f"Role      : {agent.role}",
                "",
                "Usage     : use as a thinking lens for /research and future multi-agent analysis.",
            ]
        ),
        title="FinCLI Agent",
        border_style="cyan",
    )


def _format_connectors(connectors: list[Connector], label: str) -> Table:
    table = Table(title=f"Connector Catalog: {label}", expand=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("Access", no_wrap=True)
    table.add_column("Coverage", overflow="fold")
    for connector in connectors:
        table.add_row(connector.name, connector.category, connector.access, connector.coverage)
    if not connectors:
        table.add_row("-", "-", "-", "No connectors matched.")
    table.caption = "Catalog entries are roadmap-ready; active adapters depend on implementation and entitlement."
    return table


def _format_news_connectors(connectors: list[NewsConnectorSpec], label: str) -> Table:
    table = Table(title=f"News Connector Catalog: {label}", expand=True)
    table.add_column("Slug", style="cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Access", no_wrap=True)
    table.add_column("Category", no_wrap=True)
    table.add_column("API Key", no_wrap=True)
    table.add_column("Status", overflow="fold")
    for connector in connectors:
        status = "active rss" if connector.access == "public-rss" else "api-key ready"
        if connector.slug == "custom_news":
            status = "custom endpoint"
        table.add_row(
            connector.slug,
            connector.name,
            connector.access,
            connector.category,
            connector.env_key or "-",
            status,
        )
    if not connectors:
        table.add_row("-", "No news connectors matched.", "-", "-", "-", "-")
    table.caption = (
        "Use /news_model use <slug> for primary, /news_model priority a,b,c for fallback order, "
        "and /news_model key <slug> <api_key> for API-key providers."
    )
    return table


def _format_plugins(plugins: list[PluginManifest], status_only: bool = False) -> Table:
    table = Table(title="FinCLI Plugins" if not status_only else "FinCLI Plugin Status", expand=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Version", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Capabilities", overflow="fold")
    table.add_column("Commands", overflow="fold")
    if not status_only:
        table.add_column("Description", overflow="fold")
    for plugin in plugins:
        row = [
            plugin.name,
            plugin.version,
            plugin.status,
            ", ".join(plugin.capabilities) or "-",
            ", ".join(plugin.commands) or "-",
        ]
        if not status_only:
            row.append(plugin.description or "-")
        table.add_row(*row)
    if not plugins:
        empty = ["-", "-", "no plugins", "-", "-"]
        if not status_only:
            empty.append("Create ~/.fincli/plugins/<name>/plugin.json to register a local plugin.")
        table.add_row(*empty)
    table.caption = "Plugins are manifest-only in v0.4.0; FinCLI does not execute plugin code yet."
    return table


def _format_transactions(rows: list[dict[str, object]]) -> Table:
    table = Table(title="Transaction Ledger", expand=True)
    table.add_column("ID", justify="right")
    table.add_column("Action")
    table.add_column("Symbol", style="cyan")
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Realized PnL", justify="right")
    table.add_column("Created")
    for row in rows:
        table.add_row(
            str(row["id"]),
            str(row["action"]),
            str(row["symbol"]),
            _fmt(float(row["quantity"])),
            _fmt(float(row["price"])),
            _fmt(float(row["realized_pnl"])),
            str(row["created_at"]),
        )
    if not rows:
        table.add_row("-", "-", "-", "-", "-", "-", "Belum ada transaksi. Gunakan /tx add buy AAPL 10 100")
    return table


def _format_journal_stats(stats: JournalStats) -> Table:
    table = Table(title="Journal Stats", expand=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Total Entries", str(stats.total_entries))
    table.add_row("Wins", str(stats.wins))
    table.add_row("Losses", str(stats.losses))
    table.add_row("Win Rate", _fmt(stats.win_rate))
    table.add_row("Top Instrument", stats.top_instrument)
    table.add_row("Top Emotion", stats.top_emotion)
    table.add_row("Top Tags", ", ".join(stats.top_tags) if stats.top_tags else "N/A")
    return table


def _format_news(symbol: str, items: list[NewsItem]) -> str:
    if not items:
        return f"News: {symbol}\nBelum ada news dari provider aktif."
    lines = [f"News: {symbol}"]
    for index, item in enumerate(items, start=1):
        published = item.published_at.isoformat(timespec="seconds") if item.published_at else "unknown time"
        url = f"\n   URL: {item.url}" if item.url else ""
        summary = f"\n   Summary: {item.summary}" if item.summary else ""
        lines.append(f"{index}. {item.title}\n   Source: {item.source} | Published: {published}{summary}{url}")
    return "\n".join(lines)


def _format_news_desk(desk: NewsDesk) -> Table:
    table = Table(title=f"News Desk: {desk.symbol}", expand=True)
    table.add_column("Time", style="dim", no_wrap=True)
    table.add_column("Source", style="cyan", no_wrap=True)
    table.add_column("Headline", style="white", overflow="fold")
    table.add_column("Summary", overflow="fold")
    table.add_column("Analysis", overflow="fold")
    for item in desk.items:
        published = item.published_at.isoformat(timespec="minutes") if item.published_at else "unknown"
        table.add_row(published, item.source, item.title, item.summary or "-", _news_item_analysis(item))
    if not desk.items:
        table.add_row("-", "-", "No news from active providers.", desk.note, "-")
    lookback = f" | Lookback: {desk.lookback_days}d" if desk.lookback_days else ""
    quality = _news_data_quality(desk)
    errors = f" | Errors: {len(desk.errors)}" if desk.errors else ""
    table.caption = (
        f"Providers: {', '.join(desk.provider_chain)}{lookback} | "
        f"Reliability: {desk.reliability_status}{errors} | Data Quality: {quality.compact()} | {desk.note}"
    )
    return table


def _news_item_analysis(item: NewsItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    bullish_words = ("beat", "beats", "rise", "rises", "rally", "rallies", "higher", "growth", "upgrade", "bullish", "record")
    bearish_words = ("miss", "falls", "falling", "lower", "sink", "sinks", "down", "cut", "downgrade", "bearish", "weak")
    caution_words = ("risk", "uncertain", "probe", "lawsuit", "volatility", "warning", "recall", "delay")
    bullish = sum(1 for word in bullish_words if word in text)
    bearish = sum(1 for word in bearish_words if word in text)
    caution = sum(1 for word in caution_words if word in text)
    if caution and caution >= max(bullish, bearish):
        bias = "caution"
    elif bullish > bearish:
        bias = "bullish"
    elif bearish > bullish:
        bias = "bearish"
    else:
        bias = "neutral"
    if item.published_at is None:
        freshness = "date unknown"
    else:
        freshness = "fresh" if _news_age_days(item) <= 3 else "older context"
    return semantic_text(f"{bias} | {freshness} | verify source before trading")


def _news_age_days(item: NewsItem) -> int:
    if item.published_at is None:
        return 999
    published = item.published_at
    if published.tzinfo is None:
        from datetime import timezone

        published = published.replace(tzinfo=timezone.utc)
    from datetime import datetime, timezone

    return max((datetime.now(timezone.utc) - published).days, 0)


def _news_data_quality(desk: NewsDesk) -> DataQualityReport:
    item_count = len(desk.items)
    score = 20
    if item_count >= 8:
        score = 85
    elif item_count >= 3:
        score = 70
    elif item_count >= 1:
        score = 55
    if desk.errors:
        score = max(20, score - min(30, len(desk.errors) * 10))
    missing = () if item_count else ("news",)
    tier = "strong" if score >= 85 else "usable" if score >= 65 else "partial" if score >= 40 else "weak"
    return DataQualityReport(
        score=score,
        quote="not_applicable",
        ohlcv="not_applicable",
        news=f"{item_count} item(s)",
        fundamentals="not_applicable",
        provider=", ".join(desk.provider_chain) or "unknown",
        tier=tier,
        freshness=f"{desk.lookback_days or 'latest'}d",
        reliability_status=desk.reliability_status,
        missing_fields=missing,
        label=f"{tier} | {desk.reliability_status}",
    )


def _format_web_results(query: str, results: list[WebSearchResult]) -> Table:
    table = Table(title=f"Web Research: {query}", expand=True)
    table.add_column("#", justify="right", width=3)
    table.add_column("Title", style="cyan", overflow="fold")
    table.add_column("Snippet / Extract", overflow="fold")
    table.add_column("URL", style="dim", overflow="fold")
    for index, result in enumerate(results, start=1):
        extract = result.content[:500] if result.content else result.snippet
        table.add_row(str(index), result.title, extract or "-", result.url)
    if not results:
        table.add_row("-", "No results", "Search providers returned no public context.", "-")
    table.caption = "Web context is public web data; verify source quality before using it for financial decisions."
    return table


def _format_fundamentals(snapshot: FundamentalSnapshot) -> str:
    return (
        f"Fundamental Snapshot: {snapshot.symbol}\n"
        f"Provider: {snapshot.provider}\n"
        f"Currency: {snapshot.currency}\n"
        f"Market Cap: {_fmt(snapshot.market_cap)}\n"
        f"P/E Ratio: {_fmt(snapshot.pe_ratio)}\n"
        f"EPS: {_fmt(snapshot.eps)}\n"
        f"Revenue: {_fmt(snapshot.revenue)}\n"
        f"Beta: {_fmt(snapshot.beta)}\n"
        f"Sector: {snapshot.sector or 'N/A'}\n"
        f"Industry: {snapshot.industry or 'N/A'}"
    )


def _format_yahoo_table(dataset: YahooTable) -> Table:
    table = Table(title=f"Yahoo Finance {dataset.section}: {dataset.symbol}", expand=True)
    for index, column in enumerate(dataset.columns):
        table.add_column(str(column), style="cyan" if index == 0 else "white", overflow="fold")

    for row in dataset.rows:
        normalized = [str(value) for value in row[: len(dataset.columns)]]
        normalized += [""] * max(0, len(dataset.columns) - len(normalized))
        table.add_row(*normalized)

    if not dataset.rows:
        table.add_row(*(["No data returned by yfinance/Yahoo."] + [""] * (len(dataset.columns) - 1)))

    note = dataset.note or "Data source: yfinance/Yahoo Finance. Realtime/delayed status depends on exchange coverage."
    table.caption = f"{note}\nSource: {dataset.source_url}"
    return table


def _format_news_context(items: list[NewsItem]) -> str:
    if not items:
        return "News: no recent news from active provider."
    lines = ["News:"]
    for item in items:
        published = item.published_at.isoformat(timespec="seconds") if item.published_at else "unknown time"
        summary = f" - {item.summary}" if item.summary else ""
        lines.append(f"- {item.title} ({item.source}, {published}){summary}")
    return "\n".join(lines)


def _format_fundamental_context(snapshot: FundamentalSnapshot) -> str:
    return (
        "Fundamentals:\n"
        f"- Symbol: {snapshot.symbol}\n"
        f"- Currency: {snapshot.currency}\n"
        f"- Market Cap: {_fmt(snapshot.market_cap)}\n"
        f"- P/E Ratio: {_fmt(snapshot.pe_ratio)}\n"
        f"- EPS: {_fmt(snapshot.eps)}\n"
        f"- Revenue: {_fmt(snapshot.revenue)}\n"
        f"- Beta: {_fmt(snapshot.beta)}\n"
        f"- Sector: {snapshot.sector or 'N/A'}\n"
        f"- Industry: {snapshot.industry or 'N/A'}"
    )


def _format_ai_response(response: AIResponse) -> AIResponseView:
    return AIResponseView(response)


def _fmt(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.4f}"


def _split_command(raw: str) -> list[str]:
    parts = shlex.split(raw, posix=os.name != "nt")
    if os.name == "nt":
        return [_strip_wrapping_quotes(part) for part in parts]
    return parts


def _doctor_live_symbol(args: list[str]) -> str:
    lowered = [arg.lower() for arg in args]
    if "--live" not in lowered:
        return "AAPL"
    index = lowered.index("--live")
    if len(args) > index + 1 and not args[index + 1].startswith("--"):
        return args[index + 1].upper()
    return "AAPL"


def _router_roots() -> set[str]:
    """Return slash command roots directly handled by CommandRouter."""

    return {
        "/agent",
        "/ai",
        "/ai_model",
        "/alert",
        "/analyze",
        "/backtest",
        "/cache",
        "/calendar",
        "/clear",
        "/config",
        "/connector",
        "/dashboard",
        "/doctor",
        "/exit",
        "/export",
        "/funda",
        "/help",
        "/history",
        "/journal",
        "/macro",
        "/market",
        "/mtf",
        "/news",
        "/news_model",
        "/plugin",
        "/portfolio",
        "/privacy",
        "/profile",
        "/provider",
        "/quote",
        "/report",
        "/research",
        "/scan",
        "/secrets",
        "/security",
        "/setup",
        "/structure",
        "/symbol",
        "/technical",
        "/trading",
        "/tutorial",
        "/tx",
        "/watchlist",
        "/web",
        "/yahoo",
    }


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


# ---------------------------------------------------------------------------
# Tutorial helpers
# ---------------------------------------------------------------------------

TUTORIAL_LESSONS = {
    1: {
        "title": "Welcome & Setup",
        "subtitle": "Get started with FinCLI",
        "steps": [
            ("Set your profile", '/profile set "Your Name" 10000 USD 1:1 2', "Your profile helps FinCLI personalize risk calculations."),
            ("Check system health", "/doctor", "See if everything is configured correctly."),
            ("View setup guide", "/setup", "See recommended setup steps."),
        ],
        "tip": "You can skip API keys for now — FinCLI works with free providers like yfinance!",
    },
    2: {
        "title": "Market Data",
        "subtitle": "Quotes, overviews, and news",
        "steps": [
            ("Get a quick quote", "/quote AAPL", "Get the latest price for any symbol."),
            ("Full market overview", "/market AAPL 1d", "See technicals, structure, and data quality."),
            ("Read latest news", "/news AAPL", "Get news from multiple sources."),
            ("Deep research", "/research AAPL --deep", "AI-powered research with cited sources."),
        ],
        "tip": "Use any symbol — stocks (AAPL), crypto (BTC-USD), forex (EURUSD=X), commodities (XAUUSD).",
    },
    3: {
        "title": "Technical Analysis",
        "subtitle": "Indicators, structure, and signals",
        "steps": [
            ("Technical analysis", "/technical AAPL 1d", "RSI, MACD, Bollinger, support/resistance."),
            ("Multi-timeframe", "/mtf AAPL 1d,1h,15m", "Check alignment across timeframes."),
            ("AI analysis", "/analyze AAPL 1d", "AI interprets the technicals for you."),
            ("Market structure", "/structure AAPL 1d", "BOS, CHoCH, liquidity zones."),
        ],
        "tip": "Technical analysis is educational, not financial advice. Always use confirmation.",
    },
    4: {
        "title": "Portfolio Management",
        "subtitle": "Track positions and risk",
        "steps": [
            ("Add a position", "/portfolio add AAPL 10 150", "Add 10 shares of AAPL at $150."),
            ("View portfolio", "/portfolio", "See all positions with PnL."),
            ("Check risk", "/portfolio risk", "Exposure, concentration, health score."),
            ("Save snapshot", "/portfolio snapshot", "Track portfolio value over time."),
            ("Benchmark", "/portfolio benchmark SPY", "Compare vs S&P 500."),
        ],
        "tip": "Use /portfolio whatif to test changes before committing!",
    },
    5: {
        "title": "Paper Trading",
        "subtitle": "Practice without risk",
        "steps": [
            ("Place a paper order", "/trading paper buy AAPL 1 market 150", "Simulate buying 1 share."),
            ("View positions", "/trading positions", "See aggregated paper positions."),
            ("Check risk guard", "/trading risk", "See daily PnL and limits."),
            ("Run algo strategy", "/trading algo run sma_cross AAPL 1d", "Let a strategy trade for you."),
        ],
        "tip": "Paper trading uses risk guards to protect you. Use /trading kill to stop all orders.",
    },
    6: {
        "title": "Alerts & Monitoring",
        "subtitle": "Stay informed automatically",
        "steps": [
            ("Add price alert", "/alert add AAPL above 200", "Get notified when price hits $200."),
            ("Add to watchlist", "/watchlist add AAPL", "Track symbols in your watchlist."),
            ("Scan watchlist", "/scan watchlist rsi<30", "Find oversold stocks."),
            ("Start alert daemon", "/alert daemon start", "Background alert checking."),
        ],
        "tip": "You can set conditional alerts too: rsi_below, volume_above, macd_cross_up.",
    },
    7: {
        "title": "Export & Reports",
        "subtitle": "Save and share your research",
        "steps": [
            ("Export research", "/research AAPL --report --export md report.md", "Save research as Markdown."),
            ("Run backtest", "/backtest AAPL sma_cross 1d", "Test a strategy on historical data."),
            ("Export everything", "/export all json ./exports", "Batch export all your data."),
            ("View history", "/history", "See all commands you've run."),
        ],
        "tip": "Use /backtest --monte-carlo to test strategy robustness!",
    },
}


def _format_tutorial_menu() -> Table:
    table = Table(title="🎓 FinCLI Tutorial — Interactive Guide", expand=True)
    table.add_column("#", style="cyan", justify="center", width=3)
    table.add_column("Lesson", style="cyan", no_wrap=True)
    table.add_column("Description")
    table.add_column("Command", style="green")
    for num, lesson in TUTORIAL_LESSONS.items():
        table.add_row(str(num), lesson["title"], lesson["subtitle"], f"/tutorial {num}")
    table.caption = "Type /tutorial <number> to start a lesson. Use /tutorial next to go through them in order."
    return table


def _tutorial_lesson(num: int) -> Panel:
    lesson = TUTORIAL_LESSONS.get(num)
    if lesson is None:
        return Panel("Lesson not found. Use /tutorial to see available lessons.", title="Tutorial", border_style="red")

    lines = [
        f"[bold cyan]🎓 Tutorial: {lesson['title']} ({num}/7)[/bold cyan]",
        "",
        f"[dim]{lesson['subtitle']}[/dim]",
        "",
        "[bold]What you'll learn:[/bold]",
    ]
    for i, (step_title, cmd, explanation) in enumerate(lesson["steps"], 1):
        lines.append(f"  {i}. [bold]{step_title}[/bold]")
        lines.append(f"     [green]{cmd}[/green]")
        lines.append(f"     [dim]{explanation}[/dim]")
        lines.append("")

    lines.append(f"[bold yellow]💡 Tip:[/bold yellow] {lesson['tip']}")
    lines.append("")
    lines.append("[dim]Type /tutorial next for the next lesson, or /tutorial to see all lessons.[/dim]")

    return Panel("\n".join(lines), title=f"Tutorial: {lesson['title']}", border_style="cyan")


def _tutorial_next(router: object) -> Panel:
    if not hasattr(router, "_tutorial_progress"):
        router._tutorial_progress = 0
    router._tutorial_progress += 1
    if router._tutorial_progress > 7:
        router._tutorial_progress = 1
    return _tutorial_lesson(router._tutorial_progress)


class UnavailableAIProvider:
    """Default AI provider used until a concrete API client is configured."""

    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    async def complete(self, request: AIRequest) -> AIResponse:
        raise CommandError(
            f"AI provider {self.name} belum siap dipakai.",
            "Gunakan /ai_model untuk memilih provider dan /ai_model key <provider> <api_key> untuk menyimpan API key.",
        )
