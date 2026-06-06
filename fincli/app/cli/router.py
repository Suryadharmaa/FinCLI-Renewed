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
from fincli.app.analysis.assistant_context import (
    build_web_research_answer_prompt,
    build_fincli_assistant_prompt,
    coding_refusal,
    extract_market_symbols,
    is_coding_request,
)
from fincli.app.analysis.indicators import TechnicalSummary, summarize_technical_indicators
from fincli.app.analysis.market_structure import MarketStructureSummary, analyze_market_structure
from fincli.app.analysis.technical_debate import TechnicalDebate, format_debate, run_technical_debate
from fincli.app.analysis.technical_signal import TechnicalSignal, format_signal
from fincli.app.modules.economic_calendar import (
    EconomicCalendarService,
    EconomicEvent,
    default_calendar_window,
    fallback_events,
    filter_events,
)
from fincli.app.modules.exporter import export_rows
from fincli.app.modules.journal_analytics import JournalStats, build_journal_review_prompt, calculate_journal_stats
from fincli.app.modules.journal import JournalService
from fincli.app.modules.portfolio import PortfolioService
from fincli.app.modules.scanner import ScanResult, scan_symbols
from fincli.app.modules.session_history import SessionHistoryService
from fincli.app.modules.transactions import TransactionService
from fincli.app.modules.watchlist import WatchlistService
from fincli.app.providers.ai.base import AIRequest, AIResponse, BaseAIProvider
from fincli.app.providers.ai.manager import AIProviderManager
from fincli.app.providers.market.base import BaseMarketProvider, FundamentalSnapshot, NewsItem, Quote
from fincli.app.providers.market.manager import MarketProviderManager
from fincli.app.providers.market.yfinance_provider import YahooTable, YFinanceProvider
from fincli.app.services.market_data import MarketDataService
from fincli.app.services.market_overview import MarketOverview, build_market_overview
from fincli.app.services.web_research import (
    WebResearchService,
    WebSearchResult,
    build_web_research_context,
    should_use_web_research,
)
from fincli.app.storage.cache import TTLCache
from fincli.app.storage.config import ConfigManager
from fincli.app.storage.database import FinCLIDatabase
from fincli.app.storage.market_cache import MarketCache
from fincli.app.storage.secrets import save_secret
from fincli.app.utils.errors import CommandError, FinCLIError
from fincli.app.utils.formatting import AIResponseView, MarkdownBlock


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
        self.transactions = TransactionService(self.db, self.portfolio)
        self.journal = JournalService(self.db)
        self.history = SessionHistoryService(self.db)
        self.session_id = self.history.start_session()
        self.web_research = WebResearchService()

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

            parts = shlex.split(raw)
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
            if root == "/quote":
                return self._quote(args)
            if root == "/market":
                return self._market(args)
            if root == "/technical":
                return self._technical(args)
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

    def _help_table(self) -> Table:
        table = Table(title="FinCLI v0.1 Commands", expand=True)
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
            chain = ", ".join(current.market_provider_priority or [current.market_provider])
            return CommandResult(
                Panel(
                    (
                        f"Market: {current.market_provider}\n"
                        f"News: {current.news_provider}\n"
                        f"Fallback priority: {chain}\n\n"
                        "Di TUI, gunakan /news_model untuk membuka provider selector."
                    ),
                    title="Active Data Provider",
                )
            )
        if args[0].lower() == "key":
            if len(args) < 3:
                raise CommandError("Format: /news_model key <provider> <api_key> [base_url untuk custom]")
            provider = args[1].lower()
            env_keys = _market_provider_secret_keys(provider)
            if not env_keys:
                raise CommandError(f"Provider {provider} tidak membutuhkan API key atau tidak dikenal.")
            save_secret(env_keys[0], args[2])
            if provider == "custom" and len(args) >= 4:
                save_secret("MARKET_DATA_BASE_URL", args[3])
            self.config.set_market_provider_priority([provider, *self._priority_tail(provider)])
            self._refresh_market_service()
            self.cache.clear()
            extra = "\nBase URL custom juga disimpan." if provider == "custom" and len(args) >= 4 else ""
            return CommandResult(
                Panel(
                    (
                        f"API key market/news untuk {provider} disimpan global di ~/.fincli/secrets.env.{extra}\n"
                        f"Provider market/news aktif disimpan: {provider}.\n"
                        "Key tidak ditampilkan di terminal dan dipakai lintas session."
                    ),
                    title="Market API Key Saved",
                    border_style="green",
                )
            )
        self.config.set_market_provider(args[0])
        self.config.set_news_provider(args[0])
        self.config.set_market_provider_priority([args[0], *self._priority_tail(args[0])])
        self._refresh_market_service()
        self.cache.clear()
        return CommandResult(Panel(f"Provider market/news aktif: {args[0]}", title="Provider Updated"))

    def _provider(self, args: list[str]) -> CommandResult:
        if args and args[0].lower() == "list":
            return CommandResult(_format_provider_list())
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
            "Format: /provider status, /provider list, /provider key status, /provider use <provider>, "
            "/provider priority finnhub,yfinance, atau /provider test [provider] <symbol>"
        )

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
            raise CommandError("Format: /news <symbol>")
        symbol = args[0].upper()
        items = self._run_async(self.market_service.news(symbol, limit=5))
        return CommandResult(_format_news(symbol, items))

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
        prompt = build_market_analysis_prompt(symbol, timeframe, candles, technical, structure, news_context)
        request = AIRequest(prompt=prompt, model=self.config.settings.ai_model)
        response = self._run_async(self.ai_provider.complete(request))
        if not isinstance(response, AIResponse):
            raise CommandError("AI provider mengembalikan data tidak valid.")
        return CommandResult(
            MarkdownBlock(f"AI Market Analysis: {symbol}", _format_ai_response(response), "Disclaimer: bukan nasihat keuangan.")
        )

    def _scan(self, args: list[str]) -> CommandResult:
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

    def _calendar(self, args: list[str]) -> CommandResult:
        start, end, country, impact = _parse_calendar_args(args)
        service = EconomicCalendarService(api_key=os.getenv("FINNHUB_API_KEY"))
        source = "finnhub"
        note = "Aktual dari provider Finnhub."
        try:
            events = self._run_async(service.events(start, end))
        except FinCLIError as exc:
            events = fallback_events(start, end)
            source = "fallback"
            note = f"{exc} Menggunakan fallback kategori event; isi FINNHUB_API_KEY untuk data aktual."
        events = filter_events(events, country=country, impact=impact)
        return CommandResult(_format_calendar(events, start, end, source, note))

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
        f"{overview.quote.provider} | {overview.quote.status} | {overview.quote.timestamp.isoformat(timespec='seconds')}",
    )
    table.add_row(
        "Technical",
        f"RSI {_fmt(overview.technical.rsi)} | Trend {overview.technical.trend_bias}",
        f"MACD {_fmt(overview.technical.macd)} / Signal {_fmt(overview.technical.macd_signal)} | ATR {_fmt(overview.technical.atr)}",
    )
    table.add_row(
        "Key Levels",
        f"Support {_fmt(overview.technical.support)} | Resistance {_fmt(overview.technical.resistance)}",
        f"Bollinger {_fmt(overview.technical.bollinger_lower)} - {_fmt(overview.technical.bollinger_upper)}",
    )
    table.add_row(
        "Market Structure",
        f"{overview.structure.trend} | {overview.structure.latest_pattern}",
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
            result.trend_bias,
            _fmt(result.support),
            _fmt(result.resistance),
            result.reason,
        )
    if not results:
        table.add_row("-", "-", "-", "-", "-", "-", "Tidak ada symbol yang match.")
    return table


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


def _format_calendar(events: list[EconomicEvent], start: date, end: date, source: str, note: str) -> Table:
    table = Table(title=f"Economic Calendar | {start.isoformat()} to {end.isoformat()} | {source}", expand=True)
    table.add_column("Time", style="cyan", no_wrap=True)
    table.add_column("Country")
    table.add_column("Impact")
    table.add_column("Event", style="white")
    table.add_column("Actual", justify="right")
    table.add_column("Estimate", justify="right")
    table.add_column("Previous", justify="right")

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
    table.add_row("Note", source, "-", note, "-", "-", "-")
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


def _format_provider_key_status(manager: MarketProviderManager) -> Table:
    table = Table(title="Market Provider API Key Status", expand=True)
    table.add_column("Provider", style="cyan")
    table.add_column("Key")
    table.add_column("Status")
    table.add_column("Source")
    for row in manager.key_status():
        table.add_row(row["provider"], row["key"], row["status"], row["source"])
    return table


def _market_provider_secret_keys(provider: str) -> tuple[str, ...]:
    return {
        "custom": ("MARKET_DATA_API_KEY", "MARKET_DATA_BASE_URL"),
        "finnhub": ("FINNHUB_API_KEY",),
        "twelvedata": ("TWELVE_DATA_API_KEY",),
    }.get(provider.lower(), ())


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


class UnavailableAIProvider:
    """Default AI provider used until a concrete API client is configured."""

    def __init__(self, provider_name: str) -> None:
        self.name = provider_name

    async def complete(self, request: AIRequest) -> AIResponse:
        raise CommandError(
            f"AI provider {self.name} belum siap dipakai.",
            "Gunakan /ai_model untuk memilih provider dan /ai_model key <provider> <api_key> untuk menyimpan API key.",
        )
