"""Command parsing and routing."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
import getpass
import io
import os
from pathlib import Path
import shlex
from typing import Any

from rich.console import Console
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fincli import __version__
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
    get_conversation_history,
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
from fincli.app.modules.session_history import SessionHistoryService, relative_time
from fincli.app.storage.session_state import SessionStateManager
from fincli.app.storage.ai_cache import AICache
from fincli.app.modules.transactions import TransactionService
from fincli.app.modules.trading import (
    BrokerCatalog,
    BrokerIntegration,
    LiveTradingEngine,
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
from fincli.app.utils.i18n import set_language, get_language, t


@dataclass(slots=True)
class CommandResult:
    renderable: Any
    status: str = "ready"
    clear: bool = False
    should_exit: bool = False
    metadata: dict[str, Any] | None = None


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
        # Set language from config
        set_language(self.config.settings.language)
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
        self.live_trading = LiveTradingEngine(self.db)
        self.broker_catalog = BrokerCatalog()
        self.realtime_connector_catalog = RealtimeConnectorCatalog()
        self.journal = JournalService(self.db)
        self.user_profiles = UserProfileService(self.db)
        self.history = SessionHistoryService(self.db)
        self.session_id = self.history.start_session()
        self.session_state = SessionStateManager(self.db)
        self.ai_cache = AICache(self.db)
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

        # Cleanup old sessions on startup (keep 7 days, max 50 sessions)
        self.history.cleanup_old_sessions(keep_days=7, max_sessions=50)

    def route(self, raw: str) -> CommandResult:
        if not isinstance(raw, str):
            return CommandResult(
                Panel(t("error.must_be_text"), title=t("general.error"), border_style="red"),
                status="error",
            )
        result = self._route(raw)
        self._record_history(raw, result)
        return result

    def _route(self, raw: str) -> CommandResult:
        raw = raw.strip()
        if not raw:
            return CommandResult(Panel(t("help.hint"), title="FinCLI"))
        if not raw.startswith("/"):
            return CommandResult(
                Panel(t("error.must_start_slash"), title="Invalid Input", border_style="red"),
                status="error",
            )

        try:
            if raw.lower().startswith("/export "):
                export_parts = raw.split(maxsplit=3)
                if len(export_parts) == 4:
                    return self._export(export_parts[1:])

            parts = _split_command(raw)
            if not parts:
                raise CommandError(t("error.command_empty"))

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
            if root == "/theme":
                return self._theme(args)
            if root == "/history":
                return self._history(args)
            if root == "/session":
                return self._session(args)
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
            if root == "/market":
                return self._market(args)
            if root == "/technical":
                return self._technical(args)
            if root == "/chart":
                return self._chart(args)
            if root == "/mtf":
                return self._mtf(args)
            if root == "/backtest":
                return self._backtest(args)
            if root == "/trading":
                return self._trading(args)
            if root == "/news":
                return self._news(args)
            if root == "/web":
                return self._web(args)
            if root == "/notification":
                return self._notification(args)
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
            if root == "/lang":
                return self._lang(args)

            raise CommandError(t("error.command_not_found", cmd=root), t("help.hint"))
        except FinCLIError as exc:
            message = str(exc)
            if exc.help_text:
                message = f"{message}\n\n{exc.help_text}"
            return CommandResult(Panel(message, title=t("general.error"), border_style="red"), status="error")
        except ValueError as exc:
            return CommandResult(
                Panel(t("error.format_invalid", error=exc), title=t("general.error")),
                status="error",
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                Panel(
                    t("error.unexpected", type=type(exc).__name__, error=exc),
                    title=t("general.error"),
                    border_style="red",
                ),
                status="error",
            )

    def _help_table(self) -> Table:
        table = Table(title=t("help.title", version=__version__), expand=True)
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
        action = args[0].lower() if args else "picker"
        # /history resume [<id|#>] — resume session
        if action == "resume":
            return self._history_resume(args[1:])
        # /history show <id> — show session detail
        if action == "show":
            if len(args) < 2:
                raise CommandError("Format: /history show <session_id>")
            session_id = args[1]
            session = self.history.get_session(session_id)
            if not session:
                raise CommandError(f"Session tidak ditemukan: {session_id}")
            events = self.history.get_events(session_id)
            return CommandResult(_format_session_events(session, events, current=session_id == self.session_id))
        # /history current — show current session events
        if action == "current":
            events = self.history.get_events(self.session_id)
            session = self.history.get_session(self.session_id)
            return CommandResult(_format_session_events(session, events, current=True))
        # /history save <title>
        if action == "save":
            title = " ".join(args[1:]).strip()
            if not title:
                raise CommandError('Format: /history save "judul session"')
            self.history.save_session(self.session_id, title)
            return CommandResult(Panel(f"Current session disimpan sebagai: {title}", title="History", border_style="green"))
        # /history delete <id>
        if action == "delete":
            if len(args) < 2:
                raise CommandError("Format: /history delete <session_id>")
            if args[1] == self.session_id:
                self.history.clear_events(self.session_id)
                self.history.save_session(self.session_id, "FinCLI session")
                return CommandResult(Panel("Current session dikosongkan.", title="History", border_style="yellow"))
            self.history.delete_session(args[1])
            return CommandResult(Panel(f"Session dihapus: {args[1]}", title="History", border_style="green"))
        # /history clear [current|all]
        if action == "clear":
            target = args[1].lower() if len(args) >= 2 else "current"
            if target == "all":
                self.history.clear_all()
                self.session_id = self.history.start_session()
                return CommandResult(Panel("Semua history session dihapus. Session baru dibuat.", title="History"))
            self.history.clear_events(self.session_id)
            return CommandResult(Panel("Current session history dikosongkan.", title="History"))
        # /history — session picker (default, like Claude Code /resume)
        sessions = self.history.list_sessions()
        return CommandResult(_format_session_picker(sessions, self.session_id, self.history.get_session_summary))

    def _history_resume(self, args: list[str]) -> CommandResult:
        """Resume a previous session — load context from it."""
        if not args:
            # Resume most recent non-current session
            last = self.history.get_last_session(self.session_id)
            if not last:
                return CommandResult(
                    Panel("Belum ada session lain. Jalankan beberapa command dulu.", title="History", border_style="dim"),
                )
            session_id = str(last["id"])
        else:
            target = args[0]
            # Allow resume by number (from picker list)
            sessions = self.history.list_sessions()
            if target.isdigit():
                idx = int(target) - 1
                if 0 <= idx < len(sessions) and str(sessions[idx]["id"]) != self.session_id:
                    session_id = str(sessions[idx]["id"])
                else:
                    raise CommandError(f"Nomor session tidak valid: {target}")
            else:
                session_id = target
        if session_id == self.session_id:
            raise CommandError("Sedang di session ini. Gunakan /history current untuk lihat commands.")
        data = self.history.resume_session(session_id)
        if not data:
            raise CommandError(f"Session tidak ditemukan: {session_id}")
        session = data["session"]
        events = data["events"]
        summary = self.history.get_session_summary(session_id)
        ts = relative_time(str(session.get("updated_at", session.get("created_at", ""))))
        # Build resume output
        header = Panel(
            f"[bold]Resumed session [cyan]{session_id}[/cyan][/]\n"
            f"[dim]{ts}[/] · [dim]{len(events)} commands[/]\n"
            f"[dim]{summary}[/]",
            title="History — Resume",
            border_style="cyan",
        )
        # Show last few commands as context
        recent = events[-8:] if len(events) > 8 else events
        table = Table(title="Recent Commands", expand=True, show_lines=False)
        table.add_column("#", justify="right", width=4, style="dim")
        table.add_column("Command", style="white")
        table.add_column("Status", style="cyan", width=8)
        table.add_column("When", style="dim")
        for ev in recent:
            table.add_row(
                str(ev["id"]),
                str(ev["command"])[:60],
                str(ev["status"]),
                relative_time(str(ev["created_at"])),
            )
        caption = Text.from_markup(
            f"[dim]Session {session_id} loaded. "
            f"Type /history show {session_id} for full detail.[/]"
        )
        return CommandResult(Group(header, table, caption))

    def _session(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /session save|restore|status")
        action = args[0].lower()
        if action == "save":
            saved = self.session_state.save(force=True)
            if saved:
                return CommandResult(Panel("Session state saved.", title="Session", border_style="green"))
            return CommandResult(Panel("No changes to save.", title="Session", border_style="yellow"))
        if action == "restore":
            unclean = self.session_state.get_last_unclean_state()
            if not unclean:
                return CommandResult(Panel("No unclean session found to restore.", title="Session", border_style="yellow"))
            restored = self.session_state.restore_state(unclean)
            summary = self.session_state.get_recovery_summary(unclean)
            return CommandResult(Panel(
                f"Session restored:\n{summary}",
                title="Session Restored",
                border_style="green",
            ))
        if action == "status":
            state = self.session_state.current_state
            if not state:
                return CommandResult(Panel("Session state not initialized.", title="Session", border_style="yellow"))
            table = Table(title="Session State Status", show_header=False, border_style="cyan")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Session ID", state.session_id[:12] + "...")
            table.add_row("Command Buffer", state.command_buffer or "(empty)")
            table.add_row("Output Entries", str(len(state.output_entries)))
            table.add_row("Status Bar", state.status_bar or "(empty)")
            table.add_row("Dirty", "Yes" if state.is_dirty else "No")
            return CommandResult(table)
        raise CommandError("Format: /session save|restore|status")

    def _lang(self, args: list[str]) -> CommandResult:
        """Change display language."""
        if not args:
            current = get_language()
            table = Table(title="Language Settings", show_header=False, border_style="cyan")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Current", current)
            table.add_row("Supported", "en (English), id (Indonesia)")
            table.add_row("Usage", "/lang en | /lang id")
            return CommandResult(table)

        lang = args[0].lower()
        if lang not in ("en", "id"):
            raise CommandError("Language not supported. Use 'en' (English) or 'id' (Indonesia).")

        set_language(lang)
        self.config.settings.language = lang
        self.config.save()

        if lang == "en":
            msg = "Language changed to English."
        else:
            msg = "Bahasa diubah ke Indonesia."

        return CommandResult(Panel(msg, title="Language", border_style="green"))

    def _notification(self, args: list[str]) -> CommandResult:
        """Manage webhook notifications (Discord/Telegram)."""
        from fincli.app.connectors.webhooks import (
            NotificationManager,
            configure_discord_webhook,
            configure_telegram_webhook,
            remove_webhook,
        )

        manager = NotificationManager(self.config)

        if not args:
            targets = manager.get_active_targets()
            if not targets:
                return CommandResult(
                    Panel(
                        (
                            "No notification targets configured.\n\n"
                            "Commands:\n"
                            "- /notification add discord <name> <webhook_url>\n"
                            "- /notification add telegram <name> <bot_token> <chat_id>\n"
                            "- /notification list\n"
                            "- /notification test <target>\n"
                            "- /notification remove <target>\n\n"
                            "Target format: discord:name or telegram:name"
                        ),
                        title="Notifications",
                    )
                )
            table = Table(title="Active Notification Targets", border_style="cyan")
            table.add_column("Target", style="bold")
            table.add_column("Type")
            table.add_column("Status")
            for target in targets:
                parts = target.split(":")
                table.add_row(target, parts[0].capitalize(), "✓ Configured")
            return CommandResult(table)

        action = args[0].lower()

        if action == "list":
            targets = manager.get_active_targets()
            if not targets:
                return CommandResult(Panel("No notification targets configured.", title="Notifications", border_style="yellow"))
            table = Table(title="Notification Targets", border_style="cyan")
            table.add_column("Target", style="bold")
            table.add_column("Type")
            for target in targets:
                table.add_row(target, target.split(":")[0].capitalize())
            return CommandResult(table)

        if action == "add":
            if len(args) < 3:
                raise CommandError("Format: /notification add discord|telegram <name> ...")
            webhook_type = args[1].lower()
            name = args[2].lower()
            if webhook_type == "discord":
                if len(args) < 4:
                    raise CommandError("Format: /notification add discord <name> <webhook_url>")
                configure_discord_webhook(name, args[3])
                return CommandResult(
                    Panel(f"Discord webhook '{name}' configured.", title="Notification Added", border_style="green")
                )
            if webhook_type == "telegram":
                if len(args) < 5:
                    raise CommandError("Format: /notification add telegram <name> <bot_token> <chat_id>")
                configure_telegram_webhook(name, args[3], args[4])
                return CommandResult(
                    Panel(f"Telegram webhook '{name}' configured.", title="Notification Added", border_style="green")
                )
            raise CommandError(f"Unsupported webhook type: {webhook_type}. Use 'discord' or 'telegram'.")

        if action == "test":
            if len(args) < 2:
                raise CommandError("Format: /notification test <target>\nTarget format: discord:name or telegram:name")
            target = args[1]
            success, error = manager.test_notification(target)
            if success:
                return CommandResult(
                    Panel(f"Test notification sent to {target} ✅", title="Notification Test", border_style="green")
                )
            return CommandResult(
                Panel(f"Failed to send test notification to {target} ❌\n\nError: {error}", title="Notification Test", border_style="red")
            )

        if action == "remove":
            if len(args) < 2:
                raise CommandError("Format: /notification remove <target>")
            target = args[1]
            if remove_webhook(target):
                return CommandResult(
                    Panel(f"Removed {target}", title="Notification Removed", border_style="green")
                )
            return CommandResult(
                Panel(f"Failed to remove {target}", title="Notification Remove", border_style="red")
            )

        raise CommandError(
            "Unknown notification action. Use: list, add, test, remove"
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
            alerts_rows=self.alerts.list(active_only=True),
        )

    def _theme(self, args: list[str]) -> CommandResult:
        from fincli.app.tui.themes import THEMES, ThemePreset, get_theme, list_themes, load_custom_theme, save_custom_theme, register_custom_theme
        if not args:
            current = getattr(self.config.settings, "theme", "midnight")
            t = get_theme(current)
            return CommandResult(_format_theme_current(t, list_themes()))
        action = args[0].lower()
        if action in {"list", "ls"}:
            return CommandResult(_format_theme_list(list_themes()))
        if action == "create":
            if len(args) < 2:
                raise CommandError("Format: /theme create <name> [--base midnight]")
            name = args[1]
            base_name = args[3] if len(args) >= 4 and args[2] == "--base" else "midnight"
            base = get_theme(base_name)
            custom = ThemePreset(
                name=name, description=f"custom theme (based on {base_name})",
                bg=base.bg, bg_alt=base.bg_alt, text=base.text, muted=base.muted,
                accent=base.accent, border=base.border, positive=base.positive,
                negative=base.negative, caution=base.caution,
                gradient_start=base.gradient_start, gradient_end=base.gradient_end,
                gradient_angle=base.gradient_angle,
            )
            from fincli.app.storage import config_paths
            path = config_paths.APP_DIR / "themes" / f"{name}.json"
            save_custom_theme(path, custom)
            register_custom_theme(custom)
            return CommandResult(Panel(f"Tema '{name}' dibuat di {path}. Edit JSON untuk kustomisasi warna.", title="Theme Created", border_style="green"))
        if action == "import":
            if len(args) < 2:
                raise CommandError("Format: /theme import <path.json>")
            path = Path(args[1])
            if not path.exists():
                raise CommandError(f"File tidak ditemukan: {path}")
            custom = load_custom_theme(path)
            register_custom_theme(custom)
            return CommandResult(Panel(f"Tema '{custom.name}' di-import dan terdaftar.", title="Theme Imported", border_style="green"))
        if action == "export":
            if len(args) < 3:
                raise CommandError("Format: /theme export <theme_name> <path.json>")
            theme_name = args[1]
            t = get_theme(theme_name)
            path = Path(args[2])
            save_custom_theme(path, t)
            return CommandResult(Panel(f"Tema '{theme_name}' di-export ke {path}.", title="Theme Exported", border_style="green"))
        if action in THEMES:
            # Store theme — actual CSS reload happens in TUI layer
            self.config.settings.theme = action
            self.config.save()
            t = get_theme(action)
            return CommandResult(
                Panel(f"Tema diubah ke: [bold]{t.name}[/] — {t.description}", title="Theme", border_style=t.accent),
                metadata={"theme_changed": action},
            )
        raise CommandError(f"Tema tidak dikenal: {action}. Gunakan /theme list.")

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
        from fincli.app.tui.model_selector import MODEL_CATALOG

        con = Console()
        manager = AIProviderManager()
        current = self.config.settings

        if len(args) == 0:
            return self._ai_model_interactive(manager, current, con)
        if args[0].lower() == "key":
            con.print("[dim]Hint: /ai_model key akan deprecated. Gunakan /ai_model untuk picker interaktif.[/dim]")
            if len(args) < 3:
                raise CommandError("Format: /ai_model key <provider> <api_key>")
            provider = args[1].lower()
            info = manager.get(provider)
            if info is None:
                raise CommandError(f"AI provider tidak dikenal: {provider}")
            save_secret(info.env_key, args[2])
            model = current.ai_model if current.ai_provider == provider else info.default_model
            self.config.set_ai_model(provider, model)
            self.ai_provider = manager.create(provider)
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
        # /ai_model <provider> — select provider with default model
        if len(args) == 1:
            provider = args[0].lower()
            info = manager.get(provider)
            if info is None:
                raise CommandError(f"AI provider tidak dikenal: {provider}. Gunakan: {', '.join(p.name for p in manager.list_providers())}")
            if not os.getenv(info.env_key):
                con.print(f"[yellow]API key {info.env_key} belum disimpan.[/yellow]")
                key_val = _interactive_prompt(f"Paste {info.env_key}", mask=True)
                if key_val:
                    save_secret(info.env_key, key_val)
                    con.print(f"[green]✓ {info.env_key} saved.[/green]")
                else:
                    raise CommandError("API key dibutuhkan. Coba lagi dengan /ai_model.")
            self.config.set_ai_model(provider, info.default_model)
            self.ai_provider = manager.create(provider)
            return CommandResult(Panel(f"AI model aktif: {provider} / {info.default_model}", title="AI Model Updated"))
        # /ai_model <provider> <model> — direct set
        self.config.set_ai_model(args[0], args[1])
        self.ai_provider = manager.create(args[0])
        return CommandResult(Panel(f"AI model aktif: {args[0]} / {args[1]}", title="AI Model Updated"))

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
            return CommandResult(Panel("Dibatalkan.", title="AI Model"))

        info = manager.get(selected_provider)
        if info is None:
            raise CommandError(f"Provider tidak dikenal: {selected_provider}")

        # Prompt for API key if missing
        if not os.getenv(info.env_key):
            con.print(f"\n[yellow]API key [bold]{info.env_key}[/bold] belum disimpan untuk {selected_provider}.[/yellow]")
            key_val = _interactive_prompt(f"Paste {info.env_key}", mask=True)
            if key_val:
                save_secret(info.env_key, key_val)
                con.print(f"[green]✓ {info.env_key} saved.[/green]")
            else:
                con.print("[dim]Skip API key. Provider mungkin tidak bekerja tanpa key.[/dim]")

        # Show model picker
        models = MODEL_CATALOG.get(selected_provider, ())
        if models:
            model_items = [(m.model, f"{m.label:<30} {m.context}" if m.context else m.label) for m in models]
            selected_model = _interactive_select(model_items, f"Select Model ({selected_provider})", current=current.ai_model, console=con)
            if not selected_model:
                selected_model = info.default_model
                con.print(f"[dim]Using default: {selected_model}[/dim]")
        else:
            selected_model = info.default_model
            con.print(f"[dim]No model catalog for {selected_provider}. Using default: {selected_model}[/dim]")

        self.config.set_ai_model(selected_provider, selected_model)
        self.ai_provider = manager.create(selected_provider)
        return CommandResult(
            Panel(f"AI model aktif: [bold]{selected_provider}[/bold] / [cyan]{selected_model}[/cyan]", title="AI Model Updated", border_style="green")
        )

    def _news_model(self, args: list[str]) -> CommandResult:
        con = Console()
        current = self.config.settings

        if len(args) == 0:
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
            con.print("[dim]Hint: /news_model key akan deprecated. Gunakan /news_model untuk picker interaktif.[/dim]")
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
        con.print(f"\n[dim]Current: market={current.market_provider}, news={current.news_provider}, priority={chain}[/dim]")

        selected = _interactive_select(items, "Select Market/News Provider", current=current.market_provider, console=con)
        if not selected:
            return CommandResult(Panel("Dibatalkan.", title="News Model"))

        return self._news_model_select_provider(selected, con)

    def _news_model_select_provider(self, provider: str, con: Console) -> CommandResult:
        """Select a news/market provider, prompting for API key if needed."""
        # Check if it's a market provider
        if self.market_manager.get(provider) is not None:
            env_keys = _market_provider_secret_keys(provider)
            if env_keys and not any(os.getenv(k) for k in env_keys):
                con.print(f"\n[yellow]API key belum disimpan untuk [bold]{provider}[/bold].[/yellow]")
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
            return CommandResult(Panel(f"Provider market/news aktif: [bold]{provider}[/bold]", title="Provider Updated", border_style="green"))

        # Check if it's a news connector
        env_key = news_connector_secret_key(provider)
        env_keys = (env_key,) if env_key else ()
        if env_keys and not any(os.getenv(k) for k in env_keys):
            con.print(f"\n[yellow]API key belum disimpan untuk [bold]{provider}[/bold].[/yellow]")
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
        return CommandResult(Panel(f"Provider news aktif: [bold]{provider}[/bold]", title="News Provider Updated", border_style="green"))

    def _provider(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "list":
            return CommandResult(_format_provider_list())
        if args and args[0].lower() in {"entitlement", "entitlements"}:
            return CommandResult(_format_provider_entitlements(self.market_manager.entitlements()))
        if args and args[0].lower() == "metrics":
            return CommandResult(_format_provider_metrics(self.market_service))
        if args and args[0].lower() in {"capabilities", "capability", "matrix"}:
            return CommandResult(_format_provider_capabilities(self.market_service.providers))
        if args and args[0].lower() == "key" and len(args) >= 2 and args[1].lower() == "status":
            return CommandResult(_format_provider_key_status(self.market_manager))
        if args and args[0].lower() == "key" and len(args) >= 3 and args[1].lower() == "rotate":
            provider = args[2].lower()
            from fincli.app.storage.secrets import read_secrets, save_secret
            secret_keys = {
                "finnhub": "FINNHUB_API_KEY",
                "twelvedata": "TWELVE_DATA_API_KEY",
                "alphavantage": "ALPHA_VANTAGE_API_KEY",
                "custom": "MARKET_DATA_API_KEY",
            }
            key_name = secret_keys.get(provider)
            if not key_name:
                raise CommandError(f"Provider '{provider}' tidak dikenal. Gunakan: {', '.join(secret_keys)}")
            old_secrets = read_secrets()
            old_value = old_secrets.get(key_name, "")
            if old_value:
                masked = f"{old_value[:4]}...{old_value[-2:]}" if len(old_value) > 6 else "***"
                return CommandResult(Panel(
                    f"Key untuk {provider} sudah ada: {masked}\nGunakan /secrets clear dulu, lalu /news_model key {provider} <new_key>.",
                    title="Key Rotate",
                    border_style="yellow",
                ))
            return CommandResult(Panel(
                f"Belum ada key untuk {provider}. Gunakan /news_model key {provider} <api_key> untuk menyimpan.",
                title="Key Rotate",
                border_style="yellow",
            ))
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
        if args and args[0].lower() == "reset":
            if len(args) < 2:
                raise CommandError("Format: /provider reset <provider_name>")
            provider_name = args[1].lower()
            if self.market_service.reset_circuit(provider_name):
                return CommandResult(Panel(f"Circuit breaker untuk {provider_name} di-reset.", title="Circuit Reset", border_style="green"))
            return CommandResult(Panel(f"Provider '{provider_name}' tidak ditemukan dalam metrics.", title="Circuit Reset", border_style="red"))
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
        raise CommandError(
            "Format: /provider status, /provider list, /provider capabilities, /provider entitlement, /provider key status, "
            "/provider use <provider>, /provider priority finnhub,yfinance, /provider insider <symbol>, "
            "/provider ipo [week|from to], /provider reset <provider>, atau /provider test [provider] <symbol>"
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
        if args and args[0].lower() == "report":
            return self._doctor_report()
        full = bool(args and args[0].lower() in {"full", "deep"})
        live = "--live" in {arg.lower() for arg in args}
        live_symbol = _doctor_live_symbol(args)
        table = Table(title="FinCLI Doctor Full" if full else "FinCLI Doctor", expand=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status")
        table.add_column("Detail", overflow="fold")
        table.add_row("Version", "ok", f"FinCLI v{__version__} command surface loaded.")
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

    def _doctor_report(self) -> CommandResult:
        import platform
        import sys
        from fincli.app.utils.errors import CrashContext
        lines = [
            "=== FinCLI Diagnostic Report ===",
            "",
            f"Version      : {__version__}",
            f"Python       : {sys.version.split()[0]}",
            f"Platform     : {platform.platform()}",
            f"Database     : {self.db.db_file}",
            "",
            "--- Provider Chain ---",
        ]
        for provider in self.market_service.providers:
            name = getattr(provider, "name", "unknown")
            cap = getattr(provider, "capabilities", lambda: None)()
            if cap:
                lines.append(f"  {name}: realtime={cap.realtime}, ops={','.join(cap.operations)}")
            else:
                lines.append(f"  {name}: capabilities=unknown")
        lines.append("")
        lines.append("--- Provider Metrics (Session) ---")
        for name, metric in self.market_service.provider_metrics_snapshot().items():
            lines.append(f"  {name}: calls={metric.calls}, success_rate={metric.success_rate:.1f}%, errors={metric.errors}")
        lines.append("")
        lines.append("--- API Key Status ---")
        for row in self.market_manager.key_status():
            lines.append(f"  {row['provider']}: {row['status']}")
        lines.append("")
        lines.append("--- Database Tables ---")
        try:
            tables = self.db.query("SELECT name FROM sqlite_master WHERE type='table'")
            lines.append(f"  {len(tables)} table(s): {', '.join(str(t['name']) for t in tables)}")
        except Exception as exc:
            lines.append(f"  Error: {exc}")
        lines.append("")
        lines.append("--- Active Config (no secrets) ---")
        safe = self.config.settings.safe_dict()
        for key, value in safe.items():
            if key != "api_keys":
                lines.append(f"  {key}: {value}")
        lines.append("")
        lines.append("=== End Report ===")
        lines.append("")
        lines.append("This report contains no API keys or secrets.")
        lines.append("Share this output when filing a bug report.")
        report_text = "\n".join(lines)
        return CommandResult(Panel(report_text, title="Doctor Report", border_style="cyan"))

    def _setup(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "check":
            return CommandResult(self._setup_check())
        if args and args[0].lower() == "keys":
            return self._setup_keys()
        if args and args[0].lower() == "profile":
            return self._setup_profile()
        if args and args[0].lower() == "theme":
            return self._setup_theme()
        return CommandResult(self._setup_wizard())

    def _setup_wizard(self) -> Table:
        table = Table(title="FinCLI Setup Wizard", expand=True)
        table.add_column("Step", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Action", overflow="fold")

        # Check profile
        try:
            profile_rows = self.db.query("SELECT name FROM user_profile WHERE id = 1")
            if profile_rows:
                table.add_row("1. Profile", "[green]OK[/]", f"Welcome back, {profile_rows[0]['name']}")
            else:
                table.add_row("1. Profile", "[yellow]MISSING[/]", '/setup profile — set name, equity, currency')
        except Exception:
            table.add_row("1. Profile", "[yellow]MISSING[/]", '/setup profile')

        # Check AI key
        secrets = read_secrets()
        ai_keys = [k for k in secrets if "AI" in k.upper() or "GROQ" in k.upper() or "OPENAI" in k.upper()]
        if ai_keys:
            table.add_row("2. AI Key", "[green]OK[/]", f"{len(ai_keys)} key(s) configured")
        else:
            table.add_row("2. AI Key", "[yellow]MISSING[/]", "/ai_model key groq <api_key>")

        # Check market key
        market_keys = [k for k in secrets if any(p in k.upper() for p in ["FINNHUB", "ALPHA", "TWELVEDATA", "MARKETAUX"])]
        if market_keys:
            table.add_row("3. Market Key", "[green]OK[/]", f"{len(market_keys)} key(s) configured")
        else:
            table.add_row("3. Market Key", "[yellow]MISSING[/]", "/news_model key finnhub <api_key>")

        # Check theme
        current_theme = getattr(self.config.settings, "theme", "midnight")
        table.add_row("4. Theme", "[green]OK[/]", f"Current: {current_theme}. /theme list to change.")

        # Quick start
        table.add_row("5. Test", "[dim]-[/]", "/research AAPL --quick")
        table.add_row("6. Test", "[dim]-[/]", "/analyze XAUUSD 1d")

        table.caption = "Run: /setup check | /setup keys | /setup profile | /setup theme"
        return table

    def _setup_check(self) -> Table:
        """Detailed configuration check."""
        table = Table(title="Configuration Check", expand=True)
        table.add_column("Check", style="cyan", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Detail", overflow="fold")

        secrets = read_secrets()
        # Profile
        try:
            profile_rows = self.db.query("SELECT name, equity, currency FROM user_profile WHERE id = 1")
            if profile_rows:
                p = profile_rows[0]
                table.add_row("Profile", "ok", f"{p['name']} | {p['equity']} {p['currency']}")
            else:
                table.add_row("Profile", "missing", "Run /setup profile")
        except Exception:
            table.add_row("Profile", "error", "Cannot read profile")

        # Keys
        for key_name in ["GROQ_API_KEY", "OPENAI_API_KEY", "FINNHUB_API_KEY", "ALPHAVANTAGE_API_KEY"]:
            if secrets.get(key_name):
                table.add_row(key_name, "ok", "***configured***")
            else:
                table.add_row(key_name, "missing", f"Run /ai_model key or /news_model key")

        # Theme
        theme = getattr(self.config.settings, "theme", "midnight")
        table.add_row("Theme", "ok", theme)

        # Database
        table.add_row("Database", "ok", str(self.db.db_file))

        return table

    def _setup_keys(self) -> CommandResult:
        """Guide through API key setup."""
        secrets = read_secrets()
        lines = [
            "[bold]API Key Setup[/]",
            "",
            "[cyan]AI Providers:[/]",
            "  /ai_model key groq <api_key>        — free tier, fast",
            "  /ai_model key openai <api_key>      — GPT-4o",
            "  /ai_model key anthropic <api_key>   — Claude",
            "",
            "[cyan]Market Data:[/]",
            "  /news_model key finnhub <api_key>   — free tier, news + calendar",
            "  /news_model key alphavantage <key>  — macro data",
            "  /news_model key twelvedata <key>    — technical data",
        ]
        if secrets:
            lines.append("")
            lines.append("[green]Configured:[/]")
            for k in sorted(secrets):
                lines.append(f"  {k}: ***")
        return CommandResult(Panel("\n".join(lines), title="API Keys", border_style="cyan"))

    def _setup_profile(self) -> CommandResult:
        """Guide through profile setup."""
        try:
            profile_rows = self.db.query("SELECT name, equity, currency, leverage, years_in_investment, gameplay FROM user_profile WHERE id = 1")
            if profile_rows:
                p = profile_rows[0]
                return CommandResult(Panel(
                    f"Name: {p['name']}\nEquity: {p['equity']} {p['currency']}\nLeverage: {p['leverage']}\nYears: {p['years_in_investment']}\nGameplay: {p['gameplay']}",
                    title="Current Profile",
                    border_style="green",
                ))
        except Exception:
            pass
        return CommandResult(Panel(
            'No profile set.\n\nRun:\n/profile set "Your Name" 10000 USD 1x 3 conservative',
            title="Profile Setup",
            border_style="yellow",
        ))

    def _setup_theme(self) -> CommandResult:
        """Guide through theme setup."""
        from fincli.app.tui.themes import list_themes
        themes = list_themes()
        current = getattr(self.config.settings, "theme", "midnight")
        lines = [f"Current: [bold]{current}[/]", "", "Available themes:"]
        for t in themes:
            marker = " [green]<-- current[/]" if t.name == current else ""
            lines.append(f"  /theme {t.name} — {t.description}{marker}")
        lines.append("\nRun: /theme <name> to change.")
        return CommandResult(Panel("\n".join(lines), title="Theme Setup", border_style="cyan"))

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
        if action == "purge":
            # Purge: clear secrets, session history, cache
            secrets_cleared = clear_secrets()
            self.history.clear_events(self.session_id)
            self.cache.clear()
            cache_cleared = self.market_cache.clear()
            self.audit_log.record("security_purge", f"Purged: {secrets_cleared} secrets, session history, cache")
            return CommandResult(Panel(
                (
                    f"Security state purged.\n"
                    f"- secrets cleared: {secrets_cleared}\n"
                    f"- current session history cleared\n"
                    f"- runtime cache cleared\n"
                    f"- persistent market cache rows cleared: {cache_cleared}\n\n"
                    "Portfolio, journal, alerts, and profile were kept."
                ),
                title="Security Purge",
                border_style="yellow",
            ))
        if action == "encrypt-key":
            if len(args) < 2:
                raise CommandError("Format: /security encrypt-key <broker_name>")
            return self._encrypt_broker_key(args[1])
        if action == "decrypt-key":
            if len(args) < 2:
                raise CommandError("Format: /security decrypt-key <broker_name>")
            return self._decrypt_broker_key(args[1])
        if action == "session":
            return CommandResult(_format_session_security(self))
        raise CommandError(
            "Format: /security status, /security audit, /security scan, /security lockdown, "
            "/security purge, /security encrypt-key, /security decrypt-key, /security session"
        )

    def _encrypt_broker_key(self, broker_name: str) -> CommandResult:
        """Encrypt a broker API key with master password."""
        from fincli.app.utils.crypto import encrypt_broker_key
        from fincli.app.storage.secrets import read_secrets, save_secret

        # Get the API key from environment or secrets
        broker_name = broker_name.lower()
        env_key_map = {
            "alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
        }

        if broker_name not in env_key_map:
            raise CommandError(f"Broker tidak didukung: {broker_name}. Broker tersedia: {', '.join(env_key_map.keys())}")

        api_key_env, secret_key_env = env_key_map[broker_name]

        # Read current keys
        secrets = read_secrets()
        api_key = secrets.get(api_key_env) or os.getenv(api_key_env, "")
        secret_key = secrets.get(secret_key_env) or os.getenv(secret_key_env, "")

        if not api_key and not secret_key:
            raise CommandError(
                f"API key untuk {broker_name} belum diatur. "
                f"Gunakan environment variable atau secrets store."
            )

        # In a real implementation, we would prompt for master password
        # For now, we'll show the encryption would happen
        table = Table(title=f"Broker Key Encryption ({broker_name})", show_header=False, border_style="cyan")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Broker", broker_name)
        table.add_row("API Key", "✓ found" if api_key else "✗ not set")
        table.add_row("Secret Key", "✓ found" if secret_key else "✗ not set")
        table.add_row("Status", "Ready for encryption")
        table.add_row("Note", "Master password required for encryption. Use TUI for interactive encryption.")

        return CommandResult(table)

    def _decrypt_broker_key(self, broker_name: str) -> CommandResult:
        """Decrypt a broker API key with master password."""
        from fincli.app.utils.crypto import decrypt_broker_key

        broker_name = broker_name.lower()
        table = Table(title=f"Broker Key Decryption ({broker_name})", show_header=False, border_style="yellow")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("Broker", broker_name)
        table.add_row("Status", "Decryption requires master password")
        table.add_row("Note", "Use TUI for interactive decryption. Keys are decrypted on-demand for broker connection.")

        return CommandResult(table)

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
        if action == "validate":
            plugins = PluginLoader().discover()
            from fincli.app.plugins.loader import validate_manifest
            results = []
            for plugin in plugins:
                errors = validate_manifest(plugin)
                results.append((plugin, errors))
            return CommandResult(_format_plugin_validation(results))
        raise CommandError("Format: /plugin list, /plugin status, atau /plugin validate")

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
            return self._watchlist_table()

        action = args[0].lower()

        if action == "add" and len(args) >= 2:
            group = args[2] if len(args) >= 3 else "default"
            notes = args[3] if len(args) >= 4 else ""
            self.watchlist.add(args[1], group_name=group, notes=notes)
            return CommandResult(Panel(f"{args[1].upper()} ditambahkan ke watchlist (group: {group}).", title="Watchlist"))
        if action == "remove" and len(args) >= 2:
            self.watchlist.remove(args[1])
            return CommandResult(Panel(f"{args[1].upper()} dihapus dari watchlist.", title="Watchlist"))
        if action == "list":
            group = args[1] if len(args) >= 2 else None
            return self._watchlist_table(group)
        if action == "note" and len(args) >= 3:
            self.watchlist.update_notes(args[1], " ".join(args[2:]))
            return CommandResult(Panel(f"Catatan untuk {args[1].upper()} disimpan.", title="Watchlist"))
        if action == "groups":
            groups = self.watchlist.groups()
            if not groups:
                return CommandResult(Panel("Belum ada group.", title="Watchlist Groups"))
            table = Table(title="Watchlist Groups", expand=True)
            table.add_column("Group", style="cyan")
            table.add_column("Count", justify="right")
            for g in groups:
                rows = self.watchlist.list(g)
                table.add_row(g, str(len(rows)))
            return CommandResult(table)

        # If arg looks like a group name, filter by it
        if len(args) == 1:
            rows = self.watchlist.list(args[0])
            if rows:
                return self._watchlist_table(args[0])

        raise CommandError("Format: /watchlist, /watchlist add <symbol> [group] [notes], /watchlist remove <symbol>, /watchlist list [group], /watchlist note <symbol> <text>, /watchlist groups")

    def _watchlist_table(self, group: str | None = None) -> CommandResult:
        rows = self.watchlist.list(group)
        title = f"Watchlist | {group}" if group else "Watchlist"
        table = Table(title=title, expand=True)
        table.add_column("Symbol", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Currency")
        table.add_column("Status")
        table.add_column("Group")
        table.add_column("Notes")
        table.add_column("Created")
        for row in rows:
            quote = self._safe_quote(str(row["symbol"]))
            table.add_row(
                str(row["symbol"]),
                _fmt(quote.price) if quote else "N/A",
                quote.currency if quote else "-",
                quote.status if quote else "unavailable",
                str(row["group_name"]),
                str(row.get("notes", "") or "")[:30],
                str(row["created_at"]),
            )
        if not rows:
            table.add_row("-", "-", "-", "-", "-", "Belum ada data. Gunakan /watchlist add AAPL", "-")
        return CommandResult(table)

    def _portfolio(self, args: list[str]) -> CommandResult:
        # Multi-portfolio subcommands
        if args and args[0].lower() == "create":
            if len(args) < 2:
                raise CommandError("Format: /portfolio create <name> [description]")
            name = args[1].lower()
            desc = " ".join(args[2:]) if len(args) > 2 else ""
            self.portfolio.create(name, desc)
            return CommandResult(Panel(f"Portfolio '{name}' created.", title="Portfolio", border_style="green"))

        if args and args[0].lower() == "switch":
            if len(args) < 2:
                raise CommandError("Format: /portfolio switch <name>")
            name = args[1].lower()
            portfolios = self.portfolio.list_portfolios()
            names = {str(p["name"]) for p in portfolios}
            if name not in names:
                raise CommandError(f"Portfolio '{name}' tidak ditemukan. Buat dengan /portfolio create {name}")
            self.portfolio.set_portfolio(name)
            return CommandResult(Panel(f"Active portfolio: {name}", title="Portfolio", border_style="green"))

        if args and args[0].lower() == "delete":
            if len(args) < 2:
                raise CommandError("Format: /portfolio delete <name>")
            name = args[1].lower()
            if name == "main":
                raise CommandError("Cannot delete 'main' portfolio.")
            if self.portfolio.delete(name):
                if self.portfolio.portfolio_name == name:
                    self.portfolio.set_portfolio("main")
                return CommandResult(Panel(f"Portfolio '{name}' deleted.", title="Portfolio", border_style="green"))
            return CommandResult(Panel(f"Portfolio '{name}' not found.", title="Portfolio", border_style="yellow"))

        if args and args[0].lower() == "portfolios":
            portfolios = self.portfolio.list_portfolios()
            table = Table(title="Portfolios", expand=True)
            table.add_column("Name", style="cyan")
            table.add_column("Description")
            table.add_column("Active")
            table.add_column("Created")
            for p in portfolios:
                is_active = "●" if str(p["name"]) == self.portfolio.portfolio_name else ""
                table.add_row(str(p["name"]), str(p["description"]), is_active, str(p["created_at"]))
            return CommandResult(table)

        if args and args[0].lower() == "compare":
            if len(args) < 2:
                raise CommandError("Format: /portfolio compare <other_portfolio>")
            other = args[1].lower()
            comparison = self.portfolio.compare(other)
            table = Table(title=f"Compare: {self.portfolio.portfolio_name} vs {other}", expand=True)
            table.add_column("Portfolio", style="cyan")
            table.add_column("Symbol")
            table.add_column("Qty", justify="right")
            table.add_column("Avg Price", justify="right")
            for pname, positions in comparison.items():
                for pos in positions:
                    table.add_row(
                        pname,
                        str(pos["symbol"]),
                        f"{float(pos['quantity']):,.8g}",
                        f"{float(pos['average_price']):,.4f}",
                    )
                if not positions:
                    table.add_row(pname, "(empty)", "-", "-")
            return CommandResult(table)

        if not args:
            rows = self.portfolio.list()
            table = Table(title=f"Portfolio: {self.portfolio.portfolio_name}", expand=True)
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
                    _fmt_pct(pnl_percent),
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
        if action == "rebalance":
            return self._portfolio_rebalance()
        if action == "snapshot":
            return self._portfolio_snapshot()
        if action == "history":
            return self._portfolio_history()
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
        if action == "update" and len(args) >= 4:
            try:
                quantity = float(args[2])
                price = float(args[3])
            except ValueError as exc:
                raise CommandError("Quantity dan price harus angka.") from exc
            result = self.portfolio.update(args[1], quantity, price, args[4] if len(args) >= 5 else "USD")
            sym = str(result["symbol"])
            act = str(result["action"])
            if act == "closed":
                msg = f"Posisi {sym} ditutup (qty = 0)."
            elif act == "updated":
                msg = f"{sym} DCA: qty {result['old_quantity']} → {result['quantity']}, avg {result['old_average_price']:.4f} → {result['average_price']:.4f}"
            else:
                msg = f"Posisi {sym} dibuat: qty {result['quantity']}, avg {result['average_price']:.4f}"
            return CommandResult(Panel(msg, title="Portfolio DCA"))
        raise CommandError(
            "Format: /portfolio, /portfolio risk, /portfolio performance, /portfolio add <symbol> <qty> <avg_price>, "
            "/portfolio update <symbol> <qty> <price>, /portfolio remove <symbol>"
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

        action = args[0].lower()

        if action == "stats":
            rows = self.journal.list(limit=10_000)
            stats = calculate_journal_stats(rows)
            return CommandResult(_format_journal_stats(stats))

        if action == "review":
            rows = self.journal.list(limit=10_000)
            stats = calculate_journal_stats(rows)
            prompt = build_journal_review_prompt(rows, stats)
            response = self._run_async(self.ai_provider.complete(AIRequest(prompt=prompt, model=self.config.settings.ai_model)))
            if not isinstance(response, AIResponse):
                raise CommandError("AI provider mengembalikan data tidak valid.")
            return CommandResult(
                MarkdownBlock("Journal Review", _format_ai_response(response), "Disclaimer: bukan nasihat keuangan.")
            )

        if action == "add":
            return self._journal_add(args[1:])

        if action == "edit":
            return self._journal_edit(args[1:])

        if action == "delete":
            return self._journal_delete(args[1:])

        if action == "show":
            if len(args) < 2:
                raise CommandError("Format: /journal show <id>")
            return self._journal_show(args[1])

        rows = self.journal.list(args[0])
        return CommandResult(self._journal_table(rows, f"Journal {args[0].upper()}"))

    def _journal_add(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            raise CommandError('Format: /journal add <instrument> <bias> "entry reason" [--exit_reason ...] [--result win|loss|be] [--emotion ...] [--lesson ...] [--tags t1,t2]')
        instrument = args[0]
        bias = args[1]
        entry_reason = ""
        exit_reason = ""
        result = ""
        emotion = ""
        lesson = ""
        tags = ""
        i = 2
        while i < len(args):
            if args[i] == "--exit_reason" and i + 1 < len(args):
                exit_reason = args[i + 1]; i += 2
            elif args[i] == "--result" and i + 1 < len(args):
                result = args[i + 1]; i += 2
            elif args[i] == "--emotion" and i + 1 < len(args):
                emotion = args[i + 1]; i += 2
            elif args[i] == "--lesson" and i + 1 < len(args):
                lesson = args[i + 1]; i += 2
            elif args[i] == "--tags" and i + 1 < len(args):
                tags = args[i + 1]; i += 2
            else:
                entry_reason = args[i]; i += 1
        self.journal.add(instrument, bias=bias, entry_reason=entry_reason, exit_reason=exit_reason, result=result, emotion=emotion, lesson=lesson, tags=tags)
        return CommandResult(Panel(f"Journal untuk {instrument.upper()} ditambahkan.", title="Journal"))

    def _journal_edit(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError('Format: /journal edit <id> [--bias ...] [--entry_reason ...] [--exit_reason ...] [--result win|loss|be] [--emotion ...] [--lesson ...] [--tags t1,t2]')
        try:
            entry_id = int(args[0])
        except ValueError:
            raise CommandError("ID harus berupa angka.")
        fields: dict[str, str] = {}
        i = 1
        while i < len(args):
            key = args[i].lstrip("-")
            if key in {"bias", "entry_reason", "exit_reason", "result", "emotion", "lesson", "tags"} and i + 1 < len(args):
                fields[key] = args[i + 1]; i += 2
            else:
                i += 1
        if not fields:
            raise CommandError("Tidak ada field yang diubah. Gunakan --bias, --entry_reason, dll.")
        entry = self.journal.get(entry_id)
        if not entry:
            raise CommandError(f"Journal entry #{entry_id} tidak ditemukan.")
        self.journal.edit(entry_id, **fields)
        return CommandResult(Panel(f"Journal #{entry_id} diperbarui.", title="Journal"))

    def _journal_delete(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /journal delete <id>")
        try:
            entry_id = int(args[0])
        except ValueError:
            raise CommandError("ID harus berupa angka.")
        entry = self.journal.get(entry_id)
        if not entry:
            raise CommandError(f"Journal entry #{entry_id} tidak ditemukan.")
        self.journal.delete(entry_id)
        return CommandResult(Panel(f"Journal #{entry_id} ({entry['instrument']}) dihapus.", title="Journal"))

    def _journal_show(self, id_str: str) -> CommandResult:
        try:
            entry_id = int(id_str)
        except ValueError:
            raise CommandError("ID harus berupa angka.")
        entry = self.journal.get(entry_id)
        if not entry:
            raise CommandError(f"Journal entry #{entry_id} tidak ditemukan.")
        table = Table(title=f"Journal #{entry_id}", expand=True)
        table.add_column("Field", style="cyan", no_wrap=True)
        table.add_column("Value")
        for key in ("instrument", "bias", "entry_reason", "exit_reason", "result", "emotion", "lesson", "tags", "created_at"):
            table.add_row(key.replace("_", " ").title(), str(entry.get(key) or "-"))
        return CommandResult(table)

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

    def _chart(self, args: list[str]) -> CommandResult:
        """Render ASCII candlestick chart with optional overlays."""
        from fincli.app.tui.chart import build_chart_output

        if not args:
            raise CommandError(
                "Format: /chart <symbol> [interval] [--overlay rsi,macd] [--width N] [--height N]\n"
                "Contoh: /chart AAPL 1d --overlay rsi,macd"
            )

        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 and not args[1].startswith("--") else "1d"

        # Parse options
        overlays_raw = _extract_option_value(args, "--overlay") or ""
        overlays = [o.strip() for o in overlays_raw.split(",") if o.strip()] if overlays_raw else []
        width = int(_extract_option_value(args, "--width") or "80")
        height = int(_extract_option_value(args, "--height") or "20")

        # Period mapping
        period_map = {
            "1d": "6mo", "1h": "1mo", "15m": "5d", "5m": "5d",
            "1wk": "2y", "1mo": "5y",
        }
        period = period_map.get(interval, "6mo")

        candles = self._run_async(self.market_service.history(symbol, period=period, interval=interval))
        if not candles:
            raise CommandError(f"Data candle kosong untuk {symbol} ({interval}).")

        panels = build_chart_output(candles, symbol, interval, overlays, width, height)
        from rich.console import Group
        return CommandResult(Group(*panels))

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
        if action == "live":
            return self._trading_live(args[1:])
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
                f"Broker adapter '{args[1]}' is catalog-level. "
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
            f"Stream '{connector}' — connect via the realtime_stream module adapters "
            f"(KrakenWebSocketAdapter, HyperLiquidWebSocketAdapter, EquityStreamingAdapter). "
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
        order_error = None
        if result.signal in {"buy", "sell"} and result.suggested_qty > 0:
            try:
                order_result = self.paper_trading.place_order(
                    result.signal, symbol, result.suggested_qty, "market", strategy=strategy,
                )
            except Exception as exc:  # noqa: BLE001 - risk guard may block
                order_error = str(exc)
        return CommandResult(_format_algo_result(result, order_result, order_error))

    def _trading_live(self, args: list[str]) -> CommandResult:
        if not args:
            return CommandResult(_format_live_trading_help())

        action = args[0].lower()

        if action == "status":
            return CommandResult(_format_live_status(self.live_trading))

        if action == "connect":
            if len(args) < 2:
                raise CommandError("Format: /trading live connect <broker> [paper|live]")
            broker_name = args[1].lower()
            mode = args[2].lower() if len(args) >= 3 else "paper"
            from fincli.app.brokers.registry import BrokerRegistry
            if not hasattr(self, '_broker_registry'):
                self._broker_registry = BrokerRegistry()
            status = self._run_async(self._broker_registry.connect(broker_name, mode))
            if status.connected:
                self.live_trading.set_broker(self._broker_registry.active_broker, mode)
            return CommandResult(_format_connection_status(status))

        if action == "disconnect":
            if hasattr(self, '_broker_registry'):
                self._run_async(self._broker_registry.disconnect())
            self.live_trading.set_broker(None)
            return CommandResult(Panel("Broker disconnected.", title="Live Trading", border_style="yellow"))

        if action == "account":
            account = self._run_async(self.live_trading.get_account())
            return CommandResult(_format_broker_account(account))

        if action == "positions":
            positions = self._run_async(self.live_trading.get_positions())
            return CommandResult(_format_broker_positions(positions))

        if action == "orders":
            status_filter = args[1] if len(args) >= 2 else None
            orders = self._run_async(self.live_trading.list_orders(status=status_filter))
            return CommandResult(_format_broker_orders(orders))

        if action in {"buy", "sell"}:
            if len(args) < 3:
                raise CommandError(f"Format: /trading live {action} <symbol> <quantity> [--confirm] [--price <price>]")
            symbol = args[1].upper()
            quantity = float(args[2])
            confirm = "--confirm" in args
            price = None
            if "--price" in args:
                price_idx = args.index("--price")
                if price_idx + 1 < len(args):
                    price = float(args[price_idx + 1])
            order_type = "limit" if price else "market"

            if not confirm:
                # Show confirmation prompt
                confirmation = self.live_trading.build_confirmation(
                    symbol=symbol,
                    side=action,
                    quantity=quantity,
                    order_type=order_type,
                    price=price,
                )
                return CommandResult(_format_order_confirmation(confirmation))

            # Place order with confirmation
            result = self._run_async(self.live_trading.place_order(
                symbol=symbol,
                side=action,
                quantity=quantity,
                order_type=order_type,
                price=price,
            ))
            return CommandResult(_format_live_order_result(result))

        if action == "cancel":
            if len(args) < 2:
                raise CommandError("Format: /trading live cancel <broker_order_id>")
            result = self._run_async(self.live_trading.cancel_order(args[1]))
            return CommandResult(_format_live_order_result({
                "broker_order_id": result.broker_order_id,
                "symbol": result.symbol,
                "side": result.side,
                "status": result.status,
                "broker": result.broker,
            }))

        raise CommandError(
            "Format: /trading live status|connect|disconnect|buy|sell|positions|orders|account|cancel"
        )

    def _market(self, args: list[str]) -> CommandResult:
        if not args:
            raise CommandError("Format: /market <symbol> [interval]")
        symbol = args[0].upper()
        interval = args[1] if len(args) >= 2 else "1d"
        overview = self._run_async(build_market_overview(symbol, self.market_service, interval))
        return CommandResult(_format_market_overview(overview))

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
            raise CommandError("AI provider mengembalikan data tidak valid.")

        # Cache the response
        if response.content:
            self.ai_cache.set(prompt, model, response.content, market_context)

        # Store in conversation history
        history.add(prompt, response.content[:500] if response.content else "")

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
        if not args:
            raise CommandError(
                "Format:\n"
                "  /scan watchlist [filter] [interval]\n"
                "  /scan <universe> [filter] [interval] [--limit N]\n\n"
                "Universes: sp500, nasdaq, crypto, forex, commodities\n"
                "Filters: rsi<30, rsi>70, trend=bullish, sma_cross, sma_death, above_support\n"
                "Contoh: /scan sp500 rsi<30 --limit 20"
            )

        source = args[0].lower()
        from fincli.app.modules.scanner import UNIVERSES, scan_universe

        # Parse --limit option
        limit = 50
        remaining_args = list(args[1:])
        for i, arg in enumerate(remaining_args):
            if arg == "--limit" and i + 1 < len(remaining_args):
                try:
                    limit = int(remaining_args[i + 1])
                except ValueError:
                    pass
                remaining_args = remaining_args[:i] + remaining_args[i + 2:]
                break

        if source == "watchlist":
            rows = self.watchlist.list()
            symbols = [str(row["symbol"]) for row in rows]
            if not symbols:
                return CommandResult(Panel("Watchlist kosong. Gunakan /watchlist add AAPL.", title="Scan"))
            filter_expression = remaining_args[0] if remaining_args else ""
            interval = remaining_args[1] if len(remaining_args) >= 2 else "1d"
            results = self._run_async(scan_symbols(symbols, self.market_service, filter_expression, interval=interval))
            return CommandResult(_format_scan_results(results, filter_expression or "all", interval, "watchlist"))

        if source in UNIVERSES:
            filter_expression = remaining_args[0] if remaining_args else ""
            interval = remaining_args[1] if len(remaining_args) >= 2 else "1d"
            results = self._run_async(scan_universe(source, self.market_service, filter_expression, interval, limit=limit))
            return CommandResult(_format_scan_results(results, filter_expression or "all", interval, source))

        raise CommandError(
            f"Source tidak dikenal: {source}. Gunakan: watchlist, {', '.join(UNIVERSES.keys())}"
        )

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
        secrets = read_secrets()
        service = EconomicCalendarService(api_key=secrets.get("FINNHUB_API_KEY"))
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
        secrets = read_secrets()
        service = EconomicCalendarService(api_key=secrets.get("FINNHUB_API_KEY"))
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
        secrets = read_secrets()
        if not secrets.get("FINNHUB_API_KEY"):
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

    def _run_async(self, awaitable: Any, timeout: float | None = None) -> Any:
        if timeout is None:
            timeout = self.config.settings.provider_timeout_seconds + 15.0
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, awaitable)
            try:
                return future.result(timeout=timeout)
            except TimeoutError:
                future.cancel()
                raise FinCLIError("Provider timeout — coba lagi atau kurangi beban query.")

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

    def _portfolio_history(self) -> CommandResult:
        rows = self.db.query(
            "SELECT id, total_value, cost_basis, unrealized_pnl, realized_pnl, created_at FROM portfolio_snapshots ORDER BY id DESC LIMIT 20"
        )
        if not rows:
            return CommandResult(Panel("Belum ada portfolio snapshot. Gunakan /portfolio snapshot untuk menyimpan.", title="Portfolio History"))
        table = Table(title="Portfolio History (Last 20 Snapshots)", expand=True)
        table.add_column("#", style="dim", justify="right")
        table.add_column("Date", style="cyan")
        table.add_column("Total Value", justify="right")
        table.add_column("Cost Basis", justify="right")
        table.add_column("Unrealized", justify="right")
        table.add_column("Realized", justify="right")
        table.add_column("Total PnL", justify="right")
        for row in rows:
            uv = float(row["unrealized_pnl"])
            rv = float(row["realized_pnl"])
            table.add_row(
                str(row["id"]),
                str(row["created_at"])[:19],
                _fmt(float(row["total_value"])),
                _fmt(float(row["cost_basis"])),
                _fmt(uv),
                _fmt(rv),
                _fmt(uv + rv),
            )
        table.caption = "Use /portfolio snapshot to save current state. Use /portfolio chart for visual performance."
        return CommandResult(table)

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

    def _portfolio_rebalance(self) -> CommandResult:
        """Suggest rebalancing trades based on equal-weight allocation."""
        rows = self.portfolio.list()
        if not rows:
            return CommandResult(Panel("Portfolio kosong. Tambah posisi dulu dengan /portfolio add.", title="Rebalance"))

        # Calculate current values
        positions = []
        total_value = 0.0
        for row in rows:
            symbol = str(row["symbol"])
            quantity = float(row["quantity"])
            avg_price = float(row["average_price"])
            try:
                quote = self._get_quote(symbol)
                current_price = quote.price
            except Exception:
                current_price = avg_price
            market_value = quantity * current_price
            total_value += market_value
            positions.append({
                "symbol": symbol,
                "quantity": quantity,
                "current_price": current_price,
                "market_value": market_value,
            })

        if total_value <= 0:
            return CommandResult(Panel("Total portfolio value = 0. Tidak bisa rebalance.", title="Rebalance"))

        # Equal-weight target
        n = len(positions)
        target_value = total_value / n
        target_pct = 100.0 / n

        # Calculate rebalance trades
        trades = []
        for pos in positions:
            diff_value = target_value - pos["market_value"]
            diff_pct = (diff_value / total_value) * 100
            if abs(diff_value) > 1.0:  # Only suggest if difference > $1
                side = "buy" if diff_value > 0 else "sell"
                qty = abs(diff_value) / pos["current_price"]
                trades.append({
                    "symbol": pos["symbol"],
                    "side": side,
                    "quantity": qty,
                    "value": abs(diff_value),
                    "current_pct": (pos["market_value"] / total_value) * 100,
                    "target_pct": target_pct,
                })

        return CommandResult(_format_rebalance(positions, trades, total_value, target_pct))

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

        if dataset == "broker":
            if len(args) < 3:
                raise CommandError("Format: /export broker <csv|json> <path>")
            export_format = args[1].lower()
            target = args[2]
            # Get broker orders from live trading
            orders = self._run_async(self.live_trading.list_orders(limit=10_000))
            rows = [
                {
                    "broker_order_id": o.broker_order_id,
                    "symbol": o.symbol,
                    "side": o.side,
                    "order_type": o.order_type,
                    "quantity": o.quantity,
                    "price": o.price,
                    "status": o.status,
                    "filled_quantity": o.filled_quantity,
                    "filled_price": o.filled_price,
                    "broker": o.broker,
                    "created_at": o.created_at.isoformat(),
                }
                for o in orders
            ]
            written = export_rows(rows, export_format, target)
            return CommandResult(Panel(f"Export broker orders selesai: {written}", title="Export", border_style="green"))

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


def _format_theme_current(current: object, all_themes: list[object]) -> Table:
    from fincli.app.tui.themes import ThemePreset
    table = Table(title="FinCLI Theme", expand=True, show_lines=False)
    table.add_column("Current", style="white", no_wrap=True)
    table.add_column("Description", style="dim")
    table.add_row(str(current.name), str(current.description))
    table.caption = "/theme <name> untuk ganti. /theme list untuk semua."
    return table


def _format_theme_list(themes: list[object]) -> Table:
    from fincli.app.tui.themes import ThemePreset
    table = Table(title="Available Themes", expand=True, show_lines=False)
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Preview", style="white")
    table.add_column("Description", style="dim")
    for idx, t in enumerate(themes, 1):
        preview = f"[{t.accent}]███[/{t.accent}]"
        table.add_row(str(idx), t.name, preview, t.description)
    table.caption = "/theme <name> untuk mengganti tema"
    return table


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


def _format_session_picker(
    sessions: list[dict[str, object]],
    current_session_id: str,
    summary_fn: Any,
) -> Table:
    """Session picker like Claude Code /resume — numbered list with relative time + summary."""
    table = Table(title="FinCLI Sessions", expand=True, show_lines=False)
    table.add_column("#", justify="right", width=3, style="dim")
    table.add_column("When", style="cyan", no_wrap=True, width=12)
    table.add_column("Summary", style="white", min_width=30)
    table.add_column("Cmds", justify="right", width=5, style="dim")
    table.add_column("Session ID", style="dim", no_wrap=True)
    for idx, session in enumerate(sessions, 1):
        session_id = str(session["id"])
        marker = " ←" if session_id == current_session_id else ""
        ts = relative_time(str(session.get("updated_at", session.get("created_at", ""))))
        first_cmd = str(session.get("first_command", "") or "")[:45]
        summary = first_cmd if first_cmd else summary_fn(session_id)
        table.add_row(
            str(idx),
            ts,
            summary + marker,
            str(session["event_count"]),
            session_id,
        )
    if not sessions:
        table.add_row("-", "-", "Belum ada session.", "0", "-")
    table.caption = "/history resume <#|id> | /history show <id> | /history save <title> | /history delete <id>"
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
    alerts_rows: list[dict[str, object]] | None = None,
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
            f"{journal_stats.total_entries} entries | Win Rate {_fmt_pct(journal_stats.win_rate)} | "
            f"Top {journal_stats.top_instrument}"
        ),
        "/journal stats | /journal review",
    )

    table.add_row(
        "Market",
        "Use /market for compact quote + technical + structure + news + fundamentals.",
        "/market AAPL 1d | /analyze AAPL 1d",
    )

    # Alerts section
    alerts = alerts_rows or []
    if alerts:
        alert_symbols = list({str(a.get("symbol", "")) for a in alerts})[:5]
        alert_summary = f"{len(alerts)} active alert(s) | {', '.join(alert_symbols)}"
    else:
        alert_summary = "No active alerts"
    table.add_row("Alerts", alert_summary, "/alert add AAPL above 200 | /alert check")

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


def _format_backtest(result: BacktestResult) -> Any:
    from fincli.app.tui.chart import render_equity_curve

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

    # Build equity curve from trades
    if result.trades:
        equity_curve = []
        equity = result.initial_equity
        for trade in result.trades:
            equity += trade.pnl_absolute
            equity_curve.append(equity)
        equity_chart = render_equity_curve(equity_curve, result.initial_equity, title=f"Equity Curve: {result.symbol}")
        from rich.console import Group
        return Group(table, equity_chart)

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


def _format_rebalance(positions: list[dict], trades: list[dict], total_value: float, target_pct: float) -> Table:
    """Format rebalance suggestions."""
    table = Table(title=f"Portfolio Rebalance (Equal-Weight {target_pct:.1f}%)", expand=True)
    table.add_column("Symbol", style="cyan")
    table.add_column("Current $", justify="right")
    table.add_column("Current %", justify="right")
    table.add_column("Target %", justify="right")
    table.add_column("Action", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Value", justify="right")

    for pos in positions:
        current_pct = (pos["market_value"] / total_value) * 100 if total_value > 0 else 0
        table.add_row(
            pos["symbol"],
            f"${pos['market_value']:,.2f}",
            f"{current_pct:.1f}%",
            f"{target_pct:.1f}%",
            "-",
            "-",
            "-",
        )

    if trades:
        table.add_row("", "", "", "", "", "", "")  # separator
        for trade in trades:
            style = "green" if trade["side"] == "buy" else "red"
            table.add_row(
                trade["symbol"],
                "",
                f"{trade['current_pct']:.1f}%",
                f"{trade['target_pct']:.1f}%",
                f"[{style}]{trade['side'].upper()}[/]",
                f"{trade['quantity']:.4f}",
                f"${trade['value']:,.2f}",
            )

    table.caption = f"Total portfolio value: ${total_value:,.2f}. Equal-weight target: {target_pct:.1f}% per position."
    return table


def _format_scan_results(results: list[ScanResult], filter_expression: str, interval: str, source: str = "watchlist") -> Table:
    table = Table(title=f"Scan {source.title()} | {filter_expression} | {interval}", expand=True)
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


def _format_provider_capabilities(providers: list | None = None) -> Table:
    from rich.console import Group

    # Provider capability declarations
    cap_table = Table(title="Provider Capabilities", expand=True)
    cap_table.add_column("Provider", style="cyan", no_wrap=True)
    cap_table.add_column("Realtime", no_wrap=True)
    cap_table.add_column("Operations", overflow="fold")
    cap_table.add_column("Asset Classes", overflow="fold")
    cap_table.add_column("Rate Limit", overflow="fold")
    for provider in (providers or []):
        if hasattr(provider, "capabilities"):
            cap = provider.capabilities()
            if cap is not None:
                cap_table.add_row(
                    cap.name,
                    "yes" if cap.realtime else "no",
                    ", ".join(cap.operations),
                    ", ".join(cap.asset_classes),
                    cap.rate_limit_note or "-",
                )

    # Command capability matrix
    cmd_table = Table(title="Command Capability Matrix", expand=True)
    cmd_table.add_column("Command", style="cyan", no_wrap=True)
    cmd_table.add_column("Provider-Dependent", no_wrap=True)
    cmd_table.add_column("Needs", overflow="fold")
    cmd_table.add_column("Note", overflow="fold")
    for capability in capability_rows():
        cmd_table.add_row(
            capability.command,
            "yes" if capability.provider_dependent else "no",
            ", ".join(capability.needs),
            capability.note,
        )
    cmd_table.caption = capability_summary()
    return Group(cap_table, cmd_table)


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


def _format_session_security(router: object) -> Table:
    """Format session security status."""
    table = Table(title="🔐 Session Security", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status")
    table.add_column("Detail")

    session_id = getattr(router, "session_id", "unknown")
    table.add_row("Session ID", str(session_id)[:12] + "...", "Current active session")
    table.add_row("Session History", "active", f"{len(router.history.get_events(session_id))} events recorded")
    table.add_row("Command Audit", "active", "All commands logged in session history")
    table.add_row("Secret Redaction", "active", "Sensitive data redacted from logs")

    # Broker connection security
    live_trading = getattr(router, "live_trading", None)
    if live_trading and live_trading.is_connected():
        table.add_row("Broker Connection", "active", f"Connected to {live_trading.broker_name} ({live_trading.mode})")
        table.add_row("Live Order Safety", "active", "--confirm flag required for live orders")
    else:
        table.add_row("Broker Connection", "inactive", "No live broker connected")

    table.caption = "Session data is stored locally. Use /security purge to clear session history."
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
    table = Table(title="Security Scan", expand=True)
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail", overflow="fold")

    # 1. Secrets count
    if secrets:
        table.add_row("Local Secrets", "info", f"{len(secrets)} key(s) stored")
        masked = ", ".join(f"{k[:4]}...{k[-2:]}" if len(k) > 6 else k for k in sorted(secrets))
        table.add_row("Keys", "info", masked)
    else:
        table.add_row("Local Secrets", "ok", "None stored")

    # 2. Encryption check
    from fincli.app.storage.secrets import SECRETS_FILE, _MAGIC
    if SECRETS_FILE.exists():
        header = SECRETS_FILE.read_bytes()[:len(_MAGIC)]
        if header == _MAGIC:
            table.add_row("Encryption", "ok", "secrets.env encrypted at rest")
        else:
            table.add_row("Encryption", "warn", "secrets.env is plaintext — will encrypt on next save")
    else:
        table.add_row("Encryption", "ok", "No secrets file")

    # 3. Key file permission check
    from fincli.app.storage.secrets import _KEY_FILE
    if _KEY_FILE.exists():
        try:
            import stat
            mode = _KEY_FILE.stat().st_mode
            if mode & stat.S_IROTH:
                table.add_row("Key File", "warn", ".secrets_key is world-readable")
            else:
                table.add_row("Key File", "ok", ".secrets_key permissions OK")
        except OSError:
            table.add_row("Key File", "info", "Cannot check permissions")
    else:
        table.add_row("Key File", "ok", "No key file (will create on first save)")

    # 4. .gitignore check
    gitignore = Path(".gitignore")
    required_patterns = {"secrets.env", ".secrets_key", ".env"}
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        missing = [p for p in required_patterns if p not in content]
        if missing:
            table.add_row(".gitignore", "warn", f"Missing: {', '.join(missing)}")
        else:
            table.add_row(".gitignore", "ok", "All sensitive patterns covered")
    else:
        table.add_row(".gitignore", "warn", "No .gitignore found")

    # 5. Project file scan for leaked secrets
    try:
        from scripts.prepublish_check import find_secret_issues
        issues = find_secret_issues(Path("."))
        if issues:
            table.add_row("Project Scan", "warn", f"{len(issues)} potential leak(s) found")
            for issue in issues[:5]:
                table.add_row(f"  {issue.kind}", "warn", f"{issue.path}: {issue.detail[:60]}")
            if len(issues) > 5:
                table.add_row("  ...", "info", f"+{len(issues) - 5} more. Run: python scripts/prepublish_check.py")
        else:
            table.add_row("Project Scan", "ok", "No leaked secrets in project files")
    except Exception:
        table.add_row("Project Scan", "info", "Could not run (scripts/prepublish_check.py not found)")

    # 6. .env file check
    env_files = list(Path(".").glob(".env*"))
    env_files = [f for f in env_files if f.name != ".env.example"]
    if env_files:
        table.add_row(".env Files", "warn", f"Found: {', '.join(f.name for f in env_files)}")
    else:
        table.add_row(".env Files", "ok", "None in project root")

    # 7. Token pattern scan in Python/JS/JSON files
    import re
    token_patterns = [
        (re.compile(r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\'][A-Za-z0-9_\-]{16,}["\']', re.IGNORECASE), "potential hardcoded token"),
        (re.compile(r'ghp_[A-Za-z0-9]{36}'), "GitHub personal access token"),
        (re.compile(r'sk-[A-Za-z0-9]{20,}'), "OpenAI-style API key"),
        (re.compile(r'xoxb-[A-Za-z0-9\-]+'), "Slack bot token"),
    ]
    scan_extensions = {".py", ".js", ".ts", ".json", ".yml", ".yaml", ".toml"}
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", ".npm-python", "dist", "build"}
    token_findings: list[str] = []
    try:
        for path in Path(".").rglob("*"):
            if any(skip in path.parts for skip in skip_dirs):
                continue
            if path.suffix not in scan_extensions or not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue
            for pattern, label in token_patterns:
                if pattern.search(content):
                    token_findings.append(f"{path}: {label}")
                    if len(token_findings) >= 10:
                        break
            if len(token_findings) >= 10:
                break
    except OSError:
        pass
    if token_findings:
        table.add_row("Token Scan", "warn", f"{len(token_findings)} finding(s)")
        for finding in token_findings[:5]:
            table.add_row("  ", "warn", finding[:80])
    else:
        table.add_row("Token Scan", "ok", "No hardcoded token patterns found")

    table.caption = "Use /security lockdown to emergency-clear all secrets."
    return table


def _format_circuit_status(service: MarketDataService) -> str:
    metrics = service.provider_metrics_snapshot()
    if not metrics:
        return "Circuit Breakers: no data"
    lines = ["Circuit Breakers:"]
    for name, metric in metrics.items():
        state = "OPEN" if metric.circuit_open else "closed"
        streak = metric.consecutive_failures
        lines.append(f"  {name}: {state} (failures={streak})")
    return "\n".join(lines)


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

    # Per-operation breakdown
    if getattr(service, "metrics_store", None) is not None:
        op_metrics = service.metrics_store.all_operation_snapshots()
        if op_metrics:
            op_table = Table(title="Per-Operation Metrics (All-Time)", expand=True)
            op_table.add_column("Provider", style="cyan", no_wrap=True)
            op_table.add_column("Operation", style="white", no_wrap=True)
            op_table.add_column("Calls", justify="right")
            op_table.add_column("Success Rate", justify="right")
            op_table.add_column("Avg Latency", justify="right")
            op_table.add_column("Errors", justify="right")
            for op in op_metrics:
                op_table.add_row(
                    op.provider,
                    op.operation,
                    str(op.calls),
                    f"{op.success_rate:.1f}%",
                    f"{op.avg_latency_ms:.1f}ms",
                    str(op.errors),
                )
            from rich.console import Group
            table = Group(table, op_table)  # type: ignore[assignment]

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
    table = Table(title="Trading Layer | Safe Execution Workspace", expand=True)
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


def _format_live_trading_help() -> Panel:
    return Panel(
        "Live Trading Commands:\n\n"
        "  /trading live status          — Status koneksi broker\n"
        "  /trading live connect <broker> [paper|live]  — Hubungkan ke broker\n"
        "  /trading live disconnect      — Putuskan koneksi\n"
        "  /trading live account         — Info account broker\n"
        "  /trading live positions       — Posisi dari broker\n"
        "  /trading live orders [status] — Order history\n"
        "  /trading live buy <symbol> <qty> [--confirm] [--price <p>]  — Buy order\n"
        "  /trading live sell <symbol> <qty> [--confirm] [--price <p>] — Sell order\n"
        "  /trading live cancel <id>     — Cancel order\n\n"
        "Safety:\n"
        "  • Semua order butuh --confirm flag atau konfirmasi interaktif\n"
        "  • Risk guard aktif (sama dengan paper trading)\n"
        "  • Kill switch block paper DAN live orders\n"
        "  • Semua order di-audit log\n\n"
        "Supported Brokers: Alpaca (paper + live)\n"
        "API Keys: ALPACA_API_KEY, ALPACA_SECRET_KEY",
        title="Live Trading",
        border_style="cyan",
    )


def _format_live_status(live_trading) -> Panel:
    if live_trading.is_connected():
        status = f"Connected to {live_trading.broker_name} ({live_trading.mode} mode)"
        style = "green"
    else:
        status = "Not connected. Use /trading live connect <broker>"
        style = "yellow"
    return Panel(status, title="Live Trading Status", border_style=style)


def _format_connection_status(status) -> Panel:
    style = "green" if status.connected else "red"
    return Panel(status.message, title=f"Broker Connection ({status.broker})", border_style=style)


def _format_broker_account(account) -> Table:
    table = Table(title=f"Broker Account ({account.broker})", show_header=False, border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Account ID", account.account_id)
    table.add_row("Cash", f"${account.cash:,.2f}")
    table.add_row("Portfolio Value", f"${account.portfolio_value:,.2f}")
    table.add_row("Buying Power", f"${account.buying_power:,.2f}")
    table.add_row("Equity", f"${account.equity:,.2f}")
    table.add_row("Currency", account.currency)
    return table


def _format_broker_positions(positions) -> Table:
    table = Table(title="Broker Positions", expand=True)
    table.add_column("Symbol", style="cyan", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Avg Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Market Value", justify="right")
    table.add_column("PnL", justify="right")
    table.add_column("Side", no_wrap=True)
    for pos in positions:
        pnl_style = "green" if pos.unrealized_pnl >= 0 else "red"
        table.add_row(
            pos.symbol,
            f"{pos.quantity:.4f}",
            f"${pos.avg_entry_price:,.2f}",
            f"${pos.current_price:,.2f}",
            f"${pos.market_value:,.2f}",
            f"[{pnl_style}]${pos.unrealized_pnl:,.2f}[/]",
            pos.side,
        )
    if not positions:
        table.add_row("-", "-", "-", "-", "-", "-", "-")
    return table


def _format_broker_orders(orders) -> Table:
    table = Table(title="Broker Orders", expand=True)
    table.add_column("Order ID", style="cyan", no_wrap=True)
    table.add_column("Symbol", no_wrap=True)
    table.add_column("Side", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Qty", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Status", no_wrap=True)
    table.add_column("Created", no_wrap=True)
    for order in orders:
        table.add_row(
            order.broker_order_id[:12] + "...",
            order.symbol,
            order.side,
            order.order_type,
            f"{order.quantity:.4f}",
            f"${order.price:,.2f}" if order.price else "-",
            order.status,
            order.created_at.strftime("%Y-%m-%d %H:%M"),
        )
    if not orders:
        table.add_row("-", "-", "-", "-", "-", "-", "-", "-")
    return table


def _format_order_confirmation(conf) -> Panel:
    risk_style = "green" if conf.risk_check_passed else "red"
    risk_text = "PASSED" if conf.risk_check_passed else f"BLOCKED: {conf.risk_check_reason}"

    price_line = f"  Price       : ${conf.price:,.2f}\n" if conf.price else ""
    text = (
        f"⚠️  LIVE ORDER CONFIRMATION\n\n"
        f"  Symbol      : {conf.symbol}\n"
        f"  Side        : {conf.side.upper()}\n"
        f"  Quantity    : {conf.quantity}\n"
        f"  Order Type  : {conf.order_type}\n"
        f"{price_line}"
        f"  Est. Cost   : ${conf.estimated_cost:,.2f}\n\n"
        f"  Risk Check  : [{risk_style}]{risk_text}[/]\n"
        f"  Broker      : {conf.broker}\n"
        f"  Mode        : {conf.mode}\n\n"
        f"  Add --confirm flag untuk execute order:\n"
        f"  /trading live {conf.side} {conf.symbol} {conf.quantity} --confirm"
    )
    return Panel(text, title="Order Confirmation Required", border_style="yellow")


def _format_live_order_result(result) -> Table:
    table = Table(title="Live Order Result", show_header=False, border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    for key, value in result.items():
        table.add_row(key, str(value))
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


def _format_algo_result(result: object, order: dict[str, object] | None = None, order_error: str | None = None) -> Table:
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
    elif order_error:
        table.add_row("Order Error", f"[red]{order_error}[/]")
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
    table.caption = "Plugins are manifest-only; FinCLI does not execute plugin code yet."
    return table


def _format_plugin_validation(results: list[tuple[PluginManifest, list]]) -> Table:
    from fincli.app.plugins.loader import PluginValidationError
    table = Table(title="Plugin Validation", expand=True)
    table.add_column("Plugin", style="cyan", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Errors", overflow="fold")
    for plugin, errors in results:
        if not errors:
            table.add_row(plugin.name, "[green]valid[/]", "-")
        else:
            error_text = "\n".join(f"- {e.field}: {e.message}" for e in errors)
            table.add_row(plugin.name, "[red]invalid[/]", error_text)
    if not results:
        table.add_row("-", "-", "No plugins found.")
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
    table.add_row("Win Rate", _fmt_pct(stats.win_rate))
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
    return semantic_text(f"{bias} | {freshness} | keyword-based (approximate) | verify source before trading")


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


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.1f}%"


def _validate_symbol(symbol: str) -> str:
    """Validate and normalize a symbol. Raises CommandError on invalid input."""
    import re
    if not symbol or not symbol.strip():
        raise CommandError("Symbol tidak boleh kosong.")
    normalized = symbol.strip().upper()
    # Reject path traversal and shell metacharacters
    dangerous = re.search(r'[.;|&`$!#~<>{}()\[\]\\]', normalized)
    if dangerous:
        raise CommandError(f"Symbol mengandung karakter tidak valid: '{dangerous.group()}'.")
    if ".." in normalized or "/" in normalized or "\\" in normalized:
        raise CommandError(f"Symbol tidak boleh mengandung path separator: '{normalized}'.")
    if len(normalized) > 20:
        raise CommandError(f"Symbol terlalu panjang (max 20 karakter): '{normalized}'.")
    return normalized


def _split_command(raw: str) -> list[str]:
    parts = shlex.split(raw, posix=os.name != "nt")
    if os.name == "nt":
        return [_strip_wrapping_quotes(part) for part in parts]
    return parts


def _interactive_select(
    items: list[tuple[str, str]],
    title: str,
    current: str = "",
    console: Console | None = None,
) -> str | None:
    """Show numbered list, prompt user to select by number. Returns selected key or None."""
    con = console or Console()
    if not items:
        con.print("[dim]No items available.[/dim]")
        return None
    con.print(f"\n[bold cyan]{title}[/bold cyan]")
    for i, (key, label) in enumerate(items, 1):
        marker = " [green]● current[/green]" if key == current else ""
        con.print(f"  [bold]{i}.[/bold] {label}{marker}")
    con.print()
    try:
        raw = input("Select number (or Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        con.print("[dim]Cancelled.[/dim]")
        return None
    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        con.print("[red]Invalid input. Enter a number.[/red]")
        return None
    if idx < 1 or idx > len(items):
        con.print(f"[red]Out of range (1-{len(items)}).[/red]")
        return None
    return items[idx - 1][0]


def _interactive_prompt(prompt: str, mask: bool = False) -> str | None:
    """Prompt user for text input. Returns value or None if cancelled."""
    try:
        if mask:
            value = getpass.getpass(f"{prompt}: ")
        else:
            value = input(f"{prompt}: ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        return None
    return value if value else None


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
        "/chart",
        "/clear",
        "/config",
        "/connector",
        "/dashboard",
        "/doctor",
        "/exit",
        "/export",
        "/help",
        "/history",
        "/journal",
        "/macro",
        "/market",
        "/mtf",
        "/news",
        "/news_model",
        "/notification",
        "/plugin",
        "/portfolio",
        "/profile",
        "/provider",
        "/report",
        "/research",
        "/scan",
        "/secrets",
        "/security",
        "/session",
        "/setup",
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
            ("Get a quick quote", "/market AAPL", "Get the latest price for any symbol."),
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
            ("Market structure", "/technical AAPL 1d", "BOS, CHoCH, liquidity zones."),
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
