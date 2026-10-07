# ruff: noqa: F401
"""Command parsing and routing."""

from __future__ import annotations

import asyncio
import getpass
import io
import logging
import os
import shlex
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from fincli import __version__
from fincli.app.agents.registry import Agent, AgentRegistry
from fincli.app.analysis.analyzer import build_market_analysis_prompt, build_technical_ai_summary
from fincli.app.analysis.assistant_context import (
    build_fincli_assistant_prompt,
    build_web_research_answer_prompt,
    coding_refusal,
    extract_market_symbols,
    get_conversation_history,
    is_coding_request,
)
from fincli.app.analysis.backtest import BacktestResult, run_backtest
from fincli.app.analysis.gameplay_plan import format_gameplay_context
from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.analysis.market_structure import MarketStructureSummary, analyze_market_structure
from fincli.app.analysis.multi_timeframe import MultiTimeframeAnalysis, analyze_multi_timeframe
from fincli.app.analysis.technical_debate import TechnicalDebate, format_debate, run_technical_debate
from fincli.app.analysis.technical_signal import TechnicalSignal, format_signal
from fincli.app.cli.commands import CommandRegistry
from fincli.app.cli.handlers.common import (
    PROVIDER_TIMEOUT_BUFFER_SECONDS,
    TUTORIAL_LESSONS,
    UnavailableAIProvider,
    _calendar_data_quality,
    _calendar_fallback_note,
    _calendar_reliability_status,
    _calendar_static_fallback_note,
    _doctor_live_symbol,
    _extract_option_value,
    _fmt,
    _fmt_pct,
    _format_agent,
    _format_agents,
    _format_ai_response,
    _format_alert_checks,
    _format_alert_history,
    _format_alerts,
    _format_audit_events,
    _format_audit_log,
    _format_backtest,
    _format_backtest_compare,
    _format_benchmark,
    _format_broker_account,
    _format_broker_orders,
    _format_broker_positions,
    _format_broker_status,
    _format_brokers,
    _format_calendar,
    _format_circuit_status,
    _format_connection_status,
    _format_connectors,
    _format_correlation_matrix,
    _format_dashboard,
    _format_fundamental_context,
    _format_fundamentals,
    _format_insider_transactions,
    _format_ipo_calendar,
    _format_journal_stats,
    _format_live_order_result,
    _format_live_status,
    _format_live_trading_help,
    _format_macro_dashboard,
    _format_macro_indicator,
    _format_market_overview,
    _format_multi_timeframe,
    _format_news,
    _format_news_connectors,
    _format_news_context,
    _format_news_desk,
    _format_optional_number,
    _format_order_confirmation,
    _format_paper_order,
    _format_paper_orders,
    _format_plugin_validation,
    _format_plugins,
    _format_portfolio_chart,
    _format_portfolio_risk,
    _format_portfolio_tax,
    _format_positions,
    _format_provider_capabilities,
    _format_provider_compare,
    _format_provider_entitlements,
    _format_provider_key_status,
    _format_provider_list,
    _format_provider_metric_detail,
    _format_provider_metrics,
    _format_provider_trust,
    _format_quote,
    _format_realtime_connectors,
    _format_rebalance,
    _format_risk_status,
    _format_scan_results,
    _format_secret_ages,
    _format_secrets_status,
    _format_security_scan,
    _format_security_status,
    _format_session_events,
    _format_session_picker,
    _format_session_security,
    _format_sessions,
    _format_stream_status,
    _format_structure,
    _format_symbol_matrix,
    _format_symbol_search,
    _format_technical,
    _format_theme_current,
    _format_theme_list,
    _format_trading_overview,
    _format_transactions,
    _format_tutorial_menu,
    _format_user_profile,
    _format_web_results,
    _format_whatif,
    _format_yahoo_table,
    _interactive_prompt,
    _interactive_select,
    _macro_error_row,
    _market_provider_secret_keys,
    _metric_trust_label,
    _news_age_days,
    _news_data_quality,
    _news_item_analysis,
    _parse_calendar_args,
    _parse_date_arg,
    _parse_news_lookback,
    _parse_timeframes,
    _provider_metric_reasons,
    _provider_symbol_text,
    _provider_trust_summary,
    _render_history_preview,
    _router_roots,
    _scan_result_rows,
    _split_command,
    _strip_wrapping_quotes,
    _trust_status_label,
    _tutorial_lesson,
    _tutorial_next,
    _validate_symbol,
)
from fincli.app.cli.handlers.intelligence import IntelligenceCommands
from fincli.app.cli.handlers.portfolio import PortfolioCommands
from fincli.app.cli.handlers.providers import ProvidersCommands
from fincli.app.cli.handlers.research import ResearchCommands
from fincli.app.cli.handlers.system import SystemCommands
from fincli.app.cli.handlers.trading import TradingCommands
from fincli.app.cli.result import CommandResult
from fincli.app.connectors.catalog import Connector, ConnectorCatalog
from fincli.app.connectors.news_connectors import (
    NewsConnectorCatalog,
    NewsConnectorManager,
    NewsConnectorSpec,
    news_connector_secret_key,
)
from fincli.app.diagnostics.capabilities import capability_rows, capability_summary
from fincli.app.diagnostics.runtime import check_runtime_environment
from fincli.app.modules.alerts import AlertCheckResult, AlertService, evaluate_alert
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
from fincli.app.modules.exporter import export_rows
from fincli.app.modules.journal import JournalService
from fincli.app.modules.journal_analytics import JournalStats, build_journal_review_prompt, calculate_journal_stats
from fincli.app.modules.portfolio import PortfolioService
from fincli.app.modules.portfolio_risk import PortfolioRiskReport, build_portfolio_risk
from fincli.app.modules.reports import write_market_report
from fincli.app.modules.scanner import ScanResult, scan_symbols
from fincli.app.modules.session_history import SessionHistoryService, relative_time
from fincli.app.modules.trading import (
    BrokerCatalog,
    BrokerIntegration,
    LiveTradingEngine,
    PaperTradingEngine,
    RealtimeConnector,
    RealtimeConnectorCatalog,
)
from fincli.app.modules.transactions import TransactionService
from fincli.app.modules.user_profile import UserProfile, UserProfileService
from fincli.app.modules.watchlist import WatchlistService
from fincli.app.plugins.loader import PluginLoader, PluginManifest
from fincli.app.providers.ai.base import AIRequest, AIResponse
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.providers.market.base import (
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
from fincli.app.research import ResearchEngine, format_research_brief, write_research_report
from fincli.app.services.data_quality import DataQualityReport
from fincli.app.services.data_trust import build_data_trust_gate
from fincli.app.services.macro_data import MacroDataService, MacroIndicator
from fincli.app.services.market_data import MarketDataService
from fincli.app.services.market_overview import MarketOverview, build_market_overview
from fincli.app.services.news_aggregator import NewsAggregator, NewsDesk
from fincli.app.services.web_research import (
    WebResearchService,
    WebSearchResult,
    build_web_research_context,
    should_use_web_research,
)
from fincli.app.storage.ai_cache import AICache
from fincli.app.storage.audit_log import EVENT_SECURITY_VIOLATION, SecurityAuditLog
from fincli.app.storage.cache import TTLCache
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.market_cache import MarketCache
from fincli.app.storage.provider_metrics import ProviderMetricsStore
from fincli.app.storage.secrets import clear_secrets, read_secrets, save_secret
from fincli.app.storage.session_state import SessionStateManager
from fincli.app.utils.errors import CommandError, FinCLIError, ProviderError
from fincli.app.utils.formatting import AIResponseView, MarkdownBlock, semantic_text
from fincli.app.utils.i18n import get_language, set_language, t
from fincli.app.utils.security import RateLimiter, SecretRedactor, SecurityValidator

if TYPE_CHECKING:
    from fincli.app.providers.ai.base import BaseAIProvider
    from fincli.app.providers.market.base import (
        BaseMarketProvider,
    )


logger = logging.getLogger(__name__)

# Constants


class CommandRouter(
    SystemCommands, ProvidersCommands, ResearchCommands, PortfolioCommands, TradingCommands, IntelligenceCommands
):
    """Compose domain handlers behind the stable command routing API."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        db: FinCLIDatabase | None = None,
        registry: CommandRegistry | None = None,
        market_provider: BaseMarketProvider | None = None,
        ai_provider: BaseAIProvider | None = None,
    ) -> None:
        self._workspace_lock = threading.RLock()
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

    @property
    def workspace_service(self):
        from fincli.app.workspace.service import WorkspaceService

        with self._workspace_lock:
            if not hasattr(self, "_workspace_service"):
                self._workspace_service = WorkspaceService(self)
            return self._workspace_service

    def route(self, raw: str) -> CommandResult:
        if not isinstance(raw, str):
            return CommandResult(
                Panel(t("error.must_be_text"), title=t("general.error"), border_style="red"),
                status="error",
            )
        result = self._route(raw)
        self._record_history(raw, result)
        self._maybe_warn_provider_health(result)
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

            # Command aliases
            aliases = {
                "/p": "/portfolio",
                "/t": "/technical",
                "/r": "/research",
                "/b": "/backtest",
                "/w": "/watchlist",
                "/j": "/journal",
                "/m": "/market",
                "/n": "/news",
                "/a": "/alert",
                "/s": "/scan",
            }
            if root in aliases:
                root = aliases[root]

            from fincli.app.workspace.commands import ROOTS, handle

            if root in ROOTS or root == "/portfolio" and args and args[0] == "intelligence":
                return handle(self, root, args)
            if root == "/scan" and "--where" in args:
                return handle(self, "/screen", args)

            if root == "/help":
                return CommandResult(self._help_table())
            if root == "/dashboard":
                return CommandResult(self._dashboard())
            if root == "/clear":
                return CommandResult("", clear=True)
            if root == "/exit":
                return CommandResult("Exiting FinCLI.", should_exit=True)
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
            if root == "/favourites":
                return self._favourites(args)
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
        except Exception as exc:
            logger.debug("History record failed: %s", exc)
            return

    def _maybe_warn_provider_health(self, result: CommandResult) -> None:
        """Append provider health warnings if degraded (non-blocking)."""
        try:
            warnings = self.market_service.check_provider_health()
            if warnings and result.status != "error":
                warning_text = "\n".join(w["warnings"][0] for w in warnings if w.get("warnings"))
                if warning_text:
                    result.metadata = result.metadata or {}
                    result.metadata["provider_warning"] = warning_text
        except Exception as exc:
            logger.debug("Provider health check failed: %s", exc)

    def _run_async(self, awaitable: Any, timeout: float | None = None) -> Any:
        if timeout is None:
            timeout = self.config.settings.provider_timeout_seconds + PROVIDER_TIMEOUT_BUFFER_SECONDS
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
                raise FinCLIError("Provider timeout — try again or reduce query load.") from None

    def shutdown(self) -> None:
        """Stop managed background services before the TUI event loop exits."""
        if hasattr(self, "_workspace_service"):
            self._workspace_service.jobs.shutdown()
        daemon = getattr(self, "_alert_daemon_instance", None)
        if daemon is not None:
            daemon.stop()
