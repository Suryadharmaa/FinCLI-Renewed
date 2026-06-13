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
from fincli.app.modules.scanner import ScanResult, scan_symbols
from fincli.app.modules.session_history import SessionHistoryService
from fincli.app.modules.transactions import TransactionService
from fincli.app.modules.user_profile import UserProfile, UserProfileService
from fincli.app.modules.watchlist import WatchlistService
from fincli.app.connectors.catalog import Connector, ConnectorCatalog
from fincli.app.connectors.news_connectors import (
    NewsConnectorCatalog,
    NewsConnectorManager,
    NewsConnectorSpec,
    news_connector_secret_key,
)
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
from fincli.app.providers.market.symbols import provider_symbol_matrix, search_symbol_catalog
from fincli.app.providers.market.yfinance_provider import YahooTable, YFinanceProvider
from fincli.app.plugins.loader import PluginLoader, PluginManifest
from fincli.app.services.market_data import MarketDataService
from fincli.app.services.market_overview import MarketOverview, build_market_overview
from fincli.app.services.macro_data import MacroDataService, MacroIndicator
from fincli.app.services.news_aggregator import NewsAggregator, NewsDesk
from fincli.app.services.web_research import (
    WebResearchService,
    WebSearchResult,
    build_web_research_context,
    should_use_web_research,
)
from fincli.app.research import ResearchEngine, format_research_brief
from fincli.app.storage.cache import TTLCache
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.market_cache import MarketCache
from fincli.app.storage.secrets import save_secret
from fincli.app.utils.errors import CommandError, FinCLIError
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
        self.market_manager = MarketProviderManager()
        self.market_service = self._build_market_service(market_provider)
        self.market_provider = self.market_service.primary_provider
        self.ai_provider = ai_provider or AIProviderManager().create(self.config.settings.ai_provider)
        self.watchlist = WatchlistService(self.db)
        self.portfolio = PortfolioService(self.db)
        self.alerts = AlertService(self.db)
        self.transactions = TransactionService(self.db, self.portfolio)
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

    def route(self, raw: str) -> CommandResult:
        result = self._route(raw)
        self._record_history(raw, result)
        return result

    def _route(self, raw: str) -> CommandResult:
        raw = raw.strip()
        if not raw:
            return CommandResult(Panel("Ketik /help untuk melihat command.", title="FinCLI"))
        if not raw.startswith("/"):
            return CommandResult(Panel("Command harus diawali slash. Contoh: /help", title="Invalid Input"))

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
            if root == "/profile":
                return self._profile(args)
            if root == "/doctor":
                return self._doctor(args)
            if root == "/setup":
                return self._setup(args)
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
        table = Table(title="FinCLI v0.2.2 Commands", expand=True)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Group", style="magenta")
        table.add_column("Fungsi", style="white")
        table.add_column("Contoh", style="green")
        for command in self.registry.all():
            table.add_row(command.name, command.group, command.description, command.example)
        return table

    def _record_history(self, raw: str, result: CommandResult) -> None:
        normalized = raw.strip().lower()
        if not normalized or normalized.startswith("/history"):
            return
        try:
            preview = _render_history_preview(result.renderable)
            self.history.record_event(self.session_id, raw, result.status, preview)
        except FinCLIError:
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
        if args and args[0].lower() == "key" and len(args) >= 2 and args[1].lower() == "status":
            return CommandResult(_format_provider_key_status(self.market_manager))
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
            "Format: /provider status, /provider list, /provider entitlement, /provider key status, /provider use <provider>, "
            "/provider priority finnhub,yfinance, atau /provider test [provider] <symbol>"
        )

    def _symbol(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /symbol <query> atau /symbol normalize <symbol>")
        action = args[0].lower()
        if action in {"normalize", "norm"}:
            if len(args) < 2:
                raise CommandError("Format: /symbol normalize <symbol>")
            return CommandResult(_format_symbol_matrix(args[1]))
        query = " ".join(args)
        results = search_symbol_catalog(query)
        return CommandResult(_format_symbol_search(query, results))

    def _research(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /research <symbol> [--quick|--deep] [timeframe]")
        symbol = args[0].upper()
        mode = "deep" if any(arg.lower() == "--deep" for arg in args[1:]) else "quick"
        timeframe = next((arg for arg in args[1:] if not arg.startswith("--")), "1d")
        engine = ResearchEngine(self.market_service, self.ai_provider, self.config.settings.ai_model)
        brief = self._run_async(engine.build(symbol, timeframe=timeframe, mode=mode))
        return CommandResult(format_research_brief(brief))

    def _macro(self, args: list[str]) -> CommandResult:
        query = " ".join(args).strip()
        rows = self.macro_data.indicators(query)
        return CommandResult(_format_macro_dashboard(query or "global", rows))

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
        table = Table(title="FinCLI Doctor", expand=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status")
        table.add_column("Detail", overflow="fold")
        table.add_row("Version", "ok", "FinCLI v0.2.2 command surface loaded.")
        table.add_row("Database", "ok", str(self.db.db_file))
        table.add_row("Market Provider", "ok", ", ".join(provider.name for provider in self.market_service.providers))
        profile = self.user_profiles.get()
        table.add_row("Profile", "ok" if profile else "missing", profile.gameplay if profile else "Run /profile set ...")
        table.add_row("AI Provider", "configured", f"{self.config.settings.ai_provider} / {self.config.settings.ai_model}")
        table.caption = "Doctor checks local wiring only; provider entitlement still depends on your API key/account."
        return CommandResult(table)

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
        if action == "performance":
            return CommandResult(self._portfolio_performance_table())
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
            "Format: /portfolio, /portfolio performance, /portfolio add <symbol> <qty> <avg_price>, "
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
                raise CommandError("Format: /alert add <symbol> <above|below|>|< > <price> [note]")
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
            return CommandResult(_format_alert_checks(checked))
        raise CommandError("Format: /alert, /alert add <symbol> <above|below> <price>, /alert remove <id>, /alert check")

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
            raise CommandError("Format: /backtest <symbol> [sma_cross|rsi_reversion] [interval]")
        symbol = args[0].upper()
        strategy = args[1].lower() if len(args) >= 2 else "sma_cross"
        interval = args[2].lower() if len(args) >= 3 else "1d"
        candles = self._run_async(self.market_service.history(symbol, period="2y", interval=interval))
        result = run_backtest(symbol, candles, strategy=strategy, interval=interval)
        return CommandResult(_format_backtest(result))

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
        prompt = build_market_analysis_prompt(symbol, timeframe, candles, technical, structure, news_context, gameplay_context)
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
        positions = self.portfolio.list()
        realized = self.transactions.realized_pnl_total()
        cost_basis = 0.0
        market_value = 0.0
        unrealized = 0.0
        for row in positions:
            quantity = float(row["quantity"])
            average_price = float(row["average_price"])
            current_price, pnl, _ = self._portfolio_market_values(row)
            cost_basis += quantity * average_price
            if current_price is not None:
                market_value += quantity * current_price
            if pnl is not None:
                unrealized += pnl

        table = Table(title="Portfolio Performance", expand=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Cost Basis", _fmt(cost_basis))
        table.add_row("Market Value", _fmt(market_value))
        table.add_row("Unrealized PnL", _fmt(unrealized))
        table.add_row("Realized PnL", _fmt(realized))
        table.add_row("Total PnL", _fmt(realized + unrealized))
        return table

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
            return (
                f"Provider health: {status.status}\n"
                f"Provider realtime: {status.realtime}\n"
                f"Provider message: {status.message}"
            )
        except (FinCLIError, AttributeError) as exc:
            return f"Provider health: unavailable ({exc})"

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
        if len(args) < 3 or args[0].lower() not in {"journal", "portfolio"}:
            raise CommandError("Format: /export <journal|portfolio> <csv|json> <path>")
        dataset = args[0].lower()
        export_format = args[1].lower()
        target = args[2]
        rows = self.journal.list(limit=10_000) if dataset == "journal" else self.portfolio.list()
        written = export_rows(rows, export_format, target)
        return CommandResult(Panel(f"Export {dataset} selesai: {written}", title="Export", border_style="green"))

    def _build_market_service(self, injected_provider: BaseMarketProvider | None = None) -> MarketDataService:
        if injected_provider is not None:
            return MarketDataService(
                [injected_provider],
                cache=self.market_cache,
                cache_ttl_seconds=self.config.settings.cache_ttl_seconds,
            )
        priority = self.config.settings.market_provider_priority or [self.config.settings.market_provider]
        return MarketDataService(
            self.market_manager.create_many(priority),
            cache=self.market_cache,
            cache_ttl_seconds=self.config.settings.cache_ttl_seconds,
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
        f"{quality.score}/100",
        f"quote={quality.quote}; ohlcv={quality.ohlcv}; news={quality.news}; fundamentals={quality.fundamentals}; provider={quality.provider}",
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
    table.add_row("Candles", str(result.candles))
    table.add_row("Trades", str(len(result.trades)))
    table.add_row("Total Return", semantic_text(f"{result.total_return_percent:.2f}% {'gain' if result.total_return_percent >= 0 else 'loss'}"))
    table.add_row("Win Rate", f"{result.win_rate:.2f}%")
    table.add_row("Max Drawdown", semantic_text(f"{result.max_drawdown_percent:.2f}% drawdown"))
    table.add_row("Exposure", f"{result.exposure_percent:.2f}%")
    if result.trades:
        latest = result.trades[-1]
        table.add_row(
            "Latest Trade",
            (
                f"entry={latest.entry_price:.4f}; exit={latest.exit_price:.4f}; "
                f"pnl={latest.pnl_percent:.2f}%; reason={latest.reason}"
            ),
        )
    table.add_row("Notes", " ".join(result.notes))
    table.caption = "Educational backtest only. Fees, slippage, spreads, liquidity, and execution risk are not modeled."
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
    table = Table(title=f"Economic Calendar | {start.isoformat()} to {end.isoformat()} | {source}", expand=True)
    table.add_column("Time", style="cyan", no_wrap=True, width=16, max_width=16)
    table.add_column("Country", no_wrap=True, width=7, max_width=7)
    table.add_column("Impact", no_wrap=True, width=6, max_width=6)
    table.add_column("Event", style="white", overflow="fold")

    for event in events:
        event_time = event.time.isoformat(timespec="minutes") if event.time else "TBA"
        table.add_row(
            event_time,
            event.country,
            event.impact,
            event.event,
        )

    if not events:
        table.add_row("-", "-", "-", "Tidak ada event yang cocok dengan filter.")
    summary = calendar_summary(events)
    table.add_row(
        "Summary",
        source,
        "-",
        f"total={summary['total']}; high={summary.get('high', 0)}; medium={summary.get('medium', 0)}; low={summary.get('low', 0)}",
    )
    table.add_row("Note", source, "-", note)
    return table


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


def _format_provider_key_status(manager: MarketProviderManager) -> Table:
    table = Table(title="Market Provider API Key Status", expand=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Source")
    for row in manager.key_status():
        table.add_row(row["provider"], row["key"], row["status"], row["source"])
    return table


def _format_provider_metrics(service: MarketDataService) -> Table:
    table = Table(title="Provider Metrics", expand=True)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", overflow="fold")
    table.add_row("Active Provider", service.primary_provider.name)
    table.add_row("Provider Chain", ", ".join(provider.name for provider in service.providers))
    table.add_row("Last Errors", "\n".join(service.last_errors) if service.last_errors else "none")
    table.add_row("Runtime Label", "realtime/delayed depends on provider entitlement and API plan")
    table.caption = "Use /provider entitlement for static capability labels and /provider test <symbol> for live checks."
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
        table.add_row("-", "No local symbol match.", "-", "-", "-", "-", "Try /symbol normalize <symbol>.")
    table.caption = "Use /symbol normalize <symbol> to inspect provider-specific normalization for any symbol."
    return table


def _format_symbol_matrix(symbol: str) -> Table:
    matrix = provider_symbol_matrix(symbol)
    table = Table(title=f"Provider Symbol Normalization: {symbol}", expand=True)
    table.add_column("Provider", style="cyan", no_wrap=True)
    table.add_column("Normalized Symbol", style="white")
    table.add_column("Asset Class", no_wrap=True)
    table.add_column("Original", style="dim")
    for provider, resolved in matrix.items():
        table.add_row(provider, resolved.symbol, resolved.asset_class, resolved.original)
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
    table.caption = "Plugins are manifest-only in v0.2.2; FinCLI does not execute plugin code yet."
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
    table.caption = f"Providers: {', '.join(desk.provider_chain)}{lookback} | {desk.note}"
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


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


class UnavailableAIProvider:
    """Default AI provider used until a concrete API client is configured."""

    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    async def complete(self, request: AIRequest) -> AIResponse:
        raise CommandError(
            f"AI provider {self.name} belum siap dipakai.",
            "Gunakan /ai_model untuk memilih provider dan /ai_model key <provider> <api_key> untuk menyimpan API key.",
        )
